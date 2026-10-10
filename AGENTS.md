# Flight Watcher — contexto del proyecto

Panel web + bot multiusuario que vigila precios de vuelos (solo ida, y viajes de ida y vuelta que juntan dos vigilancias) en Vueling, Ryanair, Wizz Air y Google Flights, guarda el histórico en SQLite/PostgreSQL/MySQL/MariaDB, dibuja gráficas y avisa por Discord y/o Telegram (lista de canales por usuario, asignables a cada vigilancia) con un enlace directo a cada fecha. Todo el código, comentarios, textos de UI y README están **en castellano de España** (tuteo, nunca voseo ni expresiones rioplatenses); mantenlo así, también al hablar con el usuario.

## Stack

- Python 3.12, FastAPI como **API JSON** (`/api/v1`, paquete `app/api/`) que además sirve el panel ya compilado (`app/web`).
- Panel: **React 19 + Vite + TypeScript** en `frontend/` (React Router, TanStack Query, Tailwind CSS v4, primitivas accesibles de Radix, Motion para animaciones, Recharts para gráficas, sonner para avisos emergentes). `npm run build` escribe en `../app/web`; la imagen Docker lo compila en una etapa de Node.
- SQLAlchemy **Core** (no ORM) en `app/db.py`: tablas declaradas con `Table` (fuente de verdad del esquema). Motor por `DB_ENGINE` (`sqlite` por defecto con WAL, `postgres` → psycopg, `mysql`/`mariadb` → pymysql).
- Migraciones con **Alembic** en `app/migrations/` (dentro de `app/` porque el Dockerfile solo copia esa carpeta). `db.init()` ejecuta `upgrade head` al arrancar; no hay `create_all`.
- APIs JSON públicas vía `requests` (Vueling, Ryanair, Wizz Air, Google Flights) y Playwright/Chromium headless solo para proveedores sin API (hoy ninguno registrado; `CalendarProvider` queda como base y lo cubren los tests). El navegador solo se abre si algún proveedor de la ronda lo necesita.
- APScheduler (`BackgroundScheduler`) dentro del mismo proceso. `requests` para notificar.
- Docker / docker-compose. **Un único worker de uvicorn**: el planificador vive en el proceso, más workers = comprobaciones duplicadas.

## Estructura

