import pytest
from fastapi.testclient import TestClient

from app import worker
from app.main import app
from app.models import Lead

LEAD_VALIDO = {
    "nombre_empresa": "Compañía Acme SpA",
    "dominio": "acme.cl",
    "cargo_contacto": "Gerente de Operaciones",
}


def test_post_crea_lead_pendiente_sin_esperar_al_llm(cliente_api, leer_lead):
    respuesta = cliente_api.post("/leads", json=LEAD_VALIDO)

    assert respuesta.status_code == 201
    cuerpo = respuesta.json()
    assert cuerpo["estado"] == "pendiente"
    # El correo todavía no existe: lo genera el worker después, la API no llama al LLM.
    assert cuerpo["correo_asunto"] is None
    assert cuerpo["correo_cuerpo"] is None
    assert cuerpo["nombre_empresa"] == "Compañía Acme SpA"

    guardado = leer_lead(cuerpo["id"])
    assert guardado.estado == "pendiente"
    assert guardado.intentos == 0


def test_post_normaliza_espacios_y_dominio(cliente_api):
    datos = {"nombre_empresa": "  Acme SpA  ", "dominio": " ACME.cl ", "cargo_contacto": " CTO "}

    cuerpo = cliente_api.post("/leads", json=datos).json()

    assert cuerpo["nombre_empresa"] == "Acme SpA"
    assert cuerpo["dominio"] == "acme.cl"
    assert cuerpo["cargo_contacto"] == "CTO"


@pytest.mark.parametrize(
    "cambio",
    [
        pytest.param({"cargo_contacto": None}, id="falta cargo_contacto"),
        pytest.param({"dominio": "https://acme.cl"}, id="dominio con https"),
        pytest.param({"dominio": "acme"}, id="dominio sin punto"),
        pytest.param({"cargo": "CTO"}, id="campo extra"),
        pytest.param({"nombre_empresa": "   "}, id="solo espacios"),
        pytest.param({"nombre_empresa": "x" * 201}, id="mas de 200 caracteres"),
    ],
)
def test_post_invalido_responde_422_y_no_guarda(cliente_api, db, cambio):
    datos = {**LEAD_VALIDO, **cambio}
    datos = {clave: valor for clave, valor in datos.items() if valor is not None}  # None = quitar campo

    respuesta = cliente_api.post("/leads", json=datos)

    assert respuesta.status_code == 422
    assert db.query(Lead).count() == 0


def test_get_lista_los_mas_nuevos_primero(cliente_api):
    cliente_api.post("/leads", json={**LEAD_VALIDO, "nombre_empresa": "Primera"})
    cliente_api.post("/leads", json={**LEAD_VALIDO, "nombre_empresa": "Segunda"})

    respuesta = cliente_api.get("/leads")

    assert respuesta.status_code == 200
    leads = respuesta.json()
    assert [lead["nombre_empresa"] for lead in leads] == ["Segunda", "Primera"]
    assert set(leads[0]) == {
        "id", "nombre_empresa", "dominio", "cargo_contacto", "estado",
        "correo_asunto", "correo_cuerpo", "error_motivo", "created_at",
    }


# --- RUN_WORKER_IN_API: el worker dentro de la API (Render free) ----------------------


@pytest.fixture
def llamadas_al_worker(monkeypatch):
    """Reemplaza iniciar_en_segundo_plano por una función que solo anota que la llamaron,
    para no levantar un hilo real que procese leads mientras corren los otros tests."""
    llamadas = []
    monkeypatch.setattr(worker, "iniciar_en_segundo_plano", lambda: llamadas.append("iniciado"))
    return llamadas


def test_api_no_arranca_el_worker_por_defecto(monkeypatch, llamadas_al_worker):
    monkeypatch.delenv("RUN_WORKER_IN_API", raising=False)

    with TestClient(app):
        pass

    assert llamadas_al_worker == []


def test_api_arranca_el_worker_si_se_pide(monkeypatch, llamadas_al_worker):
    monkeypatch.setenv("RUN_WORKER_IN_API", "true")

    with TestClient(app):
        pass

    assert llamadas_al_worker == ["iniciado"]


def test_api_no_arranca_si_el_worker_no_tiene_llave(monkeypatch):
    # Función real: sin GROQ_API_KEY (la borra conftest), ClienteGroq falla antes de crear el hilo.
    monkeypatch.setenv("RUN_WORKER_IN_API", "true")

    with pytest.raises(RuntimeError, match="falta la variable de entorno GROQ_API_KEY"):
        with TestClient(app):
            pass
