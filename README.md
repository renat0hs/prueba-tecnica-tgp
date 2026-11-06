# TGP Outreach

Microservicio que genera con un LLM un primer correo de outreach B2B para cada lead y guarda el resultado en PostgreSQL.

Recibe la empresa, su dominio y el cargo que se busca. Devuelve un correo corto que no pide reunión, sino que pregunta si quien lo lee es la persona indicada. Ejemplo real generado en producción:

> **Asunto:** Gerente de Marketing - Viña Concha y Toro
>
> Hola, ¿cómo estás? Estoy buscando al Gerente de Marketing de Viña Concha y Toro. ¿Eres tú quien ocupa ese puesto o hay alguien más con quien debería hablar? Gracias por tu ayuda.

Cómo lo construí y cómo usé IA: [BRIEF.md](BRIEF.md).

## Pruébalo en 1 minuto

**URL:** https://tgp-outreach.onrender.com (redirige a la documentación interactiva, `/docs`).

> **Ojo: el servicio está en el plan gratis de Render.**
> - Se duerme tras 15 minutos sin tráfico. El primer request lo despierta y puede tardar alrededor de 1 minuto.
> - El worker se duerme con él, porque corre como un hilo dentro de la misma API. Mientras duerme no procesa nada. Los leads que queden `pendiente` se procesan solos cuando un request lo despierta.
> - La base gratis de Render vence 30 días después de creada, alrededor del 7 de diciembre de 2026.

**Desde el navegador:**
1. Abre la URL y espera a que cargue `/docs`.
2. En `POST /leads` aprieta **Try it out**. El ejemplo ya viene escrito; cámbialo si quieres y aprieta **Execute**. Responde `201` con `"estado": "pendiente"`.
3. Espera unos segundos y ejecuta `GET /leads`. El lead aparece `procesado`, con `correo_asunto` y `correo_cuerpo`.

**Con curl (bash):**
```bash
curl -X POST https://tgp-outreach.onrender.com/leads \
  -H "Content-Type: application/json" \
  -d '{"nombre_empresa":"Compañía Acme SpA","dominio":"acme.cl","cargo_contacto":"Gerente de Operaciones"}'

sleep 10
curl https://tgp-outreach.onrender.com/leads
```

**Con PowerShell:**
```powershell
$base = "https://tgp-outreach.onrender.com"
$lead = @{ nombre_empresa = "Compañía Acme SpA"; dominio = "acme.cl"; cargo_contacto = "Gerente de Operaciones" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri "$base/leads" -ContentType "application/json; charset=utf-8" -Body ([System.Text.Encoding]::UTF8.GetBytes($lead))

Start-Sleep -Seconds 10
Invoke-RestMethod -Uri "$base/leads" | ForEach-Object { $_ } | Format-List id, estado, correo_asunto, correo_cuerpo, error_motivo
```

Si mandas datos inválidos (falta un campo, `"dominio": "https://acme.cl"`, un campo de más), la API responde `422` y no guarda nada.

## Cómo funciona

```
              POST /leads                       SELECT ... FOR UPDATE SKIP LOCKED
 cliente ───────────────────► API (FastAPI) ───► PostgreSQL ◄────────────── worker ───► Groq (LLM)
         ◄─── 201 pendiente                      tabla leads    guarda procesado / error
              GET /leads
```

1. `POST /leads` valida los datos con Pydantic, guarda el lead como `pendiente` y responde de inmediato. La API nunca llama al LLM.
2. El worker revisa la tabla cada 5 segundos. Toma un lead `pendiente`, le pide el correo a Groq, valida la respuesta y deja el lead en `procesado` o `error`.
3. `GET /leads` lista los leads, del más nuevo al más antiguo, con su estado, el correo y el motivo si falló.

**Dónde corre el worker:**

| | Local (docker compose) | Render (plan gratis) |
|---|---|---|
| API | servicio `api` | web service |
| Worker | servicio aparte, `worker` (`python -m app.worker`) | hilo dentro de la API (`RUN_WORKER_IN_API=true`), porque el plan gratis no tiene background workers |
| Base | servicio `db` (Postgres 16) | Render Postgres 16, misma región (virginia) |

### Estados de un lead

```
pendiente ──► procesado
    │
    └──► error   (con error_motivo)
```

- **Falla pasajera** (timeout, JSON inválido, 429, error 5xx): el lead sigue `pendiente` y se reintenta tras 20 s. Son hasta 3 intentos en total; al tercero queda en `error`.
- **Falla que no se arregla sola** (401/403 API key inválida, 404 modelo inexistente): queda en `error` al primer intento.
- `error_motivo` dice qué pasó en palabras simples, por ejemplo `timeout del LLM tras 20s (intento 3 de 3)`.

## Correrlo en local

