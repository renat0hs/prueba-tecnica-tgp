import httpx2  # el SDK de openai lo usa para construir sus excepciones
import openai
import pytest

from app.llm import ClienteGroq, ErrorLLM, error_por_status, interpretar_respuesta


@pytest.mark.parametrize(
    "texto",
    [
        pytest.param('{"asunto": "Hola", "cuerpo": "Un correo corto."}', id="JSON valido"),
        pytest.param('```json\n{"asunto": "Hola", "cuerpo": "Un correo corto."}\n```', id="con cercas markdown"),
        pytest.param('{"asunto": "Hola", "cuerpo": "Un correo corto.", "firma": "x"}', id="clave extra"),
    ],
)
def test_interpretar_respuesta_valida(texto):
    correo = interpretar_respuesta(texto)
    assert correo.asunto == "Hola"
    assert correo.cuerpo == "Un correo corto."


@pytest.mark.parametrize(
    "texto, motivo",
    [
        pytest.param("   ", "el LLM devolvió una respuesta vacía", id="vacia"),
        pytest.param(None, "el LLM devolvió una respuesta vacía", id="None"),
        pytest.param("Claro, aquí va: Hola...", "respuesta del LLM no es JSON válido", id="texto plano"),
        pytest.param('{"asunto": "Hola"}', "respuesta del LLM no cumple el formato: cuerpo: Field required", id="falta cuerpo"),
        pytest.param(
            '{"asunto": "Hola", "cuerpo": "' + "palabra " * 121 + '"}',
            "respuesta del LLM no cumple el formato: cuerpo: Value error, el cuerpo tiene 121 palabras (máximo 120)",
            id="cuerpo de 121 palabras",
        ),
    ],
)
def test_interpretar_respuesta_invalida(texto, motivo):
    with pytest.raises(ErrorLLM) as error:
        interpretar_respuesta(texto)
    assert error.value.motivo == motivo
    assert error.value.reintentable is True


@pytest.mark.parametrize(
    "status, reintentable",
    [(401, False), (403, False), (404, False), (400, True), (429, True), (500, True), (503, True)],
)
def test_error_por_status(status, reintentable):
    assert error_por_status(status).reintentable is reintentable


# --- ClienteGroq: traducción de las excepciones del SDK, sin red ----------------------

PETICION = httpx2.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


def respuesta_http(status):
    return httpx2.Response(status, request=PETICION)


class CompletionsQueFalla:
    """Imita cliente.chat.completions del SDK: create() lanza la excepción indicada."""

    def __init__(self, excepcion):
        self.excepcion = excepcion

    def create(self, **kwargs):
        raise self.excepcion


@pytest.fixture
def cliente_groq(monkeypatch):
    # Llave falsa: el cliente se crea, pero nunca hace una petición (create está reemplazado).
    monkeypatch.setenv("GROQ_API_KEY", "llave-falsa-de-test")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "20")
    return ClienteGroq()


@pytest.mark.parametrize(
    "excepcion, motivo, reintentable",
    [
        # APITimeoutError hereda de APIConnectionError: este caso protege el orden de los except.
        pytest.param(openai.APITimeoutError(request=PETICION), "timeout del LLM tras 20s", True, id="timeout"),
        pytest.param(openai.APIConnectionError(request=PETICION), "no se pudo conectar con el LLM", True, id="sin conexion"),
        pytest.param(
            openai.AuthenticationError("no", response=respuesta_http(401), body=None),
            "API key de Groq inválida o sin permisos (401)", False, id="401",
        ),
        pytest.param(
            openai.RateLimitError("no", response=respuesta_http(429), body=None),
            "límite de uso del LLM alcanzado (429)", True, id="429",
        ),
    ],
)
def test_cliente_groq_traduce_errores_del_sdk(cliente_groq, monkeypatch, excepcion, motivo, reintentable):
    monkeypatch.setattr(cliente_groq.cliente.chat, "completions", CompletionsQueFalla(excepcion))

    with pytest.raises(ErrorLLM) as error:
        cliente_groq.generar_correo("Acme SpA", "CTO")

    assert error.value.motivo == motivo
    assert error.value.reintentable is reintentable


def test_cliente_groq_sin_llave_falla_claro():
    # El fixture sin_llave_groq (conftest) ya borró GROQ_API_KEY.
    with pytest.raises(RuntimeError, match="falta la variable de entorno GROQ_API_KEY"):
        ClienteGroq()
