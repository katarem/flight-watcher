# Cambios

## 2.0.0 — 2026-10-15

El **viaje** pasa a ser lo que creas y gestionas, y las vigilancias, sus **tramos** internos. Es un cambio de modelo (de ahí la versión mayor): la API ya no gestiona vigilancias sueltas y los avisos son por viaje. Así el alojamiento entrará en la 2.1 como un tramo más (ver el [ROADMAP](ROADMAP.md)).

### Cambiado
- **Todo vive en los viajes.** Un viaje tiene su tramo de ida y, si quieres, el de vuelta: un «solo ida» es un viaje sin vuelta (una combinación por fecha, sin noches). Los tramos se crean, editan y borran desde el formulario del viaje, cada uno con su ruta, sus webs (con la comprobación de la ruta) y sus escalas; el botón **Al revés que la ida** rellena la vuelta. Borrar un viaje borra sus tramos y su histórico; pasarlo a solo ida borra la vuelta.
- **Reglas y avisos por viaje**: el precio máximo, el descuento, la ventana de fechas y los canales son del viaje (sobre el total, o sobre la ida en un solo ida). Ya no hay avisos por tramo; los de cambios de rutas van a los canales del viaje.
- **Panel**: el resumen de inicio es de tus viajes (cuántos hay, cuántos tienen chollo y el más barato ahora), con los chollos de ahora (la mejor combinación de cada viaje que cumple sus reglas) y los últimos avisos de tus viajes. Desaparece el apartado **Vuelos**: cada tramo tiene su detalle (calendario, gráficas e historial) dentro de su viaje, en `/trips/{viaje}/legs/{tramo}`.
- Las ejecuciones dicen de qué viaje y de qué tramo son, y la lista de usuarios cuenta sus viajes.
- Los enlaces antiguos siguen funcionando: `/watches/{id}` (los de los avisos ya enviados) y `/flights/{id}` llevan al tramo dentro de su viaje, sus `…/edit` al formulario del viaje, y `/watches/new?origin=…&destination=…` a un viaje nuevo con esa ida y la vuelta al revés.
- Migración `0009`: `watches.trip_id` y `watches.role` (ida o vuelta); `trips` deja `outbound_id`/`return_id`. Las vigilancias sueltas pasan a ser viajes de solo ida (con su precio máximo y sus canales), y los tramos que compartían varios viajes se duplican sin perder su histórico.
- Las bases de datos anteriores a los usuarios también se actualizan: sus vigilancias (sin dueño) pasan a viajes que el administrador recibe al arrancar.

### Quitado
- La API ya no tiene el CRUD suelto de `/watches` (se crean y editan dentro de `/trips`); queda el detalle de un tramo con sus gráficas. `/alerts` devuelve ahora los avisos de los viajes.

## 1.9.0 — 2026-10-13

Primera versión como **Trip Watch** (antes Flight Watcher). Prepara el terreno para otros transportes y el alojamiento: lo que daba por hecho que todo eran vuelos ahora tiene tipo.

### Añadido
- **Avisos enriquecidos.** Cada aviso se arma como un mensaje estructurado (título, una sección por web, un elemento por fecha con su enlace, enlaces generales e imagen) y cada canal lo pinta a su manera:
  - **Discord:** *embeds* con el color de cada web, un campo por fecha con el precio enlazado a esa fecha (y las escalas, la moneda original y las horas) y la cabecera enlazada al panel.
  - **Telegram:** **botones con enlace** (uno por fecha, uno por tramo en los viajes y otro para abrir el panel) en lugar de enlaces en el texto. Si Telegram rechaza algún enlace como botón (la URL del panel en la red local, por ejemplo), el aviso se repite con los enlaces en el texto.
  - **Calendario resumen en PNG** adjunto en los dos: los meses del aviso con el precio más bajo de cada día (del verde al rojo, como el calendario del panel) y con borde los días avisados; en los viajes, el total por fecha de ida.
  - Los avisos de problemas de la ronda y de cambios de rutas también salen con formato, y **Probar** un canal manda un aviso de ejemplo con el formato de verdad.
