from app.llm import interpretar_respuesta


class LLMFalso:
    """Reemplaza a ClienteGroq en los tests. Tiene el mismo método generar_correo.

    Recibe una lista de respuestas y entrega una por llamada, en orden:
    - si es un texto, lo pasa por el interpretar_respuesta real (prueba la validación de verdad);
    - si es una excepción, la lanza (timeout, 401, un bug...).
    Guarda en self.llamadas con qué argumentos lo llamaron.
    """

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = []

    def generar_correo(self, nombre_empresa, cargo_contacto):
        self.llamadas.append((nombre_empresa, cargo_contacto))
        respuesta = self.respuestas.pop(0)
        if isinstance(respuesta, Exception):
            raise respuesta
        return interpretar_respuesta(respuesta)


# JSON válido como el que devolvería el LLM
CORREO_OK = (
    '{"asunto": "Gerente de Operaciones - Acme",'
    ' "cuerpo": "Hola, ¿cómo estás? Estoy buscando al Gerente de Operaciones."}'
)
