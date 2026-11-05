# Contexto del proyecto (para Claude Code)

Microservicio para la prueba técnica de TGP: genera un primer correo de outreach B2B personalizado para un lead usando un LLM y guarda el resultado en PostgreSQL.

## Alcance (no agregar nada más)
- POST /leads: valida {nombre_empresa, dominio, cargo_contacto}, guarda en Postgres con estado `pendiente` y responde de inmediato, sin esperar al LLM.
- GET /leads: lista leads con estado, correo generado (si existe) y fecha de creación.
- Worker en segundo plano: toma leads `pendiente`, genera el correo y deja el lead en `procesado` o en `error` con el motivo.
- Sin frontend, sin autenticación, sin enriquecimiento externo.

## Stack
- Python 3.12, FastAPI, Pydantic, SQLAlchemy, PostgreSQL 16, pytest.
- LLM: Groq (API compatible con OpenAI), modelo `llama-3.1-8b-instant`.
- Docker compose para local (api + worker + db). Despliegue en Render.

## Reglas
- Ninguna credencial en el código, en logs ni en git. Todo por variables de entorno; mantener `.env.example` actualizado.
- Toda llamada al LLM con timeout. La respuesta del LLM debe ser JSON {"asunto","cuerpo"} validado con Pydantic. Cualquier falla deja el lead en `error` con un motivo legible.
- El worker toma leads con `SELECT ... FOR UPDATE SKIP LOCKED` para no procesar dos veces el mismo lead.
- Los tests nunca llaman al LLM real: usan un cliente falso inyectado.
- Cambios chicos: después de cada cambio, explícame qué hiciste y cómo lo verifico, y espera a que yo haga el commit.
- Código simple y legible: prefiero entender cada línea antes que algo "elegante".
