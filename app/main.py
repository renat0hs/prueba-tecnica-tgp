from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import models  # noqa: F401  importarlo registra la tabla Lead en Base.metadata
from app.db import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Al arrancar: crea las tablas que no existan. No modifica tablas que ya existen.
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="TGP Outreach", lifespan=lifespan)