```
app/
  __init__.py    `__version__`: única fuente de la versión (pie del panel, User-Agent, imagen Docker, CI)
  main.py        app FastAPI: middleware CSRF y de sesión, manejadores de error (JSON en castellano), /avatars, estáticos con huella (/assets) y el panel (cualquier otra ruta → index.html)
  api/           API JSON /api/v1: deps.py (sesión, permisos, Invalid, vistas saneadas), session.py (entrar/salir, /me, /meta, /status, /run), watches.py (CRUD, detalle, gráficas, avisos, ejecuciones, /places, /route-check; parse_number/parse_dates compartidos), trips.py (viajes: CRUD, combinaciones actuales, /options por fecha de ida, /run), account.py (perfil, avatar, contraseña, canales propios y de admin), admin.py (usuarios, ajustes, /providers + /providers/health + /providers/revalidate, diagnóstico)
  auth.py        hash scrypt de contraseñas, validación de usuario/clave, LoginThrottle (en memoria)
  avatars.py     guardado de avatares en DATA_DIR/avatars (tipo por magic bytes, 2 MB, sin SVG)
  checker.py     ronda de comprobaciones (por vigilancia × proveedor activo × par de aeropuertos) + reglas de aviso (deal_reason); browser_page(); al final evalúa los viajes
  trips.py       viajes de ida y vuelta: legs_by_day() (mínimo por día de cada tramo), combinations(), best_per_day(), deal_reason() y evaluate() (histórico + avisos, top TOP_DEALS)
  coverage.py    cobertura de rutas: check() (caché provider_routes), check_many() (en paralelo con tiempo límite), coverage_for() (al guardar), revalidate() (semanal, avisa de aperturas/cierres)
  health.py      prueba de acceso a proveedores (zona «Proveedores»): pasos cobertura + precios, estado ok/empty/blocked/error/timeout/skipped, BCE y aerolíneas en estudio
  places.py      catálogo de lugares: aeropuertos (app/data/airports.csv, OurAirports), CITIES, GROUPS, países (app/data/countries.csv); search(), routes(), MAX_PAIRS
  fx.py          cambio a euros con los tipos diarios del BCE (caché en DATA_DIR/ecb_rates.json)
  data/          airports.csv y countries.csv (generados con scripts/build_places.py; versionados)
  scheduler.py   cron interno; horas/minuto/zona horaria salen de los ajustes en BD; revalidación de cobertura los lunes 05:10
  db.py          esquema (SQLAlchemy Core), motor/conexión, init() → Alembic, ajustes por defecto (DEFAULT_SETTINGS), consultas, bootstrap_admin(), seed_defaults()
  migrations/    Alembic: env.py (usa db.engine/db.metadata), versions/0001_esquema_inicial.py, 0002_usuarios.py, 0003_canales.py, 0004_proveedores.py, 0005_viajes.py
  notify.py      tipos de canal en `KINDS` (campos, validación, envío; hoy Discord y Telegram) y `send*(channels, …)`: añadir un tipo = una entrada ahí
  fmt.py         formateo de fechas/precios/monedas/escalas/noches para los avisos (el panel tiene el mismo criterio en frontend/src/lib/format.ts)
  config.py      DATA_DIR, DEBUG_DIR, WEB_DIR (panel compilado), DB_ENGINE, DB_PATH (SQLite), DB_HOST/PORT/NAME/USER/PASSWORD
  providers/
    base.py      Provider (abstracto: coverage, network/probe, slot() = turno por proveedor), ApiProvider (request/get_json/post_json), CalendarProvider (Playwright), DayPrice (moneda, escalas, price_eur), ProviderError, ProviderBlocked
    extract.py   parseo de precios para CalendarProvider: respuestas JSON de red (recursivo) + celdas del DOM
    vueling.py (probe), ryanair.py (network), wizzair.py (network), google.py (universal)  ApiProvider
    candidates.py  aerolíneas en estudio (Volotea, easyJet, Iberia): solo se prueba su portada; huellas de anti-bot
    __init__.py  registro PROVIDERS (su orden es el de todo el panel), ordered(), routes() (= places.routes), link_for()
  web/           build del panel (generado, no versionado)
frontend/
  src/api/       client.ts (fetch + cabecera CSRF + 401 → login), queries.ts (TanStack Query y claves), types.ts (respuestas de la API)
  src/components/ ui/ (botón, campos, tarjetas, diálogos y menús Radix…), layout/AppShell.tsx (cabecera, menú móvil, banner de ronda, pie), watch/ (tarjetas de web, calendario, gráficas, tablas), trip/parts.tsx (piezas de los viajes), account/ (avatar, canales)
  src/components/watch/PlaceCombobox.tsx  autocompletado de lugares (patrón ARIA combobox + listbox)
  src/pages/     una por pantalla (ProvidersPage = prueba de acceso, solo admin); src/routes/router.tsx (rutas, carga diferida de detalle y administración) y guards.tsx (RequireAuth/RequireAdmin)
  src/lib/       format.ts, calendar.ts (+ tests Vitest), theme.ts, hooks.ts (useTitle, useRunNow)
  e2e/           Playwright + axe contra la app real (tests/e2e_server.py)
scripts/
  build_places.py       regenera app/data desde el CSV de OurAirports (necesita pycountry, solo para el script)
tests/
  smoke_test.py         extremo a extremo con datos simulados, sin red (incluye la API, cobertura, escalas, monedas, revalidación, turnos, prueba de acceso y cómo se sirve el panel)
  migration_test.py     BD en 0003 con datos → head (sin perder filas, CSV → watch_providers; un viaje) → 0004 → 0003 → head
  fakes.py              dobles compartidos: navegador, proveedores con precios y cobertura simulados (OPERATES, BLOCKED), cambio BCE, portadas y envío de avisos
  e2e_server.py         app real con BD temporal y datos simulados (y un viaje con las vigilancias iniciales) para las pruebas del panel
  browser_mock_test.py  Playwright real contra una web simulada
```

## Flujo principal

