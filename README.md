# Flight Watcher

Panel web + bot que vigila los precios de vuelos en **Vueling** y **Ryanair** (y en las aerolíneas que añadas), guarda todo el histórico en SQLite (o PostgreSQL / MySQL / MariaDB), dibuja gráficas de evolución por web y te avisa por **Discord** y/o **Telegram** con avisos enriquecidos (un **enlace o botón directo a cada fecha** y un calendario con los precios).

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

- **Red de rutas** (Ryanair, Wizz Air, Iberia Express): publica su red; se descarga y se mira si incluye el par de aeropuertos.
- **Pregunta por cada ruta** (Vueling, Binter): se le pregunta directamente (un 404 significa que no la opera).
- **Cualquier ruta** (un buscador que mire todas las aerolíneas): cubre cualquier ruta, directa o con escalas, con un máximo de pares de aeropuertos por vigilancia. Ninguno del catálogo lo usa ahora mismo.

La cobertura se guarda (`provider_routes`) y cada vigilancia sabe qué pares opera cada proveedor. **Cada lunes** se revalida: si una ruta de temporada se abre o se cierra, se avisa a los canales de la vigilancia, y mientras está cerrada ese proveedor no se consulta.

Todos los proveedores son **scripts de Python** que se ven, se editan, se prueban, se exportan y se importan desde **Proveedores** (ver «Añadir otra aerolínea»). Todos los que tenemos están en un solo paquete, [`app/providers/catalog/providers.fwp`](https://raw.githubusercontent.com/katarem/flight-watcher/main/app/providers/catalog/providers.fwp), que se importa desde **Proveedores → Importar** (sale como «Catálogo de Flight Watcher»; eliges cuáles) o pegando ese enlace en cualquier panel. Vueling y Ryanair se crean solos en el primer arranque y puedes cambiarlos o borrarlos como cualquier otro.

| Proveedor | Método | Estado |
|---|---|---|
| Vueling | API `apiw.vueling.com/api/v1/availability` | ✅ verificado el 2026-09-30 (~1 año en una petición) |
| Ryanair | API `ryanair.com/api/farfnd/v4/.../cheapestPerDay` + red de rutas del buscador | ✅ tarifas verificadas el 2026-09-30 (una petición por mes) |
| Wizz Air | API de wizzair.com (`/Api/asset/map` y `/Api/search/timetable`; la versión de la API sale de la portada) | ✅ verificado el 2026-10-12; necesita «Huella de Chrome» |
| Iberia Express | API del buscador de iberiaexpress.com (`/api/searchbar/calendarrealtime`, dos meses por petición, y su red de rutas) | ✅ verificado el 2026-10-12; necesita «Siempre Chrome». Trabaja por ciudades: en Tenerife (vuela a TFN y TFS) el precio se guarda como TCI |
| Binter | GraphQL de su web (`services.bintercanarias.com/main/graphql`: horarios, días operativos y calendario mensual) | ✅ verificado el 2026-10-12 sin medidas anti-bot; lento (de 3 a 15 s por consulta). Directos y, si la vigilancia admite escalas, conexiones |
| Air Europa | API de Amadeus de su motor de reservas (`api-des.aireuropa.com`, calendario de 31 días) | ⚠️ sin verificar desde el servidor; necesita «Siempre Chrome» y que pongas sus credenciales de cliente web (la cabecera del script explica de dónde salen) |

Rutas Sevilla ↔ Tenerife:

| Aerolínea | Rutas Sevilla ↔ Tenerife | Estado (2026-09-30) |
|---|---|---|
| Vueling | SVQ ↔ TFN directo, todo el año | ✅ |
| Ryanair | SVQ ↔ TFS directo, **estacional** (sin precios en invierno) | ✅ |
| Binter | SVQ ↔ TFN directo, 5 días/semana | ✅ en el catálogo desde el 2026-10-12 (el 2026-09-30, Cloudflare la bloqueaba) |
| Iberia | Solo con escala (Madrid) | ❌ sin proveedor (el 2026-09-30, 403 al navegador headless) |
| Air Europa | Solo con escala (Madrid) | ⚠️ en el catálogo desde el 2026-10-12, sin verificar desde el servidor |

Según Aena (2026-09-30), **no hay más aerolíneas directas**: SVQ ↔ TFN solo Vueling y Binter; SVQ ↔ TFS solo Ryanair.

Si una web bloquea, la comprobación falla con un mensaje claro («rechaza la consulta (HTTP 403, límite o anti-bot)») y te avisa. Por defecto las peticiones dicen que son de `flight-watcher`. Para las webs que bloquean, cada proveedor elige sus **«Medidas anti-bot»** (ver abajo).

### Medidas anti-bot

En el editor de cada proveedor, **Medidas anti-bot** tiene tres niveles:

- **Ninguna**: peticiones normales que dicen ser de `flight-watcher`. Lo más rápido; para las webs que no bloquean (Vueling, Ryanair).
- **Huella de Chrome y, si bloquean, Chrome**: lo que se describe a continuación.
- **Siempre Chrome**: todas las peticiones salen de Chrome de verdad, sin probar antes la huella. Para webs cuyo anti-bot solo deja pasar a su propio JavaScript (Imperva en Air Europa, que añade un token a cada petición). Es lo más lento y lo que más memoria gasta.

Con la huella de Chrome, sus peticiones se hacen pasar por las de una persona con Chrome:

- huella TLS y HTTP/2 de Chrome (`curl_cffi`), que es lo que miran Cloudflare, Akamai o DataDome además del User-Agent, y las cabeceras de Chrome en español (`Origin`, `Referer`, `Sec-Fetch-*`…);
- una sesión con cookies que dura 30 minutos, una visita previa a la portada de la web antes de su API y pausas más variables entre peticiones;
- si aun así la respuesta parece de un anti-bot (403/429 o su página de reto), la repite con `fetch()` desde **Chrome de verdad** abierto en la portada ([patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python), Playwright parcheado para que no se note la automatización), que resuelve los retos de JavaScript. Ese proveedor sigue con Chrome mientras dure la sesión y sus cookies se guardan en `DATA_DIR/navegador/`.

Chrome abre la portada del dominio de la API o, si el script la define, otra página con `BROWSER_PAGE = "https://…"`: hace falta cuando la API solo acepta peticiones desde una página concreta o el anti-bot solo corre en ella. Las peticiones se hacen desde esa página, así que pasan por lo que su script les añada; si la API no admite cookies desde ella (CORS), van sin cookies.

No resuelve CAPTCHA que pidan intervención ni arregla una IP ya bloqueada. En Docker, Chrome va «con ventana» en una pantalla virtual (Xvfb), que se parece más a una persona que el modo sin ventana; se cambia en **Ajustes → Modo sin ventana**. Úsalo solo con las webs que lo necesiten: es más lento y Chrome ocupa unos 300 MB de RAM mientras está abierto.

Para depurar: **Ajustes → Navegador y diagnóstico → Guardar capturas, HTML y JSON**, pulsa **Comprobar ahora** y abre **Diagnóstico** (en los proveedores por API se guarda la respuesta JSON de cada petición).

Si alguna vigilancia antigua tenía `iberia` marcada, se ignora al comprobar; al editarla y guardarla desaparece.

> Ejecútalo desde una IP residencial: las aerolíneas suelen bloquear IPs de centros de datos.

### Prueba de acceso (Proveedores)

Los administradores tienen el apartado **Proveedores**, una especie de *healthcheck*: por cada proveedor, desde la IP del servidor, comprueba la cobertura (red de rutas o pregunta directa) y los precios de un mes de una ruta (la suya de prueba o la que indiques), y dice si es **accesible**, si **nos bloquea** (403/429/anti-bot), si **falla** o si **no responde**, con el código HTTP y el tiempo de cada paso. Un proveedor lento no se da por perdido mientras siga avanzando: la prueba solo se corta si pasa minuto y medio sin ninguna petición ni mensaje (más su pausa entre peticiones) o, en cualquier caso, a los 10 minutos. Guarda el último resultado de cada uno. También prueba el cambio de divisas del BCE y permite **revalidar las rutas** de todas las vigilancias en el momento.

### Escalas y monedas

Cada vigilancia tiene un **máximo de escalas** (solo directos por defecto). Vueling, Ryanair, Wizz Air e Iberia Express solo venden sus vuelos directos; Air Europa (casi siempre vía Madrid) y Binter (vía sus aeropuertos de Canarias) también los que tienen escala. Cada precio guarda sus escalas.

Los precios se guardan en su **moneda original** y con su **equivalente en euros** según el tipo de referencia diario del **BCE** (Wizz Air cobra en la moneda del aeropuerto de salida). Las reglas de aviso, las gráficas y el calendario usan los euros; los avisos muestran también la moneda original.

## Enlaces con las fechas elegidas

Cada precio del panel y cada aviso lleva un enlace a esa fecha concreta, con la **plantilla de enlace** de cada proveedor (se cambia en su editor; marcadores `{origin} {destination} {date} {date_dmy} {year} {month} {day}`). Si venías de una versión anterior, las plantillas que tuvieras en Ajustes pasan solas a su proveedor.

- **Vueling:** usa el formato oficial de deeplink (`o`, `d`, `dd` obligatorios):
  `https://tickets.vueling.com/booking?o={origin}&d={destination}&dd={date}&adt=1&chd=0&inf=0&c=es-ES&cur=EUR`.
  Residentes en islas o Ceuta pueden añadir `&dt=1` a la plantilla de Vueling.
- **Ryanair:** `https://www.ryanair.com/es/es/trip/flights/select?...&dateOut={date}&isReturn=false&originIata={origin}&destinationIata={destination}`.
- **Wizz Air:** `https://wizzair.com/es-es/booking/select-flight/{origin}/{destination}/{date}/null/1/0/0/null`.
- **Iberia Express:** `https://booking.iberiaexpress.com/?triptype=OW&from={origin}&to={destination}&depdate={date}&retdate={date}&exactdates=0&adt=1&chd=0&inf=0`.

## Reglas de aviso

Por cada vigilancia y web se avisa de una fecha si:

- su precio es **≤ el precio máximo** que definas, **o**
- es un **X % inferior a lo habitual** (mediana de los precios guardados de esa ruta y web; se activa con las *muestras mínimas* de Ajustes, 30 por defecto).

No se repite el aviso de la misma fecha salvo que el precio baje aún más. Si no hay ningún canal configurado, los avisos no se marcan como enviados y se mandarán cuando lo configures.

### Cómo se ven los avisos

Cada aviso es un mensaje **enriquecido**, no un texto suelto:

- **Discord:** un *embed* de cabecera con la vigilancia (enlazada al panel) y uno por web, **con el color de esa web**, con **un campo por fecha**: el precio enlaza directamente a esa fecha en la web, y al lado van las escalas, la moneda original y las horas de salida y llegada si la web las da.
- **Telegram:** el resumen en el texto y **un botón por fecha** que abre esa fecha en la web (más uno para abrir el panel), en lugar de enlaces sueltos en el texto. Si Telegram no acepta algún enlace como botón (por ejemplo, la URL del panel en la red local), el aviso se repite con los enlaces en el texto.
- **Calendario en PNG** en los dos: los meses del aviso con el precio más bajo de cada día, del más barato (verde) al más caro (rojo), y con borde los días de los que avisa. En los viajes, el total más barato de cada fecha de ida.

**Perfil → Canales de aviso → Probar** manda un aviso de ejemplo con este mismo formato (precios inventados).

Puedes limitar cada vigilancia a un rango de fechas; sin límites se comprueban todas las que tengan precio desde hoy.

## Viajes de ida y vuelta

Un **viaje** junta dos de tus vigilancias (la de ida y la de vuelta) con un rango de noches (p. ej. de 3 a 5) y, opcionalmente, una ventana de fechas de ida. No consulta ninguna web por su cuenta: usa los precios de la última comprobación de cada tramo, así que se recalcula solo cuando se comprueba alguna de sus vigilancias.

Para cada fecha de ida y cada número de noches permitido, el total es el vuelo de ida más barato de ese día más el de vuelta más barato del día de regreso (entre todas las webs de cada vigilancia, en euros). Se avisa si el **total ≤ el máximo** que marques **o** si es un **X % inferior a lo habitual** (mediana de los totales guardados de ese viaje). Para no llenarte de mensajes, cada ronda avisa solo de las **5 fechas de ida más baratas** que cumplen una regla, con las fechas, las noches y un enlace por tramo, y de cada fecha una sola vez (salvo que baje más).

Los precios de un tramo con más de 3 días no cuentan (p. ej. si su vigilancia está en pausa o la web ha dejado de responder). Borrar una vigilancia borra los viajes que la usan.

## Panel

Aplicación React (carpeta `frontend/`) que habla con la API JSON del servidor (`/api/v1`). Tema claro u oscuro (sigue al sistema o se elige en el menú de usuario), pensado para móvil y accesible (navegable con teclado, revisado con axe contra WCAG 2.1 AA).

- **Panel:** el resumen de cada apartado (cuántas vigilancias y viajes, cuántos con chollo y desde cuánto), los **chollos de ahora mismo** y los últimos avisos y ejecuciones.
- **Vuelos** (`/flights`): cada vigilancia de vuelos con el mejor precio actual por web, enlace a esa fecha, etiqueta *chollo*, errores y minigráfica de tendencia. Cada transporte tendrá su apartado (barcos, trenes y buses llegarán en la 3.x); los enlaces antiguos (`/watches/…`, los de los avisos ya enviados) llevan al apartado de su vigilancia.
- **Detalle de una vigilancia:**
  - **Calendario de precios** de la última comprobación: color según lo barato que sale cada día, borde para los chollos, filtro por web. Pulsar un precio abre esa fecha en la web; pulsar el día muestra su historial. Si la web da la hora de salida y de llegada, salen con el precio.
  - Gráficas de la **evolución del precio mínimo** por web, del **precio actual por fecha de vuelo** y del **historial de una fecha concreta**.
  - Historial de comprobaciones y avisos enviados.
- **Viajes:** el viaje más barato ahora con el enlace de cada tramo, las combinaciones más baratas, todas las noches de una fecha de ida y la evolución del total. Desde el formulario de un viaje se puede crear la vigilancia de vuelta que falte.
- **Ejecuciones** y **Diagnóstico** para ver qué pasó en cada comprobación.
- **Proveedores** (administradores): la lista de proveedores, **agrupada y filtrable por tipo** (vuelos, y más adelante barcos, trenes…), con su prueba de acceso (ver «Prueba de acceso» arriba), su editor con consola, importar y exportar (ver «Añadir otra aerolínea»).

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

Cada proveedor es un script de Python guardado en la base de datos. En **Proveedores → Nuevo proveedor** (solo administradores) se escribe uno que cumple el contrato:

```python
def network(api, origin):                # cobertura «Red de rutas publicada»
    data = api.get_json(f"https://www.ejemplo.com/api/rutas/{origin}")
    return [] if data is None else [r["destino"] for r in data]


def fetch_route(api, origin, destination, start, max_months):
    out = {}
    for i in range(max_months):
        data = api.get_json(f"https://www.ejemplo.com/api/precios/{origin}/{destination}",
                            mes=add_months(start, i).strftime("%Y-%m"))
        if data is None:                 # 404: no opera la ruta
            break
        for dia in data["dias"]:
            out[date.fromisoformat(dia["fecha"])] = dia["precio"]          # en euros
            # o DayPrice(día, precio, currency="GBP", stops=1) con otra moneda o con escalas,
            # y departure="06:35", arrival="08:10" si la web da las horas
    return out
```

- Cada proveedor es de un **tipo** (hoy, *Vuelos*): solo sale en las vigilancias de ese transporte. Barcos, trenes y buses comparten este mismo contrato (con estaciones, puertos o paradas en vez de aeropuertos), así que ya se pueden escribir y probar aunque sus vigilancias lleguen en la 3.x. El tipo viaja en el `.fwp`; los paquetes antiguos se importan como vuelos.
- `DayPrice` admite la **hora de salida y de llegada** (`departure=`, `arrival=`: `"06:35"`, un `time` o un `datetime`; una llegada anterior a la salida es del día siguiente). Se guardan con el precio y salen en el panel y en los avisos. Ryanair las da siempre y Wizz Air la de salida cuando ese día hay un solo vuelo.
- Opcional: `BROWSER_PAGE = "https://…"`, la página que abre Chrome cuando sus peticiones van por él (ver «Medidas anti-bot»).
- `fetch_route` devuelve `{fecha: precio}`, `{fecha: DayPrice}` o una lista de `DayPrice` (`{}` si no opera la ruta). Si además acepta `max_stops=None`, recibe el máximo de escalas de la vigilancia y filtra él mismo (como Air Europa). Con la cobertura «Pregunta por cada ruta» hay que definir `probe(api, origin, destination)` → `True`/`False`; con «Cualquier ruta», nada más.
- `api.get_json`, `api.post_json` y `api.request` respetan el turno y las pausas del proveedor, convierten 403/429/anti-bot en «bloqueado» y un 404 en `None`, y guardan la respuesta en Diagnóstico si está activo. Una petición que no responde en 30 s se repite una vez; para una web lenta, pasa `timeout=` en segundos (`api.post_json(url, cuerpo, timeout=60)`). `api.get_json` y `api.post_json` aceptan también `headers=` (cabeceras de esa petición).
- `api.cookie("NOMBRE")` da el valor de una cookie de la sesión (o `None`), para las webs que exigen copiarla en una cabecera (el token XSRF de Iberia Express, por ejemplo). Con las peticiones por Chrome la lee de Chrome, en la misma página desde la que pide; con la huella de Chrome, tras visitar la portada de `url=` si se indica. `api.log(...)` y `print(...)` escriben en el log del servidor y en la consola de la prueba.
- **Probar el script** lo carga y hace la prueba de acceso sin guardar nada. Encima del código se abre una **consola** que cuenta en directo cada paso, cada petición (URL, estado, tiempo, tamaño y forma del JSON recibido), los mensajes del script y, si falla, la línea del script con su código. Debajo, una muestra de los precios.
- Al guardarlo activo aparece en todo el panel. Desactivado no se carga; al eliminarlo se quita de las vigilancias y sus precios se conservan como histórico.
- Los scripts de Vueling y Ryanair (en **Editar**) son buenos ejemplos de verdad.

### Importar y exportar

- **Exportar**: en **Proveedores** elige los que quieras (o todos) y descarga un archivo `.fwp`; también desde el editor de cada uno.
- **Importar** (**Proveedores → Importar**): desde un **enlace** (por ejemplo, un `.fwp` en GitHub; un enlace `…/blob/…` se cambia solo por el del archivo en bruto) o desde un **archivo**. Antes de importar se ve qué trae cada proveedor (nuevo, igual que el guardado o qué cambia), su código y si algo no se podría importar. Uno con la misma clave que uno guardado lo sustituye (se conservan sus vigilancias e histórico). Se guarda de qué enlace vino, para volver a usarlo.
- El formato `.fwp` es texto: una línea de cabecera y, por proveedor, una línea con sus datos en JSON seguida del script **tal cual**. Ocupa lo mismo que un JSON (lo grande es el código), pero el script se puede leer y comparar antes de importarlo. Todos los proveedores que tenemos están en [`app/providers/catalog/providers.fwp`](https://raw.githubusercontent.com/katarem/flight-watcher/main/app/providers/catalog/providers.fwp) (los antiguos `incluidos.fwp` y `sin-verificar.fwp` llevan ahora a ese archivo).

**Ojo:** el script se ejecuta dentro del servidor con todos sus permisos (puede leer la base de datos y los secretos de los canales). Por eso solo lo escriben o importan administradores, hay que confirmar la contraseña para probarlo, importarlo y para guardarlo si cambia el código o se activa, y se anota quién lo guardó. Con `PROVIDER_SCRIPTS=0` los proveedores que hay siguen funcionando, pero desde el panel no se puede crear, importar, cambiar el código ni probar ninguno.

Para añadir otra ciudad (como `TCI`) o un grupo (como `canarias`), añádelo a `CITIES` o `GROUPS` en `app/places.py`. Los lugares de otros transportes (estaciones, puertos y paradas de bus) van en `app/data/stations.csv`, `ports.csv` y `stops.csv` (código de 4 a 10 letras o cifras, nombre, ciudad, `city_code` = la ciudad de `CITIES` que los agrupa, país y otras palabras para buscarlos); hoy solo tienen la cabecera: se llenarán con sus transportes.

## Seguridad

- El acceso es con usuario y contraseña (sesión por cookie firmada, `SameSite=Lax`; además, toda petición que cambia algo exige la cabecera `X-Requested-With`, que un formulario de otra web no puede enviar). Las contraseñas se guardan con scrypt; cambiarla cierra las demás sesiones y varios fallos seguidos bloquean el inicio de sesión unos minutos. Si publicas el panel, ponlo tras HTTPS y define `COOKIE_SECURE=1`.
- Los webhooks y tokens de los canales se guardan en la base de datos en texto plano (JSON): protege la BD y su copia de seguridad.
- Solo se aceptan webhooks de Discord con la URL oficial y los campos secretos nunca se devuelven al navegador.
- Los proveedores ejecutan código Python en el servidor: solo un administrador puede escribirlos o importarlos, y hace falta su contraseña para probarlos, importarlos o activarlos. Importa solo paquetes de quien te fíes. Para que nadie pueda cambiar el código desde el panel, usa `PROVIDER_SCRIPTS=0`.
- Respeta los términos de uso de cada aerolínea; una comprobación al día es una frecuencia razonable. Las medidas anti-bot pueden ir contra los términos de algunas webs: actívalas solo si te hacen falta y bajo tu responsabilidad.

## Estructura

```
app/
  __init__.py     versión (__version__)
  main.py         servidor: API, avatares, protección CSRF y el panel compilado (app/web)
  api/            API JSON /api/v1: sesión, vigilancias, viajes, perfil y canales, administración, proveedores
  auth.py         contraseñas (scrypt), validación de usuarios y freno de intentos de login
  avatars.py      guardado y validación de avatares
  checker.py      ronda de comprobaciones + reglas de aviso
  trips.py        viajes de ida y vuelta: combinaciones, histórico y avisos
  coverage.py     cobertura de rutas por proveedor, comprobación al crear y revalidación semanal
  health.py       prueba de acceso a los proveedores (zona Proveedores)
  places.py       catálogo de lugares: aeropuertos, estaciones, puertos y paradas; ciudades, países y grupos (app/data)
  fx.py           cambio de divisas a euros (BCE)
  scheduler.py    planificación (se cambia desde Ajustes)
  notify.py       avisos enriquecidos: el mensaje estructurado y cómo lo pinta cada tipo de canal (Discord / Telegram)
  images.py       calendario resumen en PNG para los avisos (Pillow)
  kinds.py        tipos de transporte y de proveedor (vuelos; barcos, trenes, buses y alojamiento, más adelante)
  db.py           acceso a datos (SQLAlchemy Core: SQLite, PostgreSQL, MySQL, MariaDB)
  migrations/     migraciones de Alembic
  providers/      base.py (abstracción), extract.py, scripted.py (contrato, carga y registro de los scripts),
                  bundle.py (formato .fwp para importar y exportar), stealth.py y browser.py (medidas anti-bot y
                  Chrome con patchright) y catalog/providers.fwp (todos los proveedores)
scripts/          build_places.py (regenera el catálogo de aeropuertos desde OurAirports)
frontend/         panel React + Vite + TypeScript (src/pages, src/components, src/api) y pruebas e2e
tests/
  smoke_test.py         extremo a extremo con datos simulados (sin red)
  migration_test.py     migraciones sobre una BD con datos
  browser_mock_test.py  Playwright real contra una web simulada
  e2e_server.py         servidor con datos simulados para las pruebas del panel
```

Pruebas de Python (necesitan además `pip install httpx`): `python -m tests.smoke_test`, `python -m tests.migration_test` y `python -m tests.browser_mock_test` (esta última necesita Chromium, `patchright install chromium`; con uno propio: `FW_CHROMIUM=/ruta/chromium`). Las del panel, en «Desarrollo del panel».

## Limitaciones conocidas

- Solo ida por vigilancia: para ida y vuelta, crea dos vigilancias y júntalas en un viaje.
- Los viajes no tienen en cuenta horarios: cuentan noches por fecha de vuelo (las horas se guardan cuando la web las da, para poder usarlas más adelante).
- Los precios del calendario son «desde» y no incluyen equipaje facturado.
- La regla «habitual» compara con la mediana de la ruta, no con la de esa misma fecha.