- **Horas en los precios**: un proveedor puede devolver la hora de salida y de llegada (`DayPrice(…, departure="06:35", arrival="08:10")`). Se guardan con cada precio y salen en el calendario, en las tarjetas, en los viajes, en la prueba del editor y en los avisos («06:35–08:10», «22:40–00:15 (+1)»). Ryanair las trae siempre y Wizz Air la de salida si ese día hay un solo vuelo (sin verificar aún contra la web real; se actualizan al importarlos de nuevo desde el catálogo).
- **Tipos de proveedor**: cada proveedor es de un tipo (hoy, *Vuelos*; barcos, trenes y buses comparten contrato y ya se pueden escribir y probar). Se elige en su editor, viaja en los `.fwp` (los paquetes anteriores se importan como vuelos) y la zona **Proveedores** los agrupa y filtra por tipo. Un proveedor solo sale en las vigilancias de su transporte.
- **Lugares genéricos**: además de aeropuertos, el catálogo admite estaciones, puertos y paradas de bus (`app/data/stations.csv`, `ports.csv` y `stops.csv`, vacíos hasta que lleguen sus transportes), y la **ciudad** es el nodo común que los agrupa. El autocompletado solo ofrece lugares del transporte de la vigilancia (en una de vuelos, nada sin aeropuerto).
- **Panel por apartados**: el **Panel** pasa a ser un resumen (cada apartado con sus vigilancias, chollos y mejor precio, los chollos de ahora mismo y los últimos avisos y ejecuciones) y las vigilancias de vuelos tienen su apartado, **Vuelos** (`/flights`).
- Migración `0008`: `watches.kind` y `provider_scripts.kind` (todo lo anterior queda como vuelos), `prices.departs_at`/`arrives_at`, y los códigos de lugar de precios, caché de rutas y ruta de prueba pasan de 3 a 10 caracteres.

### Cambiado
- **El proyecto pasa a llamarse Trip Watch** (antes Flight Watcher), porque deja de ser solo de vuelos. La imagen es ahora `ghcr.io/katarem/trip-watch` y el servicio y el contenedor del `docker-compose.yml`, `trip-watch`: al actualizar, coge el compose nuevo (o cambia la imagen en el tuyo) y arranca con `docker compose pull && docker compose up -d --remove-orphans` (quita el contenedor `flight-watcher`, que si no ocuparía el puerto). Tus datos no cambian: la base de datos conserva su nombre (`flight_watcher`). Los enlaces del catálogo con el nombre anterior siguen funcionando y los `.fwp` mantienen su cabecera para que los entiendan los paneles anteriores.
- Las vigilancias viven en `/flights/{id}`. Los enlaces antiguos (`/watches/{id}`, también los de los avisos ya enviados) llevan a su vigilancia en el apartado nuevo, y los avisos nuevos enlazan ya ahí.
- La imagen Docker trae Pillow y las fuentes DejaVu (para el calendario de los avisos).

## 1.8.2 — 2026-10-12

### Añadido
- **Iberia Express** en el catálogo (verificado contra la web real): calendario de su buscador, dos meses por petición, y su red de rutas. Necesita «Siempre Chrome» (Imperva y un token XSRF). La web trabaja por ciudades: en Tenerife, donde vuela a TFN y a TFS, el precio se guarda como TCI porque el calendario no dice a qué aeropuerto va.
- **Binter** en el catálogo (verificado contra la web real, sin medidas anti-bot): directos y, si la vigilancia admite escalas, conexiones. Su GraphQL es lento (de 3 a 15 s por consulta); con «solo directos» no pide el calendario de conexiones.
- Los scripts pueden leer una cookie de la sesión con `api.cookie("NOMBRE")` (de Chrome si las peticiones van por él), para las webs que piden copiarla en una cabecera (XSRF/CSRF), y mandar cabeceras propias con `headers=` en `api.get_json` y `api.post_json`.

### Corregido
- **Wizz Air** (catálogo): su web ya no tiene `/buildnumber`; la versión de la API sale ahora de la portada. Viene con «Huella de Chrome» (la portada rechaza a quien no parece un navegador). Verificado contra la web real; se actualiza al importarlo de nuevo desde el catálogo.

### Cambiado
- Al crear o editar una vigilancia, la comprobación de qué webs operan la ruta ya no se corta a los 25 s: espera a todas, porque hay webs lentas (Binter, o las que van por Chrome) que sí la operan pero tardan.

