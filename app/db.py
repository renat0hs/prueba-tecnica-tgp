import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# Si falta la variable, la app no arranca (KeyError) en vez de conectarse a algo por defecto.
DATABASE_URL = os.environ["DATABASE_URL"]

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """Abre una sesión por request y la cierra siempre al terminar, aunque haya error."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
