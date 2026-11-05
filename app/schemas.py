import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Letras, números y guiones, separados por al menos un punto. Ej: acme.cl, mi-empresa.com.ar
DOMINIO_REGEX = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")


class LeadCreate(BaseModel):
    """Cuerpo del POST /leads."""

    # extra="forbid": un campo de más (o mal escrito) da 422 en vez de ignorarse.
    # str_strip_whitespace: quita espacios al inicio y al final de cada texto.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nombre_empresa: str = Field(min_length=1, max_length=200)
    dominio: str = Field(min_length=1, max_length=200)
    cargo_contacto: str = Field(min_length=1, max_length=200)

    @field_validator("dominio")
    @classmethod
    def validar_dominio(cls, valor: str) -> str:
        valor = valor.lower()
        if not DOMINIO_REGEX.fullmatch(valor):
            raise ValueError("dominio inválido: usa algo como 'acme.cl', sin https:// ni rutas")
        return valor


class LeadOut(BaseModel):
    """Lo que la API devuelve de un lead."""

    # Permite construirlo directo desde un objeto Lead de SQLAlchemy.
    model_config = ConfigDict(from_attributes=True)

    id: int
    nombre_empresa: str
    dominio: str
    cargo_contacto: str
    estado: str
    correo_asunto: str | None
    correo_cuerpo: str | None
    error_motivo: str | None
    created_at: datetime