### Quitado
- **Google Flights** sale del catálogo: Google firma cada petición de su calendario con un token de BotGuard que solo genera su JavaScript en el navegador, sobre el cuerpo exacto de esa petición. Si lo tenías importado, bórralo en **Proveedores**.

## 1.8.1 — 2026-10-12

### Corregido
- Con las peticiones desde Chrome, si la página navega sola justo cuando se pide algo (el reto del anti-bot que se recarga, una redirección como la del motor de reservas de Air Europa), ya no falla con «Execution context was destroyed»: espera a que la página se asiente y repite la petición (hasta 3 veces), y la consola de la prueba lo dice.
- Una página que ya parecía cargada pero redirige con JavaScript a la buena (la intermedia aún no tiene el script del anti-bot) daba «Failed to fetch». Ahora Chrome espera a que la URL deje de cambiar antes de pedir nada.
- Air Europa (catálogo): Chrome abre directamente la página final del motor de reservas (`/booking/recovery`), donde el anti-bot ya está listo. Probado desde el servidor de un usuario: el token y el calendario responden; se actualiza al importarlo de nuevo desde el catálogo.

## 1.8.0 — 2026-10-12

### Cambiado
- El interruptor «Aplicar medidas anti-bot» pasa a ser un selector **«Medidas anti-bot»** con tres niveles: **Ninguna**, **Huella de Chrome y, si bloquean, Chrome** (lo que hacía el interruptor) y **Siempre Chrome** (nuevo: todas las peticiones salen de Chrome de verdad, sin probar antes la huella; más lento, pero es lo único que vale con anti-bots que exigen algo que solo genera su JavaScript en cada petición, como Imperva). Los proveedores que lo tenían activado siguen igual y los paquetes `.fwp` antiguos (`true`/`false`) se importan bien.

### Añadido
- Un script puede decir qué página tiene que abrir Chrome con `BROWSER_PAGE = "https://…"` (si no, la portada del dominio de la API, como antes). Hace falta cuando la API solo acepta peticiones desde otra página o el anti-bot solo corre en ella. La consola de la prueba dice qué nivel se aplica y desde qué página.
- **Un solo catálogo**: todos los proveedores que tenemos (Vueling, Ryanair, Wizz Air, Google Flights y Air Europa) están en `app/providers/catalog/providers.fwp`, que se importa desde GitHub (en **Importar** sale como «Catálogo de Flight Watcher» y eliges cuáles). Sustituye a `incluidos.fwp` y `sin-verificar.fwp`: sus enlaces, también los ya guardados como origen de un proveedor, llevan ahora a `providers.fwp`.
- **Air Europa** en el catálogo (sin verificar desde el servidor): precios por día de la API de Amadeus que usa su motor de reservas, 31 días por petición, con escalas (casi siempre vía Madrid). Va con «Siempre Chrome»; hay que rellenar en el editor sus credenciales de cliente web (la cabecera del script explica de dónde salen). Se ofrece al importar, junto a los otros paquetes del catálogo de GitHub.

### Corregido
- Las peticiones desde Chrome se hacen en el contexto de la propia página (patchright las aislaba): así pasan por lo que el script de la web les añade, como el token del anti-bot.
- Si la API no admite cookies desde la página (CORS sin `Access-Control-Allow-Credentials`), la petición desde Chrome se repite sin ellas en vez de fallar con «Failed to fetch».

## 1.7.2 — 2026-10-11

### Corregido
- Una sola petición que tardaba más de 30 s (algo puntual en webs lentas como Binter) daba «Sin respuesta» a todo el paso aunque las demás fueran bien. Ahora **se repite una vez**; solo si tampoco responde la segunda vez es «sin respuesta», y el mensaje dice cuánto se esperó («no ha respondido en 30 s»).

### Añadido
- Los scripts pueden esperar más a una web lenta: `timeout=` en segundos en `api.get_json`, `api.post_json` y `api.request` (30 por defecto). La prueba de acceso no da por colgado a un proveedor mientras su petición está dentro de ese tiempo.

## 1.7.1 — 2026-10-11

### Corregido
- La **prueba de acceso** (la de la lista de Proveedores y la del editor) ya no da «Sin respuesta» a un proveedor lento que sigue respondiendo: antes se cortaba al minuto aunque cada petición fuera bien. Ahora solo se corta si pasa **minuto y medio sin ninguna señal de vida** (petición, traza de la consola o `api.log`/`print`), más la pausa entre peticiones del proveedor, con un tope de 10 minutos en total.
- Al cortarse, el resultado conserva los pasos que ya habían terminado y dice en cuál se quedó, y el script de la prueba del editor deja de hacer peticiones (antes seguía en segundo plano).

