import pytest

from app.db import normalizar_url


@pytest.mark.parametrize(
    "url, esperada",
    [
        pytest.param(
            "postgresql://u:clave@host:5432/leads",
            "postgresql+psycopg://u:clave@host:5432/leads",
            id="formato de Render",
        ),
        pytest.param(
            "postgres://u:clave@host:5432/leads",
            "postgresql+psycopg://u:clave@host:5432/leads",
            id="formato antiguo postgres://",
        ),
        pytest.param(
            "postgresql+psycopg://u:clave@db:5432/leads",
            "postgresql+psycopg://u:clave@db:5432/leads",
            id="ya trae el driver (como el .env local)",
        ),
        pytest.param(
            "postgresql://u:clave@host/leads?sslmode=require",
            "postgresql+psycopg://u:clave@host/leads?sslmode=require",
            id="conserva parametros como sslmode",
        ),
    ],
)
def test_normalizar_url(url, esperada):
    assert normalizar_url(url) == esperada
