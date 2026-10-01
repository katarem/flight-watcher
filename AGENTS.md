# Flight Watcher — contexto del proyecto

Panel web + bot multiusuario que vigila precios de vuelos (solo ida) en Vueling y Ryanair, guarda el histórico en SQLite/PostgreSQL/MySQL/MariaDB, dibuja gráficas y avisa por Discord y/o Telegram (lista de canales por usuario, asignables a cada vigilancia) con un enlace directo a cada fecha. Todo el código, comentarios, textos de UI y README están **en castellano de España** (tuteo, nunca voseo ni expresiones rioplatenses); mantenlo así, también al hablar con el usuario.

## Stack

- Python 3.12, FastAPI + Jinja2 (server-side rendering), Chart.js en `app/static/charts.js`.
- SQLAlchemy **Core** (no ORM) en `app/db.py`: tablas declaradas con `Table` (fuente de verdad del esquema). Motor por `DB_ENGINE` (`sqlite` por defecto con WAL, `postgres` → psycopg, `mysql`/`mariadb` → pymysql).
- Migraciones con **Alembic** en `app/migrations/` (dentro de `app/` porque el Dockerfile solo copia esa carpeta). `db.init()` ejecuta `upgrade head` al arrancar; no hay `create_all`.
- APIs JSON públicas vía `requests` (Vueling, Ryanair) y Playwright/Chromium headless solo para proveedores sin API (hoy ninguno registrado; `CalendarProvider` queda como base y lo cubren los tests). El navegador solo se abre si algún proveedor de la ronda lo necesita.
- APScheduler (`BackgroundScheduler`) dentro del mismo proceso. `requests` para notificar.
- Docker / docker-compose. **Un único worker de uvicorn**: el planificador vive en el proceso, más workers = comprobaciones duplicadas.

## Estructura