## 1.7.0 — 2026-10-11

### Cambiado
- **Un solo tipo de proveedor**: ya no hay proveedores «de serie», «en estudio» y «propios». Todos son scripts de Python que se ven, editan, prueban, exportan, importan o borran desde **Proveedores**, en una única lista.
- **Vueling y Ryanair pasan a ser scripts** (`app/providers/catalog/incluidos.fwp`): se crean solos la primera vez que arranca esta versión, con la misma clave, así que las vigilancias, el histórico y los avisos siguen igual. **Wizz Air y Google Flights** (sin verificar) quedan en un paquete aparte (`sin-verificar.fwp`) que se importa con un clic; si alguna vigilancia ya los usaba, se crean también al actualizar.
- La **plantilla de enlace** es parte de cada proveedor (se edita en su editor). Las que hubiera en Ajustes pasan solas a su proveedor y desaparecen de Ajustes.
- `PROVIDER_SCRIPTS=0` ya no desactiva los proveedores (ahora todos son scripts): los que hay siguen funcionando, pero desde el panel no se puede crear, importar, cambiar el código ni probar ninguno.
- La API de proveedores queda en `/api/v1/providers` (lista, `/{clave}`, `/test`, `/health`, `/export`, `/import`, `/import/preview`, `/revalidate`); desaparece `/providers/scripts`.
- Si `fetch_route` acepta `max_stops`, el script recibe el máximo de escalas de la vigilancia y filtra él mismo (lo usa Google Flights).
- **patchright sustituye a Playwright** (misma API, parcheado para que no se note que el navegador está automatizado). La imagen Docker trae Google Chrome y Xvfb, una pantalla virtual: Chrome puede ir «con ventana» sin monitor. «Modo sin ventana» pasa a estar desactivado por defecto; sin pantalla (fuera de Docker) se abre sin ventana igualmente.

### Añadido
- **Importar proveedores** desde un enlace (un `…/blob/…` de GitHub se cambia por el archivo en bruto) o desde un archivo, con vista previa: qué trae, si es nuevo, igual o qué cambia respecto al guardado, el código de cada uno y lo que no se podría importar. Pide la contraseña, importa todo o nada y recuerda de qué enlace vino cada proveedor.
- **Exportar** los proveedores elegidos o todos (también uno desde su editor) en un archivo `.fwp`: texto con una línea de datos en JSON por proveedor y el script tal cual debajo, para poder leerlo y compararlo antes de importarlo.
- Interruptor **«Aplicar medidas anti-bot»** en cada proveedor: sus peticiones se hacen pasar por las de una persona con Chrome (huella TLS y HTTP/2 de Chrome con `curl_cffi`, sus cabeceras en español, una sesión con cookies que dura 30 minutos, visita previa a la portada y pausas más variables). Si aun así una respuesta parece de un anti-bot, la repite con `fetch()` desde Chrome de verdad abierto en la portada (patchright), que resuelve los retos de JavaScript, y sigue con Chrome mientras dure la sesión; sus cookies se guardan para la próxima vez. No resuelve CAPTCHA que pidan intervención. Viaja en los paquetes `.fwp`.
- **Consola de la prueba** encima del código en el editor: cuenta en directo (streaming) cada paso, cada petición con su URL, estado, tiempo, tamaño y forma del JSON, los `api.log`/`print` del script y, si falla, la línea del script con su código. Se puede copiar.
- Migración `0007` (solo columnas nuevas: `provider_scripts.source` y `provider_scripts.stealth`).

### Quitado
- Las «aerolíneas en estudio» (Volotea, easyJet e Iberia) y la prueba de su portada.
- Los proveedores escritos como clases de Python en `app/providers/` (vueling.py, ryanair.py, wizzair.py, google.py).

## 1.6.0 — 2026-10-10

