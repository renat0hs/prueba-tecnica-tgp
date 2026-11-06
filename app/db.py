import os

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def normalizar_url(url: str) -> str:
    """Asegura que SQLAlchemy use psycopg 3, el driver que tenemos instalado.

    Render (y Neon) entregan la URL como 'postgresql://...'. Con ese formato SQLAlchemy
    usaría psycopg2, que no está instalado. Si la URL ya trae el driver, se deja igual.
    """
    url_parseada = make_url(url)
    if url_parseada.drivername in ("postgres", "postgresql"):
        url_parseada = url_parseada.set(drivername="postgresql+psycopg")
    return url_parseada.render_as_string(hide_password=False)


# Si falta la variable, la app no arranca (KeyError) en vez de conectarse a algo por defecto.
DATABASE_URL = normalizar_url(os.environ["DATABASE_URL"])

# Número cualquiera que identifica el candado de "crear tablas". Solo tiene que ser
# el mismo en la API y en el worker, y no usarse para otra cosa.
LOCK_CREAR_TABLAS = 2024_0001

# pool_pre_ping: antes de entregar una conexión del pool, verifica que siga viva.
# Si la base se reinició, descarta la conexión muerta y abre otra (sin esto, la primera
# petición después del reinicio falla con 500).
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
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