1. `scheduler` dispara `checker.run_checks()` para **todos** los usuarios (o el usuario pulsa «Comprobar»: `scheduler.run_now(watch_id, user_id)`, solo lo suyo). Un `threading.Lock` impide rondas simultáneas. Las vigilancias de usuarios desactivados se saltan.
2. Por cada vigilancia activa y cada proveedor **activo** en `watch_providers` (uno inactivo = ruta cerrada, ni se consulta), por cada par de aeropuertos de su cobertura se llama a `provider.fetch_prices(page, origin, destination, max_months, debug_dir)` (`page=None` en ApiProvider; `max_stops=` solo si `stops_filter`), hasta 2 intentos (ninguno más si `ProviderBlocked`). Cada `DayPrice` se pasa a euros (`fx.to_eur` → `price_eur`), se descarta si supera `max_stops` (escalas `None` = el proveedor ya filtró) y se queda el mínimo en euros por día con su aeropuerto real. Un par que falla solo es error si ninguno dio precios.
3. Se filtra por `date_from`/`date_to`, se guarda el snapshot en `prices` (`price` en euros, `currency`+`orig_price` originales, `stops`) y se evalúa `deal_reason` (en euros): `fixed` (precio ≤ `max_price`) o `relative` (≥ `discount_pct`% bajo la mediana histórica de esa ruta+web, solo si hay `min_samples`).
4. Los chollos nuevos (`already_alerted` evita repetir salvo que baje más) se envían con `notify.send_deals` **solo a los canales asignados a esa vigilancia** (`watch_channels`) que siguen activos; sin canales no se envía ni se marca como avisado (se reenviará al asignar uno). Los fallos de la ronda (`notify_errors`) van a **todos** los canales activos de cada dueño, solo los de sus vigilancias. Solo se guardan en `alerts` si llegaron a algún canal; sin canales se reenvían cuando se configuren.
5. **Viajes** (`trips.py`): los activos con algún tramo comprobado en la ronda (o el pedido con «Comprobar», que comprueba sus dos tramos aunque estén en pausa). No consultan ninguna web: con la última comprobación de cada tramo (más reciente que `STALE_DAYS`=3 días, solo proveedores activos) toman el mínimo por día; total = ida(d) + vuelta(d+n) para cada `n` entre `min_nights` y `max_nights` (1–60) y cada `d` en la ventana de ida. Se guarda la mejor combinación de cada fecha de ida en `trip_quotes`, se aplica `trips.deal_reason` (fijo: total ≤ `max_total`; relativo: bajo la mediana de `trip_quotes`) y se avisa con `notify.send_trip_deals` de las `TOP_DEALS`=5 fechas de ida más baratas que cumplen, una vez por fecha de ida (`trip_already_alerted`, salvo que baje), a los canales del viaje (`trip_channels`). Los errores de envío se suman a los del dueño.
6. Se purga el histórico (`retention_days`, también `trip_quotes`/`trip_alerts`) y los archivos de diagnóstico de más de 7 días.

**Cobertura** (`coverage.py`): al crear/editar, el panel llama a `POST /route-check` (expande origen y destino con `places.routes`, como mucho `MAX_PAIRS`=60, y consulta los proveedores en paralelo con `CHECK_TIMEOUT` por proveedor; el que no acaba sale como `timeout` pero sigue en segundo plano y deja su respuesta en caché). Al guardar, `coverage_for` lee esa caché (`CACHE_DAYS`=3): un proveedor que seguro no opera la ruta es un error 422 salvo que la vigilancia ya lo tuviera (se guarda inactivo: ruta de temporada); uno que no se pudo comprobar se guarda con todos los pares y `checked_at=NULL`. Los lunes `revalidate()` repasa todo sin caché (también la de red en memoria) y avisa a los canales de la vigilancia de los pares que se abren o se cierran (no en la primera comprobación, `checked_at=NULL`).

## Modelo de datos (`data/flight_watcher.db` con SQLite, o la BD de `DB_NAME`)

