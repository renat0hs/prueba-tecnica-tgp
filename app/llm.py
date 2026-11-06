import json
import os

import openai
from pydantic import ValidationError

from app.schemas import CorreoGenerado

GROQ_BASE_URL = "https://api.groq.com/openai/v1"

# Objetivo del primer correo: no pedir reunión, sino preguntar si quien lee es la persona
# con ese cargo o quién lo es. El tono se describe sin frases de ejemplo, porque el modelo
# tiende a copiarlas literal. Al modelo no se le pasa el dominio: lo que no ve, no lo menciona.
# La validación acepta hasta 120 palabras (MAX_PALABRAS_CUERPO); el prompt pide muchas menos.
PROMPT_SISTEMA = """Eres un ejecutivo de desarrollo de negocios B2B que escribe el primer correo de contacto a una empresa.
No conoces el nombre del contacto: solo tienes el nombre de la empresa y el cargo que buscas.
No sabes nada más de la empresa: ni a qué se dedica, ni cómo funciona, ni qué problemas tiene.

Objetivo del correo: que quien lo lee responda si es la persona con ese cargo en esa empresa
o, si no lo es, con quién deberías conversar. Esa respuesta es lo único que pides.

El cuerpo tiene exactamente cuatro partes, en este orden:
1. Un saludo amable, sin nombre, que incluya una pregunta de cortesía sobre cómo está la persona.
2. Una frase que dice que estás buscando a quien ocupa ese cargo en esa empresa. Usa el cargo
   y el nombre de la empresa tal como te los entregan, con el artículo que corresponda al cargo.
3. Una pregunta que va después de esa frase: si la persona que lee es quien ocupa ese cargo,
   o si hay otra persona con quien deberías conversar.
4. Un cierre corto de agradecimiento.

Reglas:
- Tono cercano, cálido y natural, como un mensaje entre profesionales. Tutea al lector.
- Redacción bien escrita, con buena ortografía y puntuación. Varía la forma de decir cada parte.
- El cuerpo debe tener entre 20 y 35 palabras.
- No expliques por qué escribes ni te presentes a ti o a tu empresa.
- No menciones áreas, procesos, desafíos ni temas específicos del cargo.
- No pidas ninguna otra información, ni reunión, ni llamada, ni demo.
- No inventes nada sobre la empresa ni sobre la persona.
- No incluyas firma, nombre propio ni marcadores entre corchetes.
- El asunto debe ser breve y mencionar el cargo o la empresa.

Responde solo con un objeto JSON con exactamente estas dos claves:
{"asunto": "texto del asunto", "cuerpo": "texto del correo"}"""


class ErrorLLM(Exception):
    """Falla al generar un correo.

    motivo: texto legible que se guarda en lead.error_motivo.
    reintentable: True si la falla puede ser pasajera y vale la pena otro intento;
                  False si va a fallar igual (ej. API key inválida).
    """

    def __init__(self, motivo: str, reintentable: bool):
        super().__init__(motivo)
        self.motivo = motivo
        self.reintentable = reintentable


def construir_mensajes(nombre_empresa: str, cargo_contacto: str) -> list[dict]:
    datos_lead = (
        f"Empresa: {nombre_empresa}\n"
        f"Cargo que buscas: {cargo_contacto}"
    )
    return [
        {"role": "system", "content": PROMPT_SISTEMA},
        {"role": "user", "content": datos_lead},
    ]


def quitar_cercas_markdown(texto: str) -> str:
    """Si el modelo envolvió el JSON en ```json ... ```, deja solo el contenido."""
    texto = texto.strip()
    if texto.startswith("```"):
        _primera_linea, _, resto = texto.partition("\n")  # descarta "```json" (o "```")
        texto = resto.removesuffix("```")
    return texto.strip()


def interpretar_respuesta(texto: str | None) -> CorreoGenerado:
    """Convierte el texto del LLM en un CorreoGenerado válido, o lanza ErrorLLM."""
    if not texto or not texto.strip():
        raise ErrorLLM("el LLM devolvió una respuesta vacía", reintentable=True)

    texto = quitar_cercas_markdown(texto)

    try:
        datos = json.loads(texto)
    except json.JSONDecodeError:
        raise ErrorLLM("respuesta del LLM no es JSON válido", reintentable=True) from None

    try:
        return CorreoGenerado.model_validate(datos)
    except ValidationError as error:
        # Solo el primer problema, con el campo y el mensaje (sin copiar el texto del modelo).
        primero = error.errors()[0]
        campo = ".".join(str(parte) for parte in primero["loc"]) or "respuesta"
        raise ErrorLLM(
            f"respuesta del LLM no cumple el formato: {campo}: {primero['msg']}",
            reintentable=True,
        ) from None


def error_por_status(status: int) -> ErrorLLM:
    """Traduce un código HTTP de Groq a un ErrorLLM con motivo legible."""
    if status in (401, 403):
        return ErrorLLM(f"API key de Groq inválida o sin permisos ({status})", reintentable=False)
    if status == 404:
        return ErrorLLM("modelo del LLM no encontrado (404), revisa GROQ_MODEL", reintentable=False)
    if status == 429:
        return ErrorLLM("límite de uso del LLM alcanzado (429)", reintentable=True)
    # 5xx y otros 4xx (ej. 400 cuando el modelo no logra producir JSON válido): vale reintentar.
    return ErrorLLM(f"error HTTP {status} del LLM", reintentable=True)


class ClienteGroq:
    """Cliente real del LLM. Los tests usan uno falso con el mismo método generar_correo."""

    def __init__(self):
        # Se lee al crear el cliente, no al importar el módulo: así los tests no necesitan la llave.
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("falta la variable de entorno GROQ_API_KEY")

        self.modelo = os.environ.get("GROQ_MODEL", "openai/gpt-oss-20b")
        self.timeout = float(os.environ.get("LLM_TIMEOUT_SECONDS", "20"))
        self.cliente = openai.OpenAI(
            api_key=api_key,
            base_url=GROQ_BASE_URL,
            timeout=self.timeout,
            max_retries=0,  # los reintentos los maneja el worker con la columna intentos
        )

    def generar_correo(self, nombre_empresa: str, cargo_contacto: str) -> CorreoGenerado:
        try:
            respuesta = self.cliente.chat.completions.create(
                model=self.modelo,
                messages=construir_mensajes(nombre_empresa, cargo_contacto),
                response_format={"type": "json_object"},
                temperature=0.7,
            )
        # El orden importa: APITimeoutError hereda de APIConnectionError, así que va primero.
        except openai.APITimeoutError:
            raise ErrorLLM(f"timeout del LLM tras {self.timeout:g}s", reintentable=True) from None
        except openai.APIConnectionError:
            raise ErrorLLM("no se pudo conectar con el LLM", reintentable=True) from None
        except openai.APIStatusError as error:
            raise error_por_status(error.status_code) from None

        return interpretar_respuesta(respuesta.choices[0].message.content)
