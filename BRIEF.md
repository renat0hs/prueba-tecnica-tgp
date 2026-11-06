# BRIEF: cómo construí TGP Outreach

## Lo importante
- El servicio funciona de punta a punta: en local con `docker compose up` (db, api y worker) y desplegado en https://tgp-outreach.onrender.com.
- Usé IA en dos roles:
  - **Claude en el chat** como apoyo para pensar.
  - **Claude Code** como agente que escribía el código y lo probaba.
- **El criterio y las decisiones fueron míos.** Revisé cada plan antes de aprobarlo, corregí lo que no me convencía, probé cada paso yo mismo y yo hice todos los commits, PRs y merges.
- La IA se equivocó varias veces, y algunos errores venían de mi propio plan armado con el chat. Los detecté al revisar o al probar; están más abajo.

## Cómo usé la IA

**Claude en el chat (apoyo):**
- Armar el plan por pasos (`notas/PLAN.md`).
- Explicarme conceptos que no dominaba.
- Revisar los planes del agente antes de aprobarlos.
- Mejorar mis prompts.

**Claude Code (agente):** trabajó con reglas que dejé en `CLAUDE.md`:
- antes de escribir código, decir qué archivos va a crear y por qué;
- cambios chicos;
- explicar cómo verificar cada cambio;
- no hacer commits;
- ninguna credencial en código, logs ni git;
- los tests nunca llaman al LLM real.

En el paso 3d le dije solo "dale con el 3d" y se saltó el plan. Desde ahí le pido siempre "muéstrame el plan y para ahí".

## Decisiones mías

Algunas fueron idea mía desde el principio (los reintentos, el 401, los 20 s, el correo y `create_all`). Otras salieron de revisar los planes con el chat, y las adopté porque entendí el porqué (probar en una copia, el `docker build` en el CI, no subir PRs de prueba y Render Postgres en la misma región).

| Decisión | Por qué |
|---|---|
| Reintentar hasta 3 veces, pero **no reintentar el 401** | Una falla pasajera puede arreglarse al tercer intento; una API key mala va a fallar igual |
| Bajar la espera entre intentos de 30 s a **20 s** | 30 s me pareció mucho |
| **El correo pregunta si la persona es la indicada**, en vez de pedir una reunión | Lo saqué de un video del cofundador y CEO de TGP: "estoy buscando al [cargo] de [empresa], ¿eres tú o hay otra persona con quien debería conversar?" |
| `create_all` al arrancar, en vez de un `init.sql` | El `init.sql` solo corre automático en Docker local; en CI y Render habría que ejecutarlo a mano |
| Probar en una copia (`docker compose -p tgp-prueba`) | Para no borrar mis leads con `down -v` |
| Agregar `docker build` al CI | Render usa ese Dockerfile y quería saber si se rompía antes del deploy |
| No subir ramas ni PRs de prueba a mi GitHub | La prueba del CI en rojo la hago en local |
| No subir el script que provocaba la carrera de `create_all` | Era solo para la prueba, no parte del servicio |
| Render Postgres, base y servicio en la misma región | Todo en un lugar; la URL interna solo funciona en la misma región |

Además revisé cada plan y probé cada paso yo mismo:
- `\d leads` en Postgres;
- los endpoints con PowerShell;
- llamadas reales a Groq;
- los tests en mi PC;
- una prueba completa a mano antes del deploy;
- la prueba en producción.

**Propuestas del agente que revisé y acepté:**
- Una sola transacción por lead con `FOR UPDATE SKIP LOCKED`, para que, si el worker se cae, el lead vuelva solo a `pendiente`.
- `clock_timestamp()` para `updated_at`. Con `now()`, la espera de 20 s ya estaría cumplida por el timeout del LLM.
- Advisory lock para la carrera de `create_all`.
- `pool_pre_ping`.
- 403 y 404 sin reintento.
- Correr el worker en un hilo dentro de la API en Render, porque el plan gratis no tiene background workers.

## Cuándo se equivocó la IA

| Error | Origen | Cómo lo detecté |
|---|---|---|
| Faltaba `notas/` en el `.gitignore` (y proponía `git add notas/`); faltaba `requirements.txt` | Ya venía en el plan del chat; el agente lo arrastró | Revisando el plan antes de aprobarlo |
| Modelo `llama-3.1-8b-instant` | Plan del chat; ya no existe en Groq | La primera llamada real dio 404. Listé los modelos de Groq y elegí `openai/gpt-oss-20b` |
| Comandos de prueba en bash, que no funcionan en PowerShell | Agente | Al leerlos; le pedí la versión PowerShell |
| Dijo que la tabla tendría 12 columnas | Agente | `\d leads` mostró 11 |
| "Crea la rama feature/worker", que yo ya había creado | Agente: supuso el estado del repo | Revisando el plan |
| Cambió la firma de `generar_correo` (sacó `dominio`) sin destacarlo | Agente | Mi prueba falló con `TypeError`. Acepté el cambio, pero le pedí explicarlo |
| El modelo copió literal una frase de ejemplo del prompt en los 3 correos | Prompt escrito por el agente | Probando con 3 cargos distintos; saqué los ejemplos copiables |
| Se saltó el plan en el paso 3d | Agente (y mi prompt, que no lo pedía) | Desde ahí siempre pido "muéstrame el plan y para ahí" |
| La prueba de mutantes se quedó pegada más de 7 minutos | Agente | La corté; queda pendiente |

El prompt del correo pasó por 4 versiones: rellenaba con suposiciones, copiaba el ejemplo, quedó demasiado seco y al final llegó a la estructura actual. Lección: la salida de un LLM hay que probarla varias veces y con datos distintos.

## Evidencia

| Prueba | Resultado |
|---|---|
| Tests (LLM falso, base `leads_test`) | 52 passed: API, worker, cliente LLM y URL de la base |
| CI en GitHub Actions (PR #1 y #2) | Verde: tests y docker build, ~35 s |
| Reintentos con timeout forzado | Exactamente 20 s entre intentos; al tercero, `error` con `timeout del LLM tras 0.01s (intento 3 de 3)` |
| API key inválida | `error` al primer intento: `API key de Groq inválida o sin permisos (401) (intento 1, no se reintenta)` |
| 2 workers, 3 leads | Cada lead procesado una sola vez (SKIP LOCKED) |
| Carrera de `create_all` | 20 de 20 rondas con un proceso caído sin el candado; 0 de 20 con el candado |
| Base caída con el worker andando | El worker sigue vivo y se recupera solo al volver la base |
| Datos inválidos | 422 y nada guardado (los ids siguieron sin saltos) |
| Producción (Render) | POST "Viña Concha y Toro": `pendiente` al tiro, `procesado` segundos después |

Correo generado en producción:
> Hola, ¿cómo estás? Estoy buscando al Gerente de Marketing de Viña Concha y Toro. ¿Eres tú quien ocupa ese puesto o hay alguien más con quien debería hablar? Gracias por tu ayuda.

---
*Este BRIEF y el README los redactó Claude Code a partir de mi bitácora (`notas/bitacora.md`, que no está en el repo). Yo los revisé y ajusté.*