```
app/
  __init__.py    `__version__`: única fuente de la versión (pie del panel, User-Agent, imagen Docker, CI)
  main.py        rutas FastAPI: login/sesión, panel, CRUD de vigilancias (por usuario), detalle, API de gráficas, perfil, administración de usuarios (admin), ajustes y diagnóstico (admin), ejecuciones
  auth.py        hash scrypt de contraseñas, validación de usuario/clave, LoginThrottle (en memoria)
  avatars.py     guardado de avatares en DATA_DIR/avatars (tipo por magic bytes, 2 MB, sin SVG)
  checker.py     ronda de comprobaciones (por vigilancia × proveedor) + reglas de aviso (deal_reason)
  scheduler.py   cron interno; horas/minuto/zona horaria salen de los ajustes en BD
  db.py          esquema (SQLAlchemy Core), motor/conexión, init() → Alembic, ajustes por defecto (DEFAULT_SETTINGS), consultas, bootstrap_admin(), seed_defaults()
  migrations/    Alembic: env.py (usa db.engine/db.metadata), versions/0001_esquema_inicial.py, 0002_usuarios.py, 0003_canales.py
  notify.py      tipos de canal en `KINDS` (campos, validación, envío; hoy Discord y Telegram) y `send*(channels, …)`: añadir un tipo = una entrada ahí
  fmt.py         formateo de fechas/precios para plantillas y avisos
  config.py      DATA_DIR, DEBUG_DIR, DB_ENGINE, DB_PATH (SQLite), DB_HOST/PORT/NAME/USER/PASSWORD
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

1. `scheduler` dispara `checker.run_checks()` para **todos** los usuarios (o el usuario pulsa «Comprobar»: `scheduler.run_now(watch_id, user_id)`, solo lo suyo). Un `threading.Lock` impide rondas simultáneas. Las vigilancias de usuarios desactivados se saltan.
2. Por cada vigilancia activa y cada proveedor, `routes()` expande los códigos de ciudad (TCI → TFN y TFS) y por cada par de aeropuertos se llama a `provider.fetch_prices(page, origin, destination, max_months, debug_dir)` (`page=None` en ApiProvider), hasta 2 intentos. Se queda el mínimo por día; cada `DayPrice` lleva el aeropuerto real. Una ruta que falla solo es error si ninguna dio precios (Vueling no vuela a TFS, Ryanair no vuela a TFN).
3. Se filtra por `date_from`/`date_to`, se guarda el snapshot en `prices` y se evalúa `deal_reason`: `fixed` (precio ≤ `max_price`) o `relative` (≥ `discount_pct`% bajo la mediana histórica de esa ruta+web, solo si hay `min_samples`).
4. Los chollos nuevos (`already_alerted` evita repetir salvo que baje más) se envían con `notify.send_deals` **solo a los canales asignados a esa vigilancia** (`watch_channels`) que siguen activos; sin canales no se envía ni se marca como avisado (se reenviará al asignar uno). Los fallos de la ronda (`notify_errors`) van a **todos** los canales activos de cada dueño, solo los de sus vigilancias. Solo se guardan en `alerts` si llegaron a algún canal; sin canales se reenvían cuando se configuren.
5. Se purga el histórico (`retention_days`) y los archivos de diagnóstico de más de 7 días.

## Modelo de datos (`data/flight_watcher.db` con SQLite, o la BD de `DB_NAME`)

- `settings(key, value)`: clave/valor **globales** (solo admin). `db.get_settings()` mezcla `DEFAULT_SETTINGS` con lo guardado. También hay claves dinámicas `link_<provider>` (plantilla de enlace por proveedor).
- `users`: id, username (único, minúsculas), display_name, password_hash (`scrypt$n$r$p$salt$hash`), role (`admin`|`user`), enabled, avatar (nombre de archivo o NULL), notify_errors, created_at. `watches.user_id` → `users` con `ON DELETE CASCADE` (borrar un usuario se lleva sus vigilancias, canales, precios, avisos y ejecuciones).
- `channels`: id, user_id, kind (`discord`|`telegram`, ver `notify.KINDS`), name, config (JSON con los campos del tipo, **con secretos**), enabled. `watch_channels(watch_id, channel_id)`: qué canales avisan por cada vigilancia (ambos con CASCADE). `db.list_watches/get_watch` añaden `channel_ids`.
- `watches`: id, user_id, name, origin, destination (IATA 3 letras), providers (CSV de claves), max_price, discount_pct, date_from, date_to, enabled.
- `prices`: watch_id, provider, flight_date, price, currency, checked_at, origin, destination (aeropuerto real; NULL en datos antiguos = el de la vigilancia). Un registro por día de vuelo por comprobación. Migración con `ALTER TABLE` en `db.init()`.
- `alerts`, `runs`: avisos enviados y ejecuciones (ok/error/n_prices/n_deals). Todo con `ON DELETE CASCADE` desde `watches`.

## Versiones y CI/CD

`__version__` en `app/__init__.py` + entrada en `CHANGELOG.md` en cada versión. `.github/workflows/docker.yml`: tests (smoke + `alembic check`) y, si pasan, imagen `linux/amd64` a `ghcr.io/katarem/flight-watcher` (`latest`+sha en `main`; `X.Y.Z`/`X.Y`/`latest` con la etiqueta `vX.Y.Z`, que debe coincidir con `__version__`). El `docker-compose.yml` usa esa imagen (`FW_VERSION`) y conserva `build: .`.

## Cómo ejecutar

```bash
cp .env.example .env && docker compose up -d --build   # panel en http://localhost:8000
python -m tests.smoke_test                             # sin red
python -m tests.browser_mock_test                      # necesita Chromium (FW_CHROMIUM=/ruta si usas el tuyo)
```

Variables de entorno: `PANEL_USER` / `PANEL_PASSWORD` (credenciales del **admin inicial**, solo si aún no hay ningún admin; sin contraseña se genera una y se escribe en el log), `SECRET_KEY` (firma de cookies; si falta se crea `DATA_DIR/.secret_key`), `COOKIE_SECURE` (`1` con HTTPS), `DATA_DIR` (por defecto `./data`; en Docker es `/data` y la carpeta del host se elige con `DATA_PATH` en el compose), `DB_ENGINE` / `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD`, `SEED_DEFAULTS` (`1` por defecto; `0` desactiva las vigilancias iniciales), `FW_CHROMIUM`, `TZ`.

## Convenciones

- Cabecera de módulo con docstring en español; `from __future__ import annotations`; type hints modernos (`dict | None`).
- Acceso a BD siempre con `with db.connect() as con:` (commit/rollback automáticos); las funciones de `db.py` reciben `con` y devuelven `dict` (nunca objetos de SQLAlchemy), así el resto de la app no sabe qué motor hay. Nada de SQL específico de un motor fuera de `db.py` (el upsert de `settings` elige dialecto ahí).
- Los `except Exception` amplios llevan `# noqa: BLE001` y solo donde el fallo de un tercero (web, navegador) no debe tumbar la ronda.
- Añadir una aerolínea: nueva clase en `app/providers/<nombre>.py` (preferir `ApiProvider` con el endpoint JSON que usa la web; `CalendarProvider` solo si no hay otra vía) y añadirla al dict `PROVIDERS` de `providers/__init__.py`. Formularios, gráficas, avisos y plantilla de enlace en Ajustes la recogen solos.
- Los campos secretos (webhook, token) nunca se devuelven al navegador; el webhook de Discord se valida contra la URL oficial. A las plantillas solo llegan usuarios saneados con `_public()` y canales saneados con `_channel_rows()` (nunca el hash ni la `config` de un canal); en los formularios `notify.view_fields` solo indica si hay un secreto guardado y un secreto vacío al guardar conserva el actual.
- **Usuarios y permisos:** autenticación por sesión (`SessionMiddleware`, cookie `fw_session`); `require_login` es dependencia global (salvo `/login`), `current_user` da el usuario y `require_admin` protege `/admin/users*`, `/settings` y `/debug`. Una vigilancia solo existe para su dueño: toda ruta con `wid` pasa por `_own_watch()` (404 para otro usuario, admin incluido). Cualquier consulta nueva de vigilancias/avisos/ejecuciones debe filtrar por `user_id`. **Canales:** `_channel_routes()` registra las mismas pantallas para el propio usuario (`/profile/channels…`) y para el admin sobre cualquier usuario (`/admin/users/{uid}/channels…`); un canal solo es accesible bajo su `user_id` (404 si no coincide) y al asignar canales a una vigilancia solo se aceptan los del dueño (`_own_channel_ids`).
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
- Sesión: la cookie guarda `uid` y una huella del hash de la contraseña; el usuario se recarga de BD en cada petición, así que desactivar/borrar o cambiar la clave cierra las sesiones al instante. Un admin no puede cambiarse a sí mismo el rol ni desactivarse, y siempre debe quedar un admin activo.
- `bootstrap_admin()` (en cada arranque): si no hay admin lo crea; también asigna al admin las vigilancias sin dueño y convierte los antiguos ajustes globales `discord_webhook`/`telegram_*` en canales del admin asignados a todas sus vigilancias (y `notify_errors` a su fila; los borra de `settings`). Es la vía de actualización de BD anteriores a los usuarios. `seed_defaults(user_id)` siembra las vigilancias iniciales para el admin.
- **SQLite + Alembic + CASCADE:** Alembic cambia columnas recreando la tabla (DROP + copia) y con `foreign_keys=ON` el `ON DELETE CASCADE` borra los datos hijos (vigilancias, precios…). Por eso `db.init()` desactiva las claves foráneas durante las migraciones (el `PRAGMA` solo vale fuera de transacción) y las reactiva al terminar. Al añadir una migración que toque tablas padre, probarla sobre una BD **con datos** (BD en la revisión anterior con filas en `watches/prices/alerts/runs`) y comprobar que los recuentos no cambian. En las migraciones, las tablas ligeras (`sa.table`) no sirven para `inserted_primary_key`: declara `sa.Table` con su PK.
- Los tests inician sesión con el admin de `PANEL_USER`/`PANEL_PASSWORD` y usan `TestClient` por usuario (cada cliente conserva su cookie).
- Solo ida por vigilancia; para ida y vuelta se crean dos vigilancias.
- Webhook y token se guardan en texto plano en la BD: no exponer el panel sin autenticación.
- Multi-motor (verificado 2026-09-30 con el smoke test y `alembic check` contra postgres:16, mariadb:11 y mysql:8.4): precios en `Double` (en MySQL `Float` es precisión simple), fechas como texto ISO (`String`), tablas `utf8mb4`, `pool_pre_ping` porque MySQL corta conexiones inactivas, y `PRAGMA foreign_keys=ON` en cada conexión SQLite para que funcione el `CASCADE`. Las columnas `key` y `trigger` son palabras reservadas en MySQL: SQLAlchemy las entrecomilla, no escribir SQL crudo con ellas.
- **Cambiar el esquema:** editar las `Table` de `db.py` y generar la revisión **contra una BD nueva** (`DATA_DIR=$(mktemp -d) python -c "from app import db; db.init()"` y luego `alembic revision --autogenerate -m "…" --rev-id 0002` con el mismo `DATA_DIR`). Revisar el archivo generado (Alembic no detecta renombrados) y comprobar con `alembic check`. Nunca importar `app.db` dentro de una revisión: cada revisión es una foto congelada.
- Contra una BD SQLite anterior a Alembic, el autogenerate ve diferencias falsas (TEXT vs VARCHAR, REAL vs DOUBLE, FK reflejadas): en SQLite son equivalentes y no afectan en ejecución, pero por eso las revisiones se generan siempre sobre una BD nueva.
- BD anterior a Alembic (tablas sin `alembic_version`): `db.init()` añade `prices.origin/destination` si faltan, marca la BD con `stamp 0001` y sigue con `upgrade head`. Verificado con datos reales del esquema del primer commit.
- Para probar contra otro motor: `DB_ENGINE=postgres DB_HOST=127.0.0.1 DB_PORT=… DB_USER=… DB_PASSWORD=… python -m tests.smoke_test` sobre una BD vacía.
