import os

from sqlalchemy.engine import make_url

# --- Base de tests aparte -------------------------------------------------------------
# Esto va ANTES de importar app: app/db.py crea el engine al importarse con DATABASE_URL.
# Misma URL, pero la base se llama "<nombre>_test" (leads -> leads_test). Así los tests
# nunca pueden borrar la base real. Si ya termina en _test (como en CI), se deja igual.
_url = make_url(os.environ["DATABASE_URL"])
if not _url.database.endswith("_test"):
    _url = _url.set(database=f"{_url.database}_test")
os.environ["DATABASE_URL"] = _url.render_as_string(hide_password=False)

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Lead  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def esquema_limpio():
    """Una vez por corrida: recrea las tablas desde el modelo actual."""
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def tabla_vacia():
    """Antes de cada test: tabla vacía y ids desde 1."""
    with engine.begin() as conexion:
        conexion.execute(text("TRUNCATE leads RESTART IDENTITY"))


@pytest.fixture(autouse=True)
def sin_llave_groq(monkeypatch):
    """Ningún test puede llamar al LLM real: si alguno crea un ClienteGroq, falla al tiro."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.fixture
def cliente_api():
    with TestClient(app) as cliente:
        yield cliente


@pytest.fixture
def db():
    sesion = SessionLocal()
    yield sesion
    sesion.close()


@pytest.fixture
def crear_lead():
    """Inserta un lead pendiente y devuelve su id."""

    def _crear(nombre_empresa="Compañía Acme SpA", cargo_contacto="Gerente de Operaciones"):
        with SessionLocal() as sesion:
            lead = Lead(nombre_empresa=nombre_empresa, dominio="acme.cl", cargo_contacto=cargo_contacto)
            sesion.add(lead)
            sesion.commit()
            return lead.id

    return _crear


@pytest.fixture
def leer_lead():
    """Lee el lead desde una sesión nueva: así vemos lo que quedó guardado (con commit)."""

    def _leer(lead_id):
        with SessionLocal() as sesion:
            return sesion.get(Lead, lead_id)

    return _leer