### Añadido
- **Proveedores propios** (solo administradores): añadir una aerolínea sin tocar el código de la aplicación, desde **Proveedores → Nuevo proveedor**. Se escribe un script de Python que cumple el contrato de proveedor (`fetch_route` y, según la cobertura, `network` o `probe`), con nombre, color, cobertura, ruta de prueba, pausa entre peticiones y plantilla de enlace. Sus peticiones van por el mismo turno que las de los proveedores de serie (una a la vez, pausas, 403/429/anti-bot = bloqueado, copia en Diagnóstico).
- **Probar sin guardar**: carga el script del formulario y hace la prueba de acceso (cobertura y precios de un mes) desde la IP del servidor, con una muestra de los precios, los mensajes de `api.log` y, si falla, el error con la línea del script.
- Un proveedor propio activo aparece solo en los formularios, la comprobación de rutas, las rondas, las gráficas, los avisos, la zona Proveedores y las plantillas de enlace de Ajustes. Si una aerolínea en estudio pasa a tener proveedor propio, deja de salir «en estudio».
- Migración `0006` (solo una tabla nueva: `provider_scripts`).

### Seguridad
- El script se ejecuta en el servidor con sus mismos permisos. Para probarlo, y para guardarlo si cambia el código o se activa, hay que confirmar la contraseña (con freno tras varios fallos); se anota quién lo guardó y el log registra cada cambio. `PROVIDER_SCRIPTS=0` los desactiva todos (ni se cargan).
- Un script que deja de cargar (error de sintaxis, una importación que falta…) no tumba el servidor: se marca con su error y no se usa.

## 1.5.0 — 2026-10-10

### Añadido
- **Viajes de ida y vuelta** (`/trips`): juntan una vigilancia de ida y otra de vuelta con un rango de noches y una ventana de fechas de ida opcional. Para cada fecha de ida y cada número de noches, el total es el vuelo de ida más barato más el de vuelta más barato (entre todas las webs de cada tramo, en euros), sin hacer peticiones nuevas a las webs.
- Avisos de viajes por el **total**: precio máximo o un % por debajo de lo habitual (mediana de los totales guardados del viaje). Cada ronda avisa solo de las 5 fechas de ida más baratas, con las fechas, las noches y un enlace por tramo, y de cada fecha una sola vez (salvo que baje). Canales propios por viaje.
- Panel: lista de viajes con el más barato ahora, detalle con las combinaciones más baratas, todas las noches de una fecha de ida, el total por fecha de ida y su evolución, y formulario que propone la vigilancia de vuelta (o ayuda a crearla y vuelve al viaje).
- El detalle de una vigilancia indica de qué viajes es tramo, y al borrarla se avisa de que se borran con ella.
- Migración `0005` (solo tablas nuevas: `trips`, `trip_channels`, `trip_quotes`, `trip_alerts`).

### Corregido
- El texto del tooltip de las gráficas usa el color del tema: el de algunas webs no daba el contraste mínimo (WCAG AA).

## 1.4.0 — 2026-10-10

### Añadido
- **Origen y destino con autocompletado**: aeropuertos de OurAirports (dominio público, solo con vuelos regulares), ciudades con varios aeropuertos (`TCI`, `LON`, `PAR`…), países (`ES`, `PT`…) y grupos propios (`canarias`, `baleares`, `andalucia`…). Endpoint `GET /api/v1/places`.
- **Cobertura por proveedor**: cada uno declara si publica su red de rutas (Ryanair, Wizz Air), si hay que preguntarle por cada ruta (Vueling) o si cubre cualquiera (Google Flights). Se guarda en caché (`provider_routes`).
- **Comprobación de la ruta al crear o editar** (`POST /api/v1/route-check`): consulta los proveedores en paralelo, con tiempo límite por proveedor, y el formulario muestra cuáles la operan y por qué los demás no.
- **Revalidación semanal** (los lunes) de la cobertura de cada vigilancia, con aviso si una ruta de temporada se abre o se cierra. Mientras está cerrada, ese proveedor no se consulta.
- **Escalas**: cada precio guarda sus escalas y cada vigilancia tiene un «máx. escalas» (solo directos por defecto).
- **Monedas**: cada precio se guarda en su moneda original y en euros con el cambio de referencia del BCE.
- Proveedores nuevos: **Wizz Air** y **Google Flights** (sin verificar todavía contra las webs reales: compruébalo en Proveedores).
- **Proveedores** (solo administradores): prueba de acceso a cada proveedor desde la IP del servidor, como un healthcheck (cobertura y precios de un mes, con estado, código HTTP y tiempos), del cambio de divisas del BCE y de las portadas de las aerolíneas en estudio (Volotea, easyJet, Iberia), con o sin navegador.