- `settings(key, value)`: clave/valor **globales** (solo admin). `db.get_settings()` mezcla `DEFAULT_SETTINGS` con lo guardado. También hay claves dinámicas `link_<provider>` (plantilla de enlace por proveedor).
- `users`: id, username (único, minúsculas), display_name, password_hash (`scrypt$n$r$p$salt$hash`), role (`admin`|`user`), enabled, avatar (nombre de archivo o NULL), notify_errors, created_at. `watches.user_id` → `users` con `ON DELETE CASCADE` (borrar un usuario se lleva sus vigilancias, canales, precios, avisos y ejecuciones).
- `channels`: id, user_id, kind (`discord`|`telegram`, ver `notify.KINDS`), name, config (JSON con los campos del tipo, **con secretos**), enabled. `watch_channels(watch_id, channel_id)`: qué canales avisan por cada vigilancia (ambos con CASCADE). `db.list_watches/get_watch` añaden `channel_ids`.
- `watches`: id, user_id, name, origin, destination (código de lugar, hasta 40: aeropuerto/ciudad IATA en mayúsculas, país ISO de 2 letras, grupo en minúsculas), max_price, discount_pct, date_from, date_to, max_stops (0 = solo directos, NULL = sin límite), enabled. `db.list_watches/get_watch` añaden `providers` (claves) y `coverage` ({clave: {routes: [(o, d)], active, checked_at}}); `create_watch/update_watch` aceptan `data["coverage"]` o, si falta, `data["providers"]` (todos los pares, sin comprobar).
- `watch_providers(watch_id, provider)`: routes (JSON ["SVQ-TFN", …]), active, checked_at (NULL = nunca comprobado). Sustituye al antiguo CSV `watches.providers` (migración 0004).
- `provider_routes(provider, origin, destination)`: operated, checked_at — caché de cobertura por par de aeropuertos.
- `provider_health(provider)`: status, detail (JSON con los pasos), latency_ms, checked_at — último resultado de la prueba de acceso.
- `prices`: watch_id, provider, flight_date, price (**en euros**), currency (moneda **original**), orig_price (en la moneda original; NULL = era en euros), stops (NULL en datos antiguos), checked_at, origin, destination (aeropuerto real; NULL en datos antiguos = el de la vigilancia). Un registro por día de vuelo por comprobación.
- `alerts`, `runs`: avisos enviados y ejecuciones (ok/error/n_prices/n_deals). Todo con `ON DELETE CASCADE` desde `watches`.
- `trips`: id, user_id, name, outbound_id y return_id (→ `watches`, **CASCADE**: borrar una vigilancia borra sus viajes), min_nights, max_nights, date_from/date_to (ventana de ida), max_total, discount_pct, enabled. Los tramos deben ser vigilancias del mismo dueño y distintas; que no encajen (ida a TFN, vuelta desde TFS) o que estén en pausa solo genera `warnings` en la vista. `trip_channels(trip_id, channel_id)` como `watch_channels`. `trip_quotes`: checked_at, out_date, ret_date, total, out_price, ret_price (la mejor combinación de cada fecha de ida en cada evaluación). `trip_alerts`: out_date, ret_date, total, sent_at. Pensado para añadir una estancia (hotel) como tercer tramo más adelante.

## Versiones y CI/CD

`__version__` en `app/__init__.py` + entrada en `CHANGELOG.md` en cada versión. `.github/workflows/docker.yml`: tests (smoke + migraciones con datos + `alembic check`), panel (lint, `tsc`, Vitest, build y Playwright + axe) y, si pasan, imagen `linux/amd64` a `ghcr.io/katarem/flight-watcher` (`latest`+sha en `main`; `X.Y.Z`/`X.Y`/`latest` con la etiqueta `vX.Y.Z`, que debe coincidir con `__version__`). El `docker-compose.yml` usa esa imagen (`FW_VERSION`) y conserva `build: .`.

## Cómo ejecutar

```bash
cp .env.example .env && docker compose up -d --build   # panel en http://localhost:8000
python -m tests.smoke_test                             # sin red
python -m tests.migration_test                         # migraciones sobre una BD con datos
python -m tests.browser_mock_test                      # necesita Chromium (FW_CHROMIUM=/ruta si usas el tuyo)
cd frontend && npm ci && npm run build                 # panel → app/web
npm run dev                                            # Vite :5173, reenvía /api y /avatars a uvicorn en :8000
npm run lint && npm run typecheck && npm test          # ESLint, tsc, Vitest
npm run e2e                                            # Playwright + axe (tras build; FW_CHROMIUM=/ruta opcional)
```

