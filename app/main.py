import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import worker
from app.db import crear_tablas, get_db
from app.models import Lead
from app.schemas import LeadCreate, LeadOut


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Al arrancar: crea las tablas que no existan. No modifica tablas que ya existen.
    crear_tablas()
    # En Render free no hay background workers: el worker corre en un hilo de la API.
    # En local va en false, porque el worker es un servicio aparte en docker compose.
    if os.environ.get("RUN_WORKER_IN_API", "false").lower() == "true":
        worker.iniciar_en_segundo_plano()
    yield


app = FastAPI(
    title="TGP Outreach",
    description=(
        "Genera con un LLM un primer correo de outreach B2B para cada lead.\n\n"
        "1. `POST /leads` guarda el lead como `pendiente` y responde al tiro.\n"
        "2. Un worker en segundo plano genera el correo y deja el lead en `procesado` o `error`.\n"
        "3. `GET /leads` muestra el estado y el correo generado."
    ),
    lifespan=lifespan,
)


@app.middleware("http")
async def declarar_utf8(request: Request, call_next):
    # Declara la codificación en todas las respuestas JSON (también en los 404 y 422).
    # JSON siempre va en UTF-8, pero algunos clientes (como PowerShell 5.1) asumen otra
    # codificación si no se la dicen y muestran "ViÃ±a" en vez de "Viña".
    respuesta = await call_next(request)
    if respuesta.headers.get("content-type") == "application/json":
        respuesta.headers["content-type"] = "application/json; charset=utf-8"
    return respuesta


@app.get("/", include_in_schema=False)
def inicio():
    # La URL principal lleva a la documentación interactiva, en vez de responder 404.
    return RedirectResponse("/docs")


@app.post(
    "/leads",
    response_model=LeadOut,
    status_code=201,
    summary="Crear un lead",
    description=(
        "Valida los datos y guarda el lead con estado `pendiente`. Responde al tiro, sin "
        "esperar al LLM: el correo lo genera el worker unos segundos después (revísalo con "
        "`GET /leads`). El dominio va sin `https://` ni rutas, por ejemplo `acme.cl`."
    ),
)
def crear_lead(datos: LeadCreate, db: Session = Depends(get_db)):
    # Solo guarda y responde. El correo lo genera el worker después (estado 'pendiente').
    lead = Lead(
        nombre_empresa=datos.nombre_empresa,
        dominio=datos.dominio,
        cargo_contacto=datos.cargo_contacto,
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)  # trae id, estado y created_at que puso Postgres
    return lead


@app.get(
    "/leads",
    response_model=list[LeadOut],
    summary="Listar los leads",
    description=(
        "Todos los leads, del más nuevo al más antiguo, con su estado, el correo generado "
        "(si ya existe) y el motivo si quedó en `error`."
    ),
)
def listar_leads(db: Session = Depends(get_db)):
    # Los más nuevos primero; el id desempata si dos tienen la misma fecha.
    consulta = select(Lead).order_by(Lead.created_at.desc(), Lead.id.desc())
    return db.scalars(consulta).all()
