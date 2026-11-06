import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Letras, números y guiones, separados por al menos un punto. Ej: acme.cl, mi-empresa.com.ar
DOMINIO_REGEX = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")

# Largo máximo aceptado para el cuerpo del correo que genera el LLM.
MAX_PALABRAS_CUERPO = 120


class LeadCreate(BaseModel):
    """Cuerpo del POST /leads."""

    # extra="forbid": un campo de más (o mal escrito) da 422 en vez de ignorarse.
    # str_strip_whitespace: quita espacios al inicio y al final de cada texto.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # examples: el valor que Swagger (/docs) deja escrito al apretar "Try it out".
    nombre_empresa: str = Field(min_length=1, max_length=200, examples=["Compañía Acme SpA"])
    dominio: str = Field(min_length=1, max_length=200, examples=["acme.cl"])
    cargo_contacto: str = Field(min_length=1, max_length=200, examples=["Gerente de Operaciones"])

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
    estado: str = Field(description="pendiente, procesado o error")
    correo_asunto: str | None
    correo_cuerpo: str | None
    error_motivo: str | None = Field(description="Por qué falló el último intento (si falló)")
    created_at: datetime


class CorreoGenerado(BaseModel):
    """Lo que el LLM debe devolver: {"asunto": "...", "cuerpo": "..."}."""

    # extra="ignore": si el modelo agrega otra clave, se descarta; lo importante son estas dos.
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    asunto: str = Field(min_length=1, max_length=150)
    cuerpo: str = Field(min_length=1)

    @field_validator("cuerpo")
    @classmethod
    def validar_largo_cuerpo(cls, valor: str) -> str:
        palabras = len(valor.split())
        if palabras > MAX_PALABRAS_CUERPO:
            raise ValueError(f"el cuerpo tiene {palabras} palabras (máximo {MAX_PALABRAS_CUERPO})")
        return valor
