from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import crear_tablas, get_db
from app.models import Lead
from app.schemas import LeadCreate, LeadOut


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Al arrancar: crea las tablas que no existan. No modifica tablas que ya existen.
    crear_tablas()
    yield


app = FastAPI(title="TGP Outreach", lifespan=lifespan)


@app.post("/leads", response_model=LeadOut, status_code=201)
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


@app.get("/leads", response_model=list[LeadOut])
def listar_leads(db: Session = Depends(get_db)):
    # Los más nuevos primero; el id desempata si dos tienen la misma fecha.
    consulta = select(Lead).order_by(Lead.created_at.desc(), Lead.id.desc())
    return db.scalars(consulta).all()