Requisitos: Docker Desktop y una API key gratis de [Groq](https://console.groq.com/keys).

```powershell
Copy-Item .env.example .env     # completa GROQ_API_KEY (y cambia la contraseña de Postgres)
docker compose up --build       # levanta db, api y worker
```

La API queda en http://localhost:8000. Abre http://localhost:8000/docs o usa los comandos de arriba con `$base = "http://localhost:8000"`.

**Tests** (usan un LLM falso y una base aparte `leads_test`; nunca tocan la base real ni llaman a Groq):
```powershell
docker compose up -d db
docker compose exec db sh -c 'createdb -U "$POSTGRES_USER" leads_test'   # solo la primera vez
docker compose run --rm -v "${PWD}/tests:/code/tests" api python -m pytest -v
```

El CI (GitHub Actions) corre los mismos tests con un Postgres 16 propio y además construye la imagen de Docker, en cada PR y en cada push a `main`. Render solo despliega `main` si el CI quedó en verde (`autoDeployTrigger: checksPass`).

### Variables de entorno

Están todas en [`.env.example`](.env.example). Ninguna credencial va en el código ni en git.

| Variable | Para qué |
|---|---|
| `DATABASE_URL` | Conexión a Postgres. Acepta también `postgresql://`, el formato de Render |
| `GROQ_API_KEY` | Llave de Groq. Sin ella, el worker no arranca (y en Render, tampoco la API) |
| `GROQ_MODEL` | Modelo (por defecto `openai/gpt-oss-20b`) |
| `LLM_TIMEOUT_SECONDS` | Tiempo máximo por llamada al LLM (20) |
| `WORKER_POLL_SECONDS` | Cada cuánto busca leads el worker cuando no hay trabajo (5) |
| `RUN_WORKER_IN_API` | `true` solo en Render: el worker corre dentro de la API |

## Estructura

```
app/
  main.py      API: POST y GET /leads, / redirige a /docs
  schemas.py   validación de entrada, salida y de la respuesta del LLM
  models.py    tabla leads (con CHECK de estados e índice por estado)
  db.py        conexión y creación de la tabla
  llm.py       cliente de Groq: prompt, timeout y errores con motivo legible
  worker.py    loop que procesa los leads pendientes
tests/         52 tests con un LLM falso
render.yaml    despliegue en Render (Blueprint)
```

## Decisiones de diseño

- **Worker con polling sobre Postgres, no `BackgroundTasks` ni Redis.**
  - El estado vive en la tabla, así que si el proceso se reinicia no se pierde trabajo.
  - No hace falta otra pieza de infraestructura.
  - `SELECT ... FOR UPDATE SKIP LOCKED` hace que dos workers nunca tomen el mismo lead. Lo probé con 2 workers: cada lead se procesó una sola vez.
- **Una transacción por lead.** Tomar, llamar al LLM y guardar ocurren en la misma transacción.
  - Si el worker muere a mitad de camino, Postgres deshace todo y el lead vuelve solo a `pendiente`. Por eso no hay un estado "procesando" que pueda quedar pegado.
  - El costo es que la fila queda bloqueada hasta 20 s, el máximo del timeout.
- **Los reintentos los decide el worker, no el SDK.** El cliente usa `max_retries=0` y solo marca si el error es reintentable. El worker cuenta los intentos en la columna `intentos`.
- **La respuesta del LLM no se cree a ciegas.**
  - Se pide JSON `{"asunto", "cuerpo"}` y se valida con Pydantic: campos obligatorios, largo del asunto y máximo 120 palabras en el cuerpo.
  - Si viene envuelta en ```` ```json ````, se limpia antes de validar.
- **El prompt no recibe el dominio.** El modelo no puede mencionar lo que no ve. El dominio igual se valida y se guarda.
- **Groq con `openai/gpt-oss-20b`.**
  - Groq es gratis, rápido y compatible con el SDK de OpenAI.
  - El modelo del plan original, `llama-3.1-8b-instant`, ya no existe: la primera llamada respondió 404 y el manejo de errores lo marcó como no reintentable, como se esperaba.
- **`create_all` al arrancar, con un advisory lock de Postgres.** La API y el worker arrancan juntos. Sin el candado, ambos intentaban crear la tabla y uno se caía: lo reproduje en 20 de 20 rondas.
- **`pool_pre_ping`.** Después de reiniciar la base, el primer request daba 500 por conexiones muertas en el pool. Con pre-ping, SQLAlchemy las detecta y reconecta.
- **Las respuestas declaran `charset=utf-8`.** PowerShell 5.1 mostraba "ViÃ±a" porque asumía otra codificación.

## Qué mejoraría con más tiempo

- **Backoff exponencial** en vez de 20 s fijos entre intentos.
- **Migraciones con Alembic.** `create_all` crea la tabla, pero no la modifica si cambia el modelo.
- **Paginación y filtro por estado en `GET /leads`.** Hoy devuelve todos los leads.
- **Worker como servicio aparte también en producción**, con un plan pagado, para que no se duerma con la API. Y una base que no venza.
- **Que el worker espere a la base al arrancar.** Hoy, si la base no está, el worker se cae y Docker lo reinicia (`restart: unless-stopped`). Después de arrancado, sí aguanta caídas de la base sin reiniciarse.
- **Logs más tranquilos cuando la base está caída.** Hoy imprime el traceback completo cada 5 s.
- **Rate limiting y autenticación** si se expone a terceros (fuera del alcance de esta prueba).
- **Métricas del worker**, como leads por estado y tiempo por lead, y logs estructurados.
- **Prompts según el tipo de cargo**, y medir cuál genera más respuestas.
- **Probar los tests rompiendo el código a propósito** (mutation testing). Lo intenté y lo dejé pendiente.
