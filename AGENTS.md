# Flight Watcher — contexto del proyecto

Panel web + bot que vigila precios de vuelos (solo ida) en Vueling y Ryanair, guarda el histórico en SQLite, dibuja gráficas y avisa por Discord y/o Telegram con un enlace directo a cada fecha. Todo el código, comentarios, textos de UI y README están **en español**; mantenlo así.

## Stack

- Python 3.12, FastAPI + Jinja2 (server-side rendering), Chart.js en `app/static/charts.js`.
- SQLite (WAL) con SQL a mano, sin ORM. Sin migraciones: el esquema es `CREATE TABLE IF NOT EXISTS` en `app/db.py`.
- APIs JSON públicas vía `requests` (Vueling, Ryanair) y Playwright/Chromium headless solo para proveedores sin API (hoy ninguno registrado; `CalendarProvider` queda como base y lo cubren los tests). El navegador solo se abre si algún proveedor de la ronda lo necesita.
- APScheduler (`BackgroundScheduler`) dentro del mismo proceso. `requests` para notificar.
- Docker / docker-compose. **Un único worker de uvicorn**: el planificador vive en el proceso, más workers = comprobaciones duplicadas.

## Estructura

```
app/
  main.py        rutas FastAPI: panel, CRUD de vigilancias, detalle, API de gráficas, ajustes, ejecuciones, diagnóstico
  checker.py     ronda de comprobaciones (por vigilancia × proveedor) + reglas de aviso (deal_reason)
  scheduler.py   cron interno; horas/minuto/zona horaria salen de los ajustes en BD
  db.py          esquema, ajustes por defecto (DEFAULT_SETTINGS), consultas, seed_defaults()
  notify.py      Discord (webhook) y Telegram (bot)
  fmt.py         formateo de fechas/precios para plantillas y avisos
  config.py      DATA_DIR, DB_PATH, DEBUG_DIR
  providers/
    base.py      Provider (abstracto), ApiProvider (JSON sin navegador), CalendarProvider (Playwright), DayPrice, ProviderError
    extract.py   parseo de precios para CalendarProvider: respuestas JSON de red (recursivo) + celdas del DOM
    vueling.py, ryanair.py  ApiProvider
    __init__.py  registro PROVIDERS, METRO_AREAS (TCI → TFN, TFS), routes(), link_for()
  templates/, static/
tests/
  smoke_test.py         extremo a extremo con datos simulados, sin red
  browser_mock_test.py  Playwright real contra una web simulada
```

## Flujo principal

1. `scheduler` dispara `checker.run_checks()` (o el usuario pulsa «Comprobar»: `scheduler.run_now`). Un `threading.Lock` impide rondas simultáneas.
2. Por cada vigilancia activa y cada proveedor, `routes()` expande los códigos de ciudad (TCI → TFN y TFS) y por cada par de aeropuertos se llama a `provider.fetch_prices(page, origin, destination, max_months, debug_dir)` (`page=None` en ApiProvider), hasta 2 intentos. Se queda el mínimo por día; cada `DayPrice` lleva el aeropuerto real. Una ruta que falla solo es error si ninguna dio precios (Vueling no vuela a TFS, Ryanair no vuela a TFN).
3. Se filtra por `date_from`/`date_to`, se guarda el snapshot en `prices` y se evalúa `deal_reason`: `fixed` (precio ≤ `max_price`) o `relative` (≥ `discount_pct`% bajo la mediana histórica de esa ruta+web, solo si hay `min_samples`).
4. Los chollos nuevos (`already_alerted` evita repetir salvo que baje más) se envían con `notify.send_deals`. Solo se guardan en `alerts` si llegaron a algún canal; sin canales se reenvían cuando se configuren.
5. Se purga el histórico (`retention_days`) y los archivos de diagnóstico de más de 7 días.

## Modelo de datos (SQLite, `data/flight_watcher.db`)

- `settings(key, value)`: clave/valor. `db.get_settings()` mezcla `DEFAULT_SETTINGS` con lo guardado. También hay claves dinámicas `link_<provider>` (plantilla de enlace por proveedor).
- `watches`: id, name, origin, destination (IATA 3 letras), providers (CSV de claves), max_price, discount_pct, date_from, date_to, enabled.
- `prices`: watch_id, provider, flight_date, price, currency, checked_at, origin, destination (aeropuerto real; NULL en datos antiguos = el de la vigilancia). Un registro por día de vuelo por comprobación. Migración con `ALTER TABLE` en `db.init()`.
- `alerts`, `runs`: avisos enviados y ejecuciones (ok/error/n_prices/n_deals). Todo con `ON DELETE CASCADE` desde `watches`.

## Cómo ejecutar

```bash
cp .env.example .env && docker compose up -d --build   # panel en http://localhost:8000
python -m tests.smoke_test                             # sin red
python -m tests.browser_mock_test                      # necesita Chromium (FW_CHROMIUM=/ruta si usas el tuyo)
```