### Cambiado
- `watch_providers` sustituye a la lista de proveedores en CSV de cada vigilancia: guarda el proveedor, los pares de aeropuertos reales que opera, si está activo y cuándo se comprobó. La migración `0004` convierte las vigilancias actuales (se aplica sola al arrancar).
- Una sola petición a la vez por proveedor y con pausas entre ellas, también entre la ronda, la comprobación de rutas y la prueba de acceso. Si una web nos bloquea (403/429/anti-bot) no se reintenta.

## 1.3.0 — 2026-10-10

### Cambiado
- **Panel nuevo en React** (Vite + TypeScript, carpeta `frontend/`), separado del servidor: diseño renovado con tema claro/oscuro (sigue al sistema o se elige en el menú de usuario), animaciones (que se desactivan si el sistema pide reducir el movimiento), menú adaptado al móvil, avisos emergentes y diálogos de confirmación accesibles. Mismas pantallas y mismas URL (los enlaces de los avisos siguen funcionando).
- El servidor pasa a ser una **API JSON** (`/api/v1`, documentación interactiva en `/api/v1/docs`) más el panel ya compilado. Las plantillas Jinja y `static/` desaparecen.
- La imagen Docker compila el panel en una etapa de Node y sigue siendo un único contenedor con un único proceso.

### Añadido
- Minigráfica de la tendencia del precio mínimo en cada vigilancia del panel.
- Calendario de precios usable en el móvil (el precio más barato de cada día; el resto, en el resumen accesible del día).
- Protección CSRF: toda petición que cambia algo exige la cabecera `X-Requested-With` (además de la cookie `SameSite=Lax`).
- Pruebas del panel en navegador (Playwright) contra la app real con datos simulados, con revisión de accesibilidad WCAG 2.1 AA (axe) en claro, oscuro y móvil, y tests unitarios (Vitest). La CI las ejecuta en cada PR.

## 1.2.0 — 2026-10-09

### Añadido
- **Calendario de precios** en el detalle de una vigilancia (sustituye a la lista «Mejores precios ahora mismo»): meses de lunes a domingo con el precio de cada web por día, color según lo barato que sale el día y borde para los chollos. Pulsar un precio abre esa fecha en la web; pulsar el día muestra su historial.

### Corregido
- El avatar de la cabecera podía mostrarse a tamaño real si el navegador o un proxy/CDN servía un `style.css` antiguo: las URL de `style.css` y `charts.js` llevan ahora una huella del contenido (`?v=…`) y el `<img>` del avatar lleva `width`/`height` propios.
- En móvil, las tablas de la parte inferior del detalle ya no ensanchan la página.

## 1.1.0 — 2026-10-01

### Añadido
- **Usuarios** con rol (administrador / usuario), avatar y sesión con login (sustituye al Basic Auth). Apartado **Usuarios** solo para administradores (CRUD, activar/desactivar) y **Perfil** para cada usuario.
- **Vigilancias por usuario**: cada uno ve y gestiona solo las suyas, con su histórico, ejecuciones y avisos.
- **Canales de aviso** como lista por usuario (Discord y Telegram), asignables a cada vigilancia; el administrador puede gestionar los de cualquier usuario.
- Imagen Docker publicada en `ghcr.io/katarem/flight-watcher` por GitHub Actions (amd64) y versión visible en el pie del panel.

### Cambiado
- `PANEL_USER` / `PANEL_PASSWORD` crean el administrador inicial (sin contraseña se genera una y sale en el log). Nuevas `SECRET_KEY` y `COOKIE_SECURE`.
- Los webhooks y el Telegram de Ajustes pasan a ser canales del administrador, asignados a todas sus vigilancias. Ajustes y Diagnóstico son solo para administradores.
- Migraciones `0002` (usuarios) y `0003` (canales); se aplican solas al arrancar.

### Corregido
- Las migraciones en SQLite ya no borran vigilancias ni histórico por el `ON DELETE CASCADE` al recrear tablas.

## 1.0.0
- Versión inicial: vigilancia de precios en Vueling y Ryanair, histórico, gráficas y avisos por Discord y Telegram.