Variables de entorno: `PANEL_USER` / `PANEL_PASSWORD` (credenciales del **admin inicial**, solo si aún no hay ningún admin; sin contraseña se genera una y se escribe en el log), `SECRET_KEY` (firma de cookies; si falta se crea `DATA_DIR/.secret_key`), `COOKIE_SECURE` (`1` con HTTPS), `DATA_DIR` (por defecto `./data`; en Docker es `/data` y la carpeta del host se elige con `DATA_PATH` en el compose), `DB_ENGINE` / `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD`, `SEED_DEFAULTS` (`1` por defecto; `0` desactiva las vigilancias iniciales), `WEB_DIR` (por defecto `app/web`), `FW_CHROMIUM`, `TZ`.

## Convenciones

- Cabecera de módulo con docstring en español; `from __future__ import annotations`; type hints modernos (`dict | None`).
- Acceso a BD siempre con `with db.connect() as con:` (commit/rollback automáticos); las funciones de `db.py` reciben `con` y devuelven `dict` (nunca objetos de SQLAlchemy), así el resto de la app no sabe qué motor hay. Nada de SQL específico de un motor fuera de `db.py` (el upsert de `settings` elige dialecto ahí).
- Los `except Exception` amplios llevan `# noqa: BLE001` y solo donde el fallo de un tercero (web, navegador) no debe tumbar la ronda.
- Añadir una aerolínea: nueva clase en `app/providers/<nombre>.py` (preferir `ApiProvider` con el endpoint JSON que usa la web; `CalendarProvider` solo si no hay otra vía) y añadirla a `PROVIDERS` en `providers/__init__.py`. Declarar `coverage` (`network` → implementar `network(session, origin)`; `probe` → `probe(session, o, d)`; `universal` → `max_routes`), `health_route` (una ruta que opere de verdad), `verified` (fecha en que se probó contra la web real; vacío = «sin verificar») y `notes`. Toda petición pasa por `self.request/get_json/post_json` (usan `slot()`: una a la vez por proveedor y `min_interval`+`jitter` de pausa); 403/429/página anti-bot → `ProviderBlocked`. Si cobra en otra moneda, `fetch_route` devuelve `DayPrice` con `currency` (el checker convierte). Formularios, comprobación de rutas, gráficas, avisos, zona Proveedores y plantilla de enlace en Ajustes la recogen solos.
- Ciudades y grupos: `CITIES`/`GROUPS` en `app/places.py` (una ciudad nunca tapa un aeropuerto con el mismo código). Nombres en castellano de ciudades de aeropuertos: `CITY_NAMES`. El CSV de aeropuertos no se edita a mano: `scripts/build_places.py`.
- Los campos secretos (webhook, token) nunca se devuelven al navegador; el webhook de Discord se valida contra la URL oficial. La API solo devuelve usuarios saneados con `deps.public()` y canales saneados con `deps.channel_rows()` (nunca el hash ni la `config` de un canal); al editar un canal, `notify.view_fields` solo indica si hay un secreto guardado y un secreto vacío al guardar conserva el actual.
- **API:** todo bajo `/api/v1` (`app/api/__init__.py`). Solo `POST/DELETE /session` son públicas; el resto cuelga del router `private` con `require_login`. Respuestas JSON con objetos con nombre (`{"watch": …}`, `{"watches": [...]}`); los errores para el usuario se lanzan con `deps.Invalid(errores, status)` → `{"detail", "errors": [...]}` (422 por defecto) y se muestran tal cual en el panel, así que van en castellano. Los cuerpos se validan con modelos Pydantic de tipos laxos y la validación de verdad (con mensajes) está en funciones como `watches.parse_watch`.
- **CSRF:** el middleware `csrf_guard` rechaza (403) cualquier petición no GET a `/api/` sin la cabecera `X-Requested-With`; el cliente del panel (`frontend/src/api/client.ts`) la pone siempre. Los tests usan la clase `Api` del smoke test, que también la pone.
- **Usuarios y permisos:** autenticación por sesión (`SessionMiddleware`, cookie `fw_session`); `deps.require_login` carga el usuario, `current_user` lo da y `require_admin` protege el router de `api/admin.py` (usuarios, ajustes, diagnóstico). Una vigilancia solo existe para su dueño: toda ruta con `wid` pasa por `deps.own_watch()` (404 para otro usuario, admin incluido). Cualquier consulta nueva de vigilancias/viajes/avisos/ejecuciones debe filtrar por `user_id`; los viajes pasan por `deps.own_trip()` y sus tramos se validan contra las vigilancias del usuario. **Canales:** `account._channel_routes()` registra las mismas rutas para el propio usuario (`/channels…`) y para el admin sobre cualquier usuario (`/users/{uid}/channels…`); un canal solo es accesible bajo su `user_id` (404 si no coincide) y al asignar canales a una vigilancia solo se aceptan los del dueño (`deps.own_channel_ids`).
- **Panel (frontend):** mismas URL que el panel anterior (`/watches/{id}` sale en los avisos). Cada pantalla en `src/pages`, datos con los hooks de `src/api/queries.ts` (claves en `keys`; tras una mutación se invalida la clave afectada) y mutaciones con `useMutation` + `toast`. Estilos solo con Tailwind y los colores del tema (variables `--fw-*` en `src/index.css`, que cambian con `data-theme`); no usar colores sueltos salvo los de cada proveedor/tipo de canal. Componentes interactivos sobre Radix (`src/components/ui`). Accesibilidad obligatoria: etiquetas en todos los controles (`Field`), `aria-label` en botones de solo icono, enlaces dentro de texto subrayados, contraste AA (lo comprueba axe en `npm run e2e`) y animaciones que respetan `prefers-reduced-motion` (`MotionConfig reducedMotion="user"` + CSS). Textos del panel en castellano de España.
- El servidor sirve el build: `/assets/*` con caché inmutable (Vite pone la huella en el nombre), `index.html` con `no-cache` y cualquier ruta que no sea `api/`, `avatars/` ni `assets/` devuelve `index.html` (enrutado en el navegador). Las páginas pesadas (detalle con gráficas, administración) se cargan aparte con `lazy` en `router.tsx`.
- Detalle de un viaje: `GET /trips/{id}` trae la mejor combinación de cada fecha de ida calculada al vuelo con los precios actuales (`quotes`), el total habitual (`base`), la evolución (`trend`, de `trip_quotes`) y los avisos; `GET /trips/{id}/options?date=` da todas las noches de una fecha de ida.
- Detalle de una vigilancia: `GET /watches/{id}` trae resumen por web, precios de la última comprobación, comprobaciones, avisos y los viajes de los que es tramo (`trips`); el calendario lo arma `buildCalendar()` en `frontend/src/lib/calendar.ts` (meses → semanas → días, nivel 1–4 por cuartil del mínimo del día).