Variables de entorno: `PANEL_USER` / `PANEL_PASSWORD` (Basic Auth; vacías = sin auth), `DATA_DIR` (por defecto `./data`), `SEED_DEFAULTS` (`1` por defecto; `0` desactiva las vigilancias iniciales), `FW_CHROMIUM`, `TZ`.

## Convenciones

- Cabecera de módulo con docstring en español; `from __future__ import annotations`; type hints modernos (`dict | None`).
- Acceso a BD siempre con `with db.connect() as con:` (commit/rollback automáticos); las funciones de `db.py` reciben `con`.
- Los `except Exception` amplios llevan `# noqa: BLE001` y solo donde el fallo de un tercero (web, navegador) no debe tumbar la ronda.
- Añadir una aerolínea: nueva clase en `app/providers/<nombre>.py` (preferir `ApiProvider` con el endpoint JSON que usa la web; `CalendarProvider` solo si no hay otra vía) y añadirla al dict `PROVIDERS` de `providers/__init__.py`. Formularios, gráficas, avisos y plantilla de enlace en Ajustes la recogen solos.
- Los campos secretos (webhook, token) nunca se devuelven al navegador; el webhook de Discord se valida contra la URL oficial.
- Sin CSS/JS frameworks: plantillas Jinja + `style.css` + `charts.js`.

## Gotchas

- **Estado real de los providers (probado 2026-09-30 desde IP residencial, todo headless):**
  - **Vueling (SVQ↔TFN):** API `apiw.vueling.com/api/v1/availability?originCode=&destinationCode=` responde a `requests` con UA honesto; ~1 año en una petición; 404 = ruta no operada (p. ej. SVQ–TFS). Ronda real SVQ↔TCI: ~300 días por sentido.
  - **Ryanair (SVQ↔TFS, estacional):** API `ryanair.com/api/farfnd/v4/oneWayFares/{o}/{d}/cheapestPerDay?outboundMonthOfDate=` por mes. No entiende TCI (devuelve todo sin precio) → por eso la expansión es genérica en el checker.
  - **Iberia:** 403 del anti-bot a cualquier Chromium headless (headless-shell y `channel="chromium"`). Solo tiene rutas con escala. `CalendarProvider` detecta 403/429 en la portada y lanza `ProviderError` claro.
  - **Binter (SVQ↔TFN directo):** sin provider. Cloudflare bloquea www y `services.bintercanarias.com/main/graphql` (operación `booking_calendar`, que sí da precios por día tras «Buscar») a headless y a `requests`. Reutilizar cookies `cf_clearance` de una sesión headed **no funciona** (atadas a UA/huella) y el sondeo repetido acabó bloqueando la IP también en headed. No insistir contra Binter.
  - **Air Europa** (solo con escala TFN→MAD→SVQ): 403 en headless (página «Estamos actualizando la web»).
  - **Descartadas por el usuario (2026-09-30): Binter, Iberia (provider eliminado) y Air Europa.** Según Aena no hay más directas: SVQ↔TFN = Vueling + Binter; SVQ↔TFS = Ryanair. Wikipedia/agregadores listaban Air Europa TFN–SVQ directo: **falso** según Aena (TFN: solo BIO y MAD).
  - El smoke test registra un `MockWebProvider(CalendarProvider)` para cubrir la rama con navegador del checker.
- Decisión: **no se usan técnicas de sigilo/spoofing** (UA falso de navegador, stealth plugins, reutilizar cookies anti-bot) para saltar anti-bots. Las APIs se llaman con `USER_AGENT` honesto (`providers/base.py`).
- Vueling bloquea IPs de centros de datos: ejecutar desde IP residencial. Los CAPTCHA no se resuelven (la ronda falla y se avisa).
- Para depurar una web: Ajustes → activar diagnóstico, «Comprobar ahora», revisar capturas/HTML/JSON en `/debug`, ajustar `sel_*` y `url_hints` del proveedor.
- `requirements.txt` no incluye lo que necesita `tests.smoke_test` (`TestClient` pide `httpx`/`httpx2`); instálalo aparte para correr los tests.
- Plantillas de enlace editables en Ajustes (`link_<provider>`) con `{origin} {destination} {date} {date_dmy} {year} {month} {day}`.
- `seed_defaults()` (SVQ↔TCI con vueling,ryanair) solo actúa si la tabla `watches` está vacía; el smoke test depende de esas vigilancias iniciales y simula que Vueling solo opera TFN y Ryanair solo TFS.
- La regla «habitual» usa la mediana de la ruta+web, no la de la misma fecha de vuelo.
- Solo ida por vigilancia; para ida y vuelta se crean dos vigilancias.
- Webhook y token se guardan en texto plano en la BD: no exponer el panel sin autenticación.
