import logging
import os
import threading
import time
from datetime import timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, crear_tablas
from app.llm import ClienteGroq, ErrorLLM
from app.models import Lead

MAX_INTENTOS = 3
ESPERA_ENTRE_INTENTOS = timedelta(seconds=20)

logger = logging.getLogger("worker")


def tomar_lead_pendiente(db: Session) -> Lead | None:
    """Toma y bloquea el lead pendiente más antiguo que esté listo para procesarse.

    FOR UPDATE: bloquea la fila hasta el commit o rollback de esta transacción.
    SKIP LOCKED: si otro worker ya bloqueó una fila, la salta en vez de esperarla.
    Un lead que ya falló solo se vuelve a tomar cuando pasó ESPERA_ENTRE_INTENTOS.
    """
    consulta = (
        select(Lead)
        .where(
            Lead.estado == "pendiente",
            or_(
                Lead.intentos == 0,
                Lead.updated_at < func.now() - ESPERA_ENTRE_INTENTOS,
            ),
        )
        .order_by(Lead.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    return db.scalars(consulta).first()


def registrar_falla(lead: Lead, motivo: str, reintentable: bool) -> None:
    """Deja el lead en 'pendiente' (para otro intento) o en 'error', con un motivo legible."""
    if reintentable and lead.intentos < MAX_INTENTOS:
        lead.error_motivo = f"{motivo} (intento {lead.intentos} de {MAX_INTENTOS})"
        logger.warning("lead %s: falló, se reintentará: %s", lead.id, lead.error_motivo)
    else:
        lead.estado = "error"
        if reintentable:
            lead.error_motivo = f"{motivo} (intento {lead.intentos} de {MAX_INTENTOS})"
        else:
            lead.error_motivo = f"{motivo} (intento {lead.intentos}, no se reintenta)"
        logger.error("lead %s: quedó en error: %s", lead.id, lead.error_motivo)


def procesar_un_lead(db: Session, cliente_llm) -> bool:
    """Procesa un lead en una sola transacción. Devuelve False si no había ninguno disponible.

    Si el worker se cae antes del commit, Postgres deshace todo: el lead sigue 'pendiente',
    sin sumar el intento, y otro worker lo puede tomar.
    """
    lead = tomar_lead_pendiente(db)
    if lead is None:
        db.rollback()  # cierra la transacción que abrió el SELECT
        return False

    lead.intentos += 1

    try:
        correo = cliente_llm.generar_correo(lead.nombre_empresa, lead.cargo_contacto)
    except ErrorLLM as error:
        registrar_falla(lead, error.motivo, error.reintentable)
    except Exception as error:
        # Un bug no debe dejar el lead tomándose para siempre: cuenta como intento.
        logger.exception("lead %s: error inesperado", lead.id)
        motivo = f"error inesperado al generar el correo ({type(error).__name__})"
        registrar_falla(lead, motivo, reintentable=True)
    else:
        lead.estado = "procesado"
        lead.correo_asunto = correo.asunto
        lead.correo_cuerpo = correo.cuerpo
        lead.error_motivo = None
        logger.info("lead %s: procesado en el intento %s", lead.id, lead.intentos)

    # clock_timestamp() es la hora real de este momento. now() sería la hora en que empezó
    # la transacción (antes de esperar al LLM) y descontaría ese tiempo de la espera.
    lead.updated_at = func.clock_timestamp()
    db.commit()
    return True


def ejecutar_worker(cliente_llm, segundos_sin_trabajo: float) -> None:
    """Loop infinito: procesa leads mientras haya; si no hay, espera y vuelve a mirar."""
    logger.info("worker iniciado")
    while True:
        try:
            with SessionLocal() as db:
                hubo_trabajo = procesar_un_lead(db, cliente_llm)
        except Exception:
            # Ej. la base no responde. Al cerrar la sesión se hace rollback: el lead sigue pendiente.
            logger.exception("error en el worker, se reintenta en %ss", segundos_sin_trabajo)
            hubo_trabajo = False

        if not hubo_trabajo:
            time.sleep(segundos_sin_trabajo)


def configurar_logs() -> None:
    """Muestra los logs INFO del worker. Uvicorn solo configura sus propios loggers,
    así que sin esto los logs del worker no aparecerían cuando corre dentro de la API."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def leer_espera_sin_trabajo() -> float:
    """Segundos que duerme el worker cuando no hay leads (WORKER_POLL_SECONDS)."""
    return float(os.environ.get("WORKER_POLL_SECONDS", "5"))


def iniciar_en_segundo_plano() -> threading.Thread:
    """Corre el worker en un hilo dentro del proceso de la API.

    Se usa en Render free, que no ofrece background workers. daemon=True: el hilo muere con
    el proceso; si estaba a mitad de un lead, Postgres deshace la transacción y el lead
    vuelve a 'pendiente'. Las tablas ya las creó la API antes de llamar a esta función.
    """
    configurar_logs()
    cliente = ClienteGroq()  # sin GROQ_API_KEY lanza RuntimeError y la API no arranca
    hilo = threading.Thread(
        target=ejecutar_worker,
        args=(cliente, leer_espera_sin_trabajo()),
        name="worker",
        daemon=True,
    )
    hilo.start()
    return hilo


if __name__ == "__main__":
    configurar_logs()
    crear_tablas()  # con candado: no choca con la API si arrancan juntas
    ejecutar_worker(ClienteGroq(), leer_espera_sin_trabajo())
