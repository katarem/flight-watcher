# Flight Watcher

Panel web + bot que vigila los precios de vuelos en **Vueling** y **Ryanair** (y en las aerolíneas que añadas), guarda todo el histórico en SQLite (o PostgreSQL / MySQL / MariaDB), dibuja gráficas de evolución por web y te avisa por **Discord** y/o **Telegram** con un **enlace directo a cada fecha**.

Sustituye al script suelto anterior: ya no hay que editar archivos ni tocar el cron. Todo se configura desde el panel.

## Puesta en marcha

```bash
cp .env.example .env        # usuario y contraseña del administrador
docker compose pull         # descarga la imagen publicada en ghcr.io
docker compose up -d
```

Para construir la imagen en local en lugar de descargarla: `docker compose up -d --build`.

Abre `http://localhost:8000`. En el primer arranque se crean dos vigilancias: **Sevilla → Tenerife** (`SVQ → TCI`) y **Tenerife → Sevilla**, con Vueling y Ryanair y un aviso a partir de 40 €.

`TCI` es el código de ciudad de Tenerife: el bot consulta **Tenerife Norte (TFN)** y **Tenerife Sur (TFS)** y se queda con el precio más bajo de cada día, indicando el aeropuerto (p. ej. `SVQ→TFS`). Puedes usar `TFN` o `TFS` si solo te interesa uno.

### Origen y destino: aeropuertos, ciudades, países y grupos

El formulario autocompleta el origen y el destino (escribe «sevilla», «malaga», «TCI», «canarias»…):