## Gotchas

- **Estado real de los providers (probado 2026-09-30 desde IP residencial, todo headless):**
  - **Vueling (SVQ↔TFN):** API `apiw.vueling.com/api/v1/availability?originCode=&destinationCode=` responde a `requests` con UA honesto; ~1 año en una petición; 404 = ruta no operada (p. ej. SVQ–TFS). Ronda real SVQ↔TCI: ~300 días por sentido.
  - **Ryanair (SVQ↔TFS, estacional):** API `ryanair.com/api/farfnd/v4/oneWayFares/{o}/{d}/cheapestPerDay?outboundMonthOfDate=` por mes. No entiende TCI (devuelve todo sin precio) → por eso la expansión es genérica en el checker.
  - **Iberia:** 403 del anti-bot a cualquier Chromium headless (headless-shell y `channel="chromium"`). Solo tiene rutas con escala. `CalendarProvider` detecta 403/429 en la portada y lanza `ProviderError` claro.
  - **Binter (SVQ↔TFN directo):** sin provider. Cloudflare bloquea www y `services.bintercanarias.com/main/graphql` (operación `booking_calendar`, que sí da precios por día tras «Buscar») a headless y a `requests`. Reutilizar cookies `cf_clearance` de una sesión headed **no funciona** (atadas a UA/huella) y el sondeo repetido acabó bloqueando la IP también en headed. No insistir contra Binter.
  - **Air Europa** (solo con escala TFN→MAD→SVQ): 403 en headless (página «Estamos actualizando la web»).
  - **Descartadas por el usuario (2026-09-30): Binter, Iberia (provider eliminado) y Air Europa.** Iberia vuelve «en estudio» en la 1.4.0 (solo prueba de portada). Binter y Air Europa siguen fuera: no añadirlos ni a las pruebas. Según Aena no hay más directas: SVQ↔TFN = Vueling + Binter; SVQ↔TFS = Ryanair. Wikipedia/agregadores listaban Air Europa TFN–SVQ directo: **falso** según Aena (TFN: solo BIO y MAD).
  - El smoke test registra un `MockWebProvider(CalendarProvider)` para cubrir la rama con navegador del checker.
  - **Wizz Air y Google Flights (2026-10-10): implementados sin poder probarlos contra la web real** (la sesión de desarrollo no tenía salida a esas webs). Wizz Air: versión de API en `wizzair.com/buildnumber`, mapa en `/Api/asset/map`, precios con `POST /Api/search/timetable` por mes (moneda de salida). Google Flights: `GetCalendarGraph` (sin documentar; `request_body`/`parse_response` en `google.py`, parser tolerante que lanza error claro si cambia). Ryanair: la red de rutas (`/api/views/locate/searchWidget/routes/es/airport/{o}`) tampoco está verificada aún. Verificarlos desde IP residencial en Proveedores → «Probar» y, si funcionan, poner `verified`.
  - **Volotea, easyJet e Iberia: en estudio** (`providers/candidates.py`): solo se prueba su portada (sin navegador y, si se pide, headless). Decidir si merecen proveedor según lo que diga la zona Proveedores desde la IP del usuario.
