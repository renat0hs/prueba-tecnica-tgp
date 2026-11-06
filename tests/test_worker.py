from datetime import timedelta

import pytest

from app import worker
from app.db import SessionLocal
from app.llm import ErrorLLM
from app.worker import procesar_un_lead, tomar_lead_pendiente
from tests.falsos import CORREO_OK, LLMFalso

TIMEOUT = ErrorLLM("timeout del LLM tras 20s", reintentable=True)
LLAVE_INVALIDA = ErrorLLM("API key de Groq inválida o sin permisos (401)", reintentable=False)


@pytest.fixture
def sin_espera(monkeypatch):
    """Para probar reintentos sin esperar 20 s de verdad."""
    monkeypatch.setattr(worker, "ESPERA_ENTRE_INTENTOS", timedelta(0))


def procesar(llm):
    """Corre el worker una vez, con su propia sesión, como lo hace ejecutar_worker."""
    with SessionLocal() as sesion:
        return procesar_un_lead(sesion, llm)


def test_pendiente_pasa_a_procesado(crear_lead, leer_lead):
    lead_id = crear_lead()
    llm = LLMFalso(CORREO_OK)

    assert procesar(llm) is True

    lead = leer_lead(lead_id)
    assert lead.estado == "procesado"
    assert lead.correo_asunto == "Gerente de Operaciones - Acme"
    assert lead.correo_cuerpo.startswith("Hola, ¿cómo estás?")
    assert lead.intentos == 1
    assert lead.error_motivo is None
    # Al LLM le llegan empresa y cargo, nunca el dominio.
    assert llm.llamadas == [("Compañía Acme SpA", "Gerente de Operaciones")]


def test_sin_leads_pendientes_devuelve_false():
    assert procesar(LLMFalso()) is False


@pytest.mark.parametrize(
    "falla, motivo",
    [
        pytest.param("Claro, aquí tienes el correo: Hola...", "respuesta del LLM no es JSON válido", id="texto no JSON"),
        pytest.param(TIMEOUT, "timeout del LLM tras 20s", id="timeout"),
    ],
)
def test_falla_reintentable_queda_en_error_al_tercer_intento(crear_lead, leer_lead, sin_espera, falla, motivo):
    lead_id = crear_lead()
    llm = LLMFalso(falla, falla, falla)

    procesar(llm)
    lead = leer_lead(lead_id)
    assert (lead.estado, lead.intentos) == ("pendiente", 1)
    assert lead.error_motivo == f"{motivo} (intento 1 de 3)"

    procesar(llm)
    lead = leer_lead(lead_id)
    assert (lead.estado, lead.intentos) == ("pendiente", 2)

    procesar(llm)
    lead = leer_lead(lead_id)
    assert (lead.estado, lead.intentos) == ("error", 3)
    assert lead.error_motivo == f"{motivo} (intento 3 de 3)"

    # Ya en error: el worker no lo vuelve a tomar.
    assert procesar(llm) is False


def test_falla_y_despues_funciona(crear_lead, leer_lead, sin_espera):
    lead_id = crear_lead()
    llm = LLMFalso(TIMEOUT, CORREO_OK)

    procesar(llm)
    procesar(llm)

    lead = leer_lead(lead_id)
    assert lead.estado == "procesado"
    assert lead.intentos == 2
    assert lead.error_motivo is None


def test_falla_no_reintentable_queda_en_error_al_tiro(crear_lead, leer_lead, sin_espera):
    lead_id = crear_lead()

    procesar(LLMFalso(LLAVE_INVALIDA))

    lead = leer_lead(lead_id)
    assert lead.estado == "error"
    assert lead.intentos == 1
    assert lead.error_motivo == "API key de Groq inválida o sin permisos (401) (intento 1, no se reintenta)"
    assert procesar(LLMFalso()) is False


def test_error_inesperado_cuenta_como_intento(crear_lead, leer_lead):
    lead_id = crear_lead()

    procesar(LLMFalso(ValueError("bug")))

    lead = leer_lead(lead_id)
    assert lead.estado == "pendiente"
    assert lead.intentos == 1
    assert lead.error_motivo == "error inesperado al generar el correo (ValueError) (intento 1 de 3)"


def test_respeta_la_espera_entre_intentos(crear_lead, leer_lead):
    # Con la espera real (20 s): un lead que acaba de fallar no se vuelve a tomar.
    lead_id = crear_lead()
    procesar(LLMFalso(TIMEOUT))

    assert procesar(LLMFalso()) is False
    assert leer_lead(lead_id).intentos == 1


def test_skip_locked_dos_workers_no_toman_el_mismo_lead(crear_lead):
    primero, segundo = crear_lead(), crear_lead()
    worker_a, worker_b, worker_c = SessionLocal(), SessionLocal(), SessionLocal()
    try:
        lead_a = tomar_lead_pendiente(worker_a)  # queda bloqueado mientras worker_a no termine
        lead_b = tomar_lead_pendiente(worker_b)
        lead_c = tomar_lead_pendiente(worker_c)

        assert lead_a.id == primero
        assert lead_b.id == segundo  # saltó el bloqueado en vez de esperarlo
        assert lead_c is None  # no queda ninguno libre
    finally:
        worker_a.close()
        worker_b.close()
        worker_c.close()


def test_si_el_worker_muere_antes_del_commit_el_lead_sigue_pendiente(crear_lead, leer_lead):
    lead_id = crear_lead()
    sesion = SessionLocal()
    lead = tomar_lead_pendiente(sesion)
    lead.intentos += 1
    lead.estado = "procesado"
    sesion.close()  # el worker "muere": se cierra sin commit y Postgres deshace todo

    lead = leer_lead(lead_id)
    assert lead.estado == "pendiente"
    assert lead.intentos == 0
    assert procesar(LLMFalso(CORREO_OK)) is True  # otro worker lo puede tomar