- **Aeropuertos**: los de [OurAirports](https://ourairports.com/data/) (dominio público) con vuelos regulares y código IATA, en `app/data/airports.csv`. Se regeneran con `pip install pycountry && python scripts/build_places.py`.
- **Ciudades** con varios aeropuertos (código IATA de ciudad: `TCI`, `LON`, `PAR`, `MIL`…), **países** (código ISO: `ES`, `PT`…) y **grupos** propios (`canarias`, `baleares`, `andalucia`…), definidos en `app/places.py`.

Una ciudad, un país o un grupo se expanden a todos los pares de aeropuertos reales (como mucho 60 combinaciones por vigilancia).

Al elegir origen y destino, el panel **comprueba la ruta** en todos los proveedores a la vez (con un tiempo límite por proveedor) y muestra cuáles la operan y por qué los demás no. Solo se pueden elegir los que la operan; si uno no se ha podido comprobar, se puede elegir igualmente y se comprobará más adelante.

### Carpeta de datos y base de datos

Todo se configura en `.env`:

| Variable | Por defecto | Para qué |
|---|---|---|
| `DATA_PATH` | `./data` | Carpeta **del host** montada en `/data`: BD SQLite, avatares, clave de sesión y archivos de diagnóstico |
| `PANEL_USER`, `PANEL_PASSWORD` | `admin` / aleatoria | Cuenta del **administrador inicial** (solo se usa si aún no hay ningún admin) |
| `SECRET_KEY` | generada en `/data/.secret_key` | Clave con la que se firman las cookies de sesión |
| `COOKIE_SECURE` | vacío | `1` si sirves el panel por HTTPS: la cookie solo viaja cifrada |
| `DB_ENGINE` | `sqlite` | `sqlite`, `postgres`, `mysql` o `mariadb` |
| `DB_HOST`, `DB_PORT` | `localhost`, 5432 / 3306 | Servidor (se ignoran con SQLite) |
| `DB_NAME` | `flight_watcher` | La base de datos debe existir; las tablas se crean solas |
| `DB_USER`, `DB_PASSWORD` | vacíos | Credenciales |

Con MySQL/MariaDB las tablas se crean en `utf8mb4`. Cambiar de motor no migra los datos: el nuevo arranca vacío con las vigilancias iniciales.

El esquema se gestiona con **Alembic**: al arrancar, la app aplica sola las migraciones pendientes (`app/migrations/`), también sobre bases de datos SQLite creadas con versiones anteriores.

Después, en el panel:

1. Entra con el administrador (`PANEL_USER` / `PANEL_PASSWORD`). Si no los definiste, se crea `admin` con una contraseña aleatoria que sale **una sola vez en el log** del contenedor (`docker compose logs flight-watcher`).
2. **Perfil → Canales de aviso:** añade tus canales (Discord con webhook, Telegram con token de bot y chat ID) y pulsa *Probar*. Después marca, en cada vigilancia, a qué canales debe avisar.
3. **Ajustes → Programación** (solo admin): elige a qué hora(s) se comprueba (p. ej. `8` o `8,20`) y la zona horaria.
4. Pulsa **Comprobar todo** para traer los primeros precios.

### Usuarios

Cada usuario tiene **sus propias vigilancias, su histórico, sus avisos y una lista de canales de aviso** (hoy de tipo Discord o Telegram; puede crear los que quiera, también varios del mismo tipo), y un **avatar** (PNG, JPG, GIF o WebP de hasta 2 MB; si no hay, se muestran las iniciales). Nadie ve las vigilancias de otro, tampoco el administrador.

Cada vigilancia avisa **solo a los canales que tenga marcados** (formulario de la vigilancia); un canal puede pausarse sin borrarlo. Si una vigilancia no tiene canales no avisa, y los chollos se enviarán cuando le asignes alguno.

El administrador tiene además el apartado **Usuarios** (crear, editar, desactivar y eliminar usuarios, asignar rol y restablecer contraseñas; y **crear, editar, probar y borrar los canales de aviso de cualquier usuario**, útil si alguien no sabe configurarlos; los secretos ya guardados no se muestran a nadie) y los **Ajustes** y el **Diagnóstico** globales. Un usuario desactivado no puede entrar y sus vigilancias no se comprueban; eliminarlo borra también sus vigilancias y su histórico. Cada usuario cambia su contraseña, nombre y avatar en **Perfil**.

Si actualizas desde una versión sin usuarios, el administrador inicial hereda las vigilancias existentes y los canales de aviso que había en Ajustes (como canales «Discord» / «Telegram» asignados a todas ellas).

Para añadir otro tipo de canal (Slack, correo…), añade una entrada a `KINDS` en `app/notify.py`: campos del formulario, validación y función de envío. Aparece sola en las pantallas.

## Versiones e imagen Docker

La versión vive en `app/__init__.py` (`__version__`, hoy **1.3.0**; se ve en el pie del panel) y los cambios se anotan en [CHANGELOG.md](CHANGELOG.md).

El CI (`.github/workflows/docker.yml`) ejecuta el test de humo, comprueba que las migraciones están al día, pasa el lint, los tests y las pruebas en navegador del panel, y publica la imagen en **ghcr.io/katarem/flight-watcher** (`linux/amd64`):

| Evento | Etiquetas publicadas |
|---|---|
| Push a `main` | `latest` y `sha-<commit>` |
| Etiqueta `vX.Y.Z` | `X.Y.Z`, `X.Y` y `latest` |
| Pull request | solo construye (no publica) |

Para sacar una versión: sube `__version__`, actualiza el CHANGELOG, haz merge a `main` y crea la etiqueta (`git tag v1.1.0 && git push origin v1.1.0`); el CI falla si la etiqueta no coincide con `__version__`. En el servidor, fija `FW_VERSION=1.1.0` en `.env` (o deja `latest`) y ejecuta `docker compose pull && docker compose up -d`. Con el paquete **público** no hace falta `docker login` para descargarlo. La imagen lleva la etiqueta `org.opencontainers.image.source`, que la enlaza con el repositorio: si el repositorio es público, el paquete nace público; si no, ponlo público una vez en GitHub → Packages → *flight-watcher* → Package settings → Change visibility (y comprueba que ahí el repositorio aparece conectado). Si lo dejas privado, `docker login ghcr.io` con un token `read:packages`.

## Aerolíneas y cómo se consultan

Todo funciona en **headless**. Siempre que se puede se usa la API JSON pública que la propia web usa para su calendario (sin navegador: más rápido y estable). Cada proveedor hace **una sola petición a la vez** y con **pausas** entre ellas (aunque coincidan la ronda, la comprobación de una ruta y la prueba de acceso), para no acabar con la IP bloqueada.

Cada proveedor declara cómo se sabe qué rutas cubre:

- **Red de rutas** (Ryanair, Wizz Air): publica su red; se descarga y se mira si incluye el par de aeropuertos.
- **Pregunta por cada ruta** (Vueling): se le pregunta directamente (un 404 significa que no la opera).
- **Cualquier ruta** (Google Flights): cubre cualquier ruta, directa o con escalas (como mucho 12 pares de aeropuertos por vigilancia).

La cobertura se guarda (`provider_routes`) y cada vigilancia sabe qué pares opera cada proveedor. **Cada lunes** se revalida: si una ruta de temporada se abre o se cierra, se avisa a los canales de la vigilancia, y mientras está cerrada ese proveedor no se consulta.

| Proveedor | Método | Estado |
|---|---|---|
| Vueling | API `apiw.vueling.com/api/v1/availability` | ✅ verificado el 2026-09-30 (~1 año en una petición) |
| Ryanair | API `ryanair.com/api/farfnd/v4/.../cheapestPerDay` + red de rutas del buscador | ✅ tarifas verificadas el 2026-09-30 (una petición por mes) |
| Wizz Air | API de wizzair.com (`/Api/asset/map` y `/Api/search/timetable`) | ⚠️ sin verificar contra la web real: pruébalo en **Proveedores** |
| Google Flights | Llamada interna `GetCalendarGraph` del calendario | ⚠️ sin verificar contra la web real: pruébalo en **Proveedores** |

Rutas Sevilla ↔ Tenerife:

| Aerolínea | Rutas Sevilla ↔ Tenerife | Estado (2026-09-30) |
|---|---|---|
| Vueling | SVQ ↔ TFN directo, todo el año | ✅ |
| Ryanair | SVQ ↔ TFS directo, **estacional** (sin precios en invierno) | ✅ |
| Binter | SVQ ↔ TFN directo, 5 días/semana | ❌ descartada: Cloudflare bloquea web y API a clientes automatizados |
| Iberia | Solo con escala (Madrid) | 🔎 en estudio (el 2026-09-30, 403 al navegador headless) |
| Air Europa | Solo con escala (TFN → Madrid → SVQ) | ❌ descartada: 403 al navegador headless |

**Volotea, easyJet e Iberia** están «en estudio»: aún no son proveedores, pero la zona **Proveedores** comprueba si sus portadas dejan entrar a un cliente honesto (y, si se pide, a Chromium headless) desde tu IP, y qué anti-bot se detecta.

Según Aena (2026-09-30), **no hay más aerolíneas directas**: SVQ ↔ TFN solo Vueling y Binter; SVQ ↔ TFS solo Ryanair.

Si una web bloquea, la comprobación falla con un mensaje claro («bloquea el navegador automatizado (HTTP 403)») y te avisa. **No se usan técnicas para esquivar sistemas anti-bot.**

Para depurar: **Ajustes → Navegador y diagnóstico → Guardar capturas, HTML y JSON**, pulsa **Comprobar ahora** y abre **Diagnóstico** (en los proveedores por API se guarda la respuesta JSON de cada petición).

Si alguna vigilancia antigua tenía `iberia` marcada, se ignora al comprobar; al editarla y guardarla desaparece.

> Ejecútalo desde una IP residencial: las aerolíneas suelen bloquear IPs de centros de datos.

### Prueba de acceso (Proveedores)

Los administradores tienen el apartado **Proveedores**, una especie de *healthcheck*: por cada proveedor, desde la IP del servidor, comprueba la cobertura (red de rutas o pregunta directa) y los precios de un mes de una ruta (la suya de prueba o la que indiques), y dice si es **accesible**, si **nos bloquea** (403/429/anti-bot), si **falla** o si **no responde**, con el código HTTP y el tiempo de cada paso. Guarda el último resultado de cada uno. También prueba el cambio de divisas del BCE y las aerolíneas en estudio, y permite **revalidar las rutas** de todas las vigilancias en el momento.

### Escalas y monedas

Cada vigilancia tiene un **máximo de escalas** (solo directos por defecto). Las aerolíneas solo venden sus vuelos directos; con escalas solo busca Google Flights. Cada precio guarda sus escalas.

Los precios se guardan en su **moneda original** y con su **equivalente en euros** según el tipo de referencia diario del **BCE** (Wizz Air cobra en la moneda del aeropuerto de salida). Las reglas de aviso, las gráficas y el calendario usan los euros; los avisos muestran también la moneda original.

## Enlaces con las fechas elegidas

Cada precio del panel y cada aviso lleva un enlace a esa fecha concreta.

- **Vueling:** usa el formato oficial de deeplink (`o`, `d`, `dd` obligatorios):
  `https://tickets.vueling.com/booking?o={origin}&d={destination}&dd={date}&adt=1&chd=0&inf=0&c=es-ES&cur=EUR`.
  Residentes en islas o Ceuta pueden añadir `&dt=1` en Ajustes.
- **Ryanair:** `https://www.ryanair.com/es/es/trip/flights/select?...&dateOut={date}&isReturn=false&originIata={origin}&destinationIata={destination}`.
- **Wizz Air:** `https://wizzair.com/es-es/booking/select-flight/{origin}/{destination}/{date}/null/1/0/0/null`.
- **Google Flights:** una búsqueda de solo ida en esa fecha (`google.com/travel/flights?q=…`).

## Reglas de aviso

Por cada vigilancia y web se avisa de una fecha si:

- su precio es **≤ el precio máximo** que definas, **o**
- es un **X % inferior a lo habitual** (mediana de los precios guardados de esa ruta y web; se activa con las *muestras mínimas* de Ajustes, 30 por defecto).

No se repite el aviso de la misma fecha salvo que el precio baje aún más. Si no hay ningún canal configurado, los avisos no se marcan como enviados y se mandarán cuando lo configures.

Puedes limitar cada vigilancia a un rango de fechas; sin límites se comprueban todas las que tengan precio desde hoy.

## Panel

Aplicación React (carpeta `frontend/`) que habla con la API JSON del servidor (`/api/v1`). Tema claro u oscuro (sigue al sistema o se elige en el menú de usuario), pensado para móvil y accesible (navegable con teclado, revisado con axe contra WCAG 2.1 AA).

- **Panel:** cada vigilancia con el mejor precio actual por web, enlace a esa fecha, etiqueta *chollo*, errores, minigráfica de tendencia, y los últimos avisos y ejecuciones.
- **Detalle de una vigilancia:**
  - **Calendario de precios** de la última comprobación: color según lo barato que sale cada día, borde para los chollos, filtro por web. Pulsar un precio abre esa fecha en la web; pulsar el día muestra su historial.
  - Gráficas de la **evolución del precio mínimo** por web, del **precio actual por fecha de vuelo** y del **historial de una fecha concreta**.
  - Historial de comprobaciones y avisos enviados.
- **Ejecuciones** y **Diagnóstico** para ver qué pasó en cada comprobación.
- **Proveedores** (administradores): prueba de acceso a cada web, ver «Prueba de acceso» arriba.

### Desarrollo del panel

Necesita Node 22. El servidor de Python sirve el panel ya compilado desde `app/web` (la imagen Docker lo compila sola).

```bash
cd frontend
npm ci
npm run build          # compila a ../app/web (lo que sirve FastAPI)
npm run dev            # Vite en :5173 con recarga en caliente; reenvía /api y /avatars a :8000
```

Para `npm run dev`, arranca antes la API: `uvicorn app.main:app --port 8000` desde la raíz. Comprobaciones: `npm run lint`, `npm run typecheck`, `npm test` (Vitest) y `npm run e2e` (Playwright contra la app real con datos simulados, `tests/e2e_server.py`; antes `npm run build` y `npx playwright install chromium`, o `FW_CHROMIUM=/ruta/chrome`).

La API tiene documentación interactiva en `/api/v1/docs` (solo con sesión iniciada en el panel). Las peticiones que cambian algo necesitan la cabecera `X-Requested-With`, así que desde ahí solo funcionan las de lectura.

## Añadir otra aerolínea

1. Crea `app/providers/<nombre>.py`. Si la web tiene un endpoint JSON accesible, hereda de `ApiProvider` e implementa `fetch_route` (mira `vueling.py`, `ryanair.py` o `wizzair.py`). Declara su cobertura (`coverage = "network"` con `network()`, `"probe"` con `probe()` o `"universal"`), su ruta de prueba (`health_route`) y, si hace falta, una pausa mayor (`min_interval`). Las peticiones con `get_json`/`post_json` ya respetan el turno del proveedor. Si hay que recorrer la web:

   ```python
   from .base import CalendarProvider

   class RyanairProvider(CalendarProvider):
       key = "ryanair"
       label = "Ryanair"
       color = "#073590"
       home_url = "https://www.ryanair.com/es/es"
       default_link_template = "https://www.ryanair.com/es/es/trip/flights/select?adults=1&dateOut={date}&originIata={origin}&destinationIata={destination}"
       url_hints = ("calendar", "fare")
       # sobrescribe sel_* / dismiss_cookies() / open_calendar() si hace falta
   ```

2. Regístrala en `app/providers/__init__.py` (añádela a la tupla de `PROVIDERS`).

Aparece sola en los formularios, la comprobación de rutas, gráficas, avisos, la zona Proveedores y la plantilla de enlace de Ajustes.

Para añadir otra ciudad (como `TCI`) o un grupo (como `canarias`), añádelo a `CITIES` o `GROUPS` en `app/places.py`.

## Seguridad

- El acceso es con usuario y contraseña (sesión por cookie firmada, `SameSite=Lax`; además, toda petición que cambia algo exige la cabecera `X-Requested-With`, que un formulario de otra web no puede enviar). Las contraseñas se guardan con scrypt; cambiarla cierra las demás sesiones y varios fallos seguidos bloquean el inicio de sesión unos minutos. Si publicas el panel, ponlo tras HTTPS y define `COOKIE_SECURE=1`.
- Los webhooks y tokens de los canales se guardan en la base de datos en texto plano (JSON): protege la BD y su copia de seguridad.
- Solo se aceptan webhooks de Discord con la URL oficial y los campos secretos nunca se devuelven al navegador.
- Respeta los términos de uso de cada aerolínea; una comprobación al día es una frecuencia razonable.

## Estructura

```
app/
  __init__.py     versión (__version__)
  main.py         servidor: API, avatares, protección CSRF y el panel compilado (app/web)
  api/            API JSON /api/v1: sesión, vigilancias, perfil y canales, administración
  auth.py         contraseñas (scrypt), validación de usuarios y freno de intentos de login
  avatars.py      guardado y validación de avatares
  checker.py      ronda de comprobaciones + reglas de aviso
  coverage.py     cobertura de rutas por proveedor, comprobación al crear y revalidación semanal
  health.py       prueba de acceso a los proveedores (zona Proveedores)
  places.py       catálogo de aeropuertos, ciudades, países y grupos (datos en app/data)
  fx.py           cambio de divisas a euros (BCE)
  scheduler.py    planificación (se cambia desde Ajustes)
  notify.py       tipos de canal (Discord / Telegram) y envío
  db.py           acceso a datos (SQLAlchemy Core: SQLite, PostgreSQL, MySQL, MariaDB)
  migrations/     migraciones de Alembic
  providers/      base.py (abstracción), extract.py, vueling.py, ryanair.py, wizzair.py, google.py, candidates.py
scripts/          build_places.py (regenera el catálogo de aeropuertos desde OurAirports)
frontend/         panel React + Vite + TypeScript (src/pages, src/components, src/api) y pruebas e2e
tests/
  smoke_test.py         extremo a extremo con datos simulados (sin red)
  migration_test.py     migraciones sobre una BD con datos
  browser_mock_test.py  Playwright real contra una web simulada
  e2e_server.py         servidor con datos simulados para las pruebas del panel
```

Pruebas de Python (necesitan además `pip install httpx`): `python -m tests.smoke_test`, `python -m tests.migration_test` y `python -m tests.browser_mock_test` (esta última necesita Chromium; con uno propio: `FW_CHROMIUM=/ruta/chromium`). Las del panel, en «Desarrollo del panel».

## Limitaciones conocidas

- Solo ida por vigilancia (para ida y vuelta, crea dos vigilancias, como en tu configuración inicial).
- Los precios del calendario son «desde» y no incluyen equipaje facturado.
- La regla «habitual» compara con la mediana de la ruta, no con la de esa misma fecha.