- Decisión: **no se usan técnicas de sigilo/spoofing** (UA falso de navegador, stealth plugins, reutilizar cookies anti-bot) para saltar anti-bots. Las APIs se llaman con `USER_AGENT` honesto (`providers/base.py`).
- Vueling bloquea IPs de centros de datos: ejecutar desde IP residencial. Los CAPTCHA no se resuelven (la ronda falla y se avisa).
- Para depurar una web: Ajustes → activar diagnóstico, «Comprobar ahora», revisar capturas/HTML/JSON en `/debug`, ajustar `sel_*` y `url_hints` del proveedor.
- `requirements.txt` no incluye lo que necesita `tests.smoke_test` (`TestClient` pide `httpx`/`httpx2`); instálalo aparte para correr los tests.
- Plantillas de enlace editables en Ajustes (`link_<provider>`) con `{origin} {destination} {date} {date_dmy} {year} {month} {day}`.
- `seed_defaults()` (SVQ↔TCI con vueling,ryanair) solo actúa si la tabla `watches` está vacía; el smoke test depende de esas vigilancias iniciales y simula que Vueling solo opera TFN y Ryanair solo TFS.
- La regla «habitual» usa la mediana de la ruta+web, no la de la misma fecha de vuelo.
- Sesión: la cookie guarda `uid` y una huella del hash de la contraseña; el usuario se recarga de BD en cada petición, así que desactivar/borrar o cambiar la clave cierra las sesiones al instante. Un admin no puede cambiarse a sí mismo el rol ni desactivarse, y siempre debe quedar un admin activo.
- `bootstrap_admin()` (en cada arranque): si no hay admin lo crea; también asigna al admin las vigilancias sin dueño y convierte los antiguos ajustes globales `discord_webhook`/`telegram_*` en canales del admin asignados a todas sus vigilancias (y `notify_errors` a su fila; los borra de `settings`). Es la vía de actualización de BD anteriores a los usuarios. `seed_defaults(user_id)` siembra las vigilancias iniciales para el admin.
- **SQLite + Alembic + CASCADE:** Alembic cambia columnas recreando la tabla (DROP + copia) y con `foreign_keys=ON` el `ON DELETE CASCADE` borra los datos hijos (vigilancias, precios…). Por eso `db.init()` desactiva las claves foráneas durante las migraciones (el `PRAGMA` solo vale fuera de transacción) y las reactiva al terminar. Al añadir una migración que toque tablas padre, probarla sobre una BD **con datos** (BD en la revisión anterior con filas en `watches/prices/alerts/runs`) y comprobar que los recuentos no cambian. En las migraciones, las tablas ligeras (`sa.table`) no sirven para `inserted_primary_key`: declara `sa.Table` con su PK.
- Los tests inician sesión con el admin de `PANEL_USER`/`PANEL_PASSWORD` y usan un `Api` (envoltorio de `TestClient` con la cabecera CSRF) por usuario (cada cliente conserva su cookie). El smoke test crea un `WEB_DIR` falso para probar cómo se sirve el panel sin depender de Node.
- Pruebas del panel (`frontend/e2e`): un único servidor (`tests/e2e_server.py`, puerto 8765) compartido por todas, en serie; fuera de CI se reutiliza si ya está arrancado, así que los datos que crean deben tener nombres únicos o borrarse al final. `expectAccessible()` espera a que acaben las animaciones antes de pasar axe.
- Solo ida por vigilancia; para ida y vuelta se crean dos vigilancias y se juntan en un viaje (`/trips`). El formulario de un viaje propone la vigilancia de la ruta al revés y, si no existe, enlaza a `/watches/new?origin=…&destination=…&for_trip=<ida>`, que al crearla vuelve a `/trips/new?outbound=…&return=…`.
- `FormSection` marca su descripción como `aria-hidden` (el título va en la `legend`): nada enfocable (enlaces) dentro de la descripción, axe lo rechaza.
- El tooltip de `PriceChart` usa el color de texto del tema (`itemStyle`): el color de algunas webs no da el contraste AA.
- OurAirports llega en `app/data/airports.csv` (solo `scheduled_service=yes`, con IATA, sin helipuertos ni hidroaviones). La copia actual se generó desde el paquete npm `ourairports-data-js` 1.0.3 (instantánea de feb. 2025, mismo contenido que el CSV oficial) porque la sesión no tenía acceso a ourairports.com; `python scripts/build_places.py` la regenera desde la web oficial.
- `.gitignore` ignora solo `/data/` (la carpeta de datos de la raíz), no `app/data/`.
- Las comprobaciones de cobertura y de salud corren en hilos (`ThreadPoolExecutor`, `shutdown(wait=False)`): un proveedor lento no retrasa al resto, y su respuesta queda en caché aunque haya pasado el tiempo límite. Los dobles ponen `min_interval = jitter = 0`.
- Al cambiar `prices.price` recuerda que es **siempre euros**: baselines, chollos, gráficas y calendario no saben de monedas.
- Webhook y token se guardan en texto plano en la BD: no exponer el panel sin autenticación.
- Multi-motor (verificado 2026-09-30 con el smoke test y `alembic check` contra postgres:16, mariadb:11 y mysql:8.4): precios en `Double` (en MySQL `Float` es precisión simple), fechas como texto ISO (`String`), tablas `utf8mb4`, `pool_pre_ping` porque MySQL corta conexiones inactivas, y `PRAGMA foreign_keys=ON` en cada conexión SQLite para que funcione el `CASCADE`. Las columnas `key` y `trigger` son palabras reservadas en MySQL: SQLAlchemy las entrecomilla, no escribir SQL crudo con ellas.
- **Cambiar el esquema:** editar las `Table` de `db.py` y generar la revisión **contra una BD nueva** (`DATA_DIR=$(mktemp -d) python -c "from app import db; db.init()"` y luego `alembic revision --autogenerate -m "…" --rev-id 0002` con el mismo `DATA_DIR`). Revisar el archivo generado (Alembic no detecta renombrados) y comprobar con `alembic check`. Nunca importar `app.db` dentro de una revisión: cada revisión es una foto congelada.
- Contra una BD SQLite anterior a Alembic, el autogenerate ve diferencias falsas (TEXT vs VARCHAR, REAL vs DOUBLE, FK reflejadas): en SQLite son equivalentes y no afectan en ejecución, pero por eso las revisiones se generan siempre sobre una BD nueva.
- BD anterior a Alembic (tablas sin `alembic_version`): `db.init()` añade `prices.origin/destination` si faltan, marca la BD con `stamp 0001` y sigue con `upgrade head`. Verificado con datos reales del esquema del primer commit.
- Para probar contra otro motor: `DB_ENGINE=postgres DB_HOST=127.0.0.1 DB_PORT=… DB_USER=… DB_PASSWORD=… python -m tests.smoke_test` sobre una BD vacía.
