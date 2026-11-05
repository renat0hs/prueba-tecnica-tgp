import os

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Si falta la variable, la app no arranca (KeyError) en vez de conectarse a algo por defecto.
DATABASE_URL = os.environ["DATABASE_URL"]

# Número cualquiera que identifica el candado de "crear tablas". Solo tiene que ser
# el mismo en la API y en el worker, y no usarse para otra cosa.
LOCK_CREAR_TABLAS = 2024_0001

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def crear_tablas():
    """Crea las tablas que falten. Es seguro llamarla desde varios procesos a la vez.

    Sin el candado, si la API y el worker arrancan juntos sobre una base vacía, los dos
    ven que la tabla no existe, los dos hacen CREATE TABLE y uno se cae con "already exists".
    pg_advisory_xact_lock hace que el segundo espere a que el primero termine; cuando entra,
    la tabla ya existe y create_all no hace nada. El candado se suelta solo al cerrar la transacción.
    """
    import app.models  # noqa: F401  registra la tabla Lead en Base.metadata (aquí para evitar import circular)

    with engine.begin() as conexion:
        conexion.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": LOCK_CREAR_TABLAS})
        Base.metadata.create_all(conexion)


def get_db():
    """Abre una sesión por request y la cierra siempre al terminar, aunque haya error."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
