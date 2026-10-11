# Cambios

## 1.7.0 — 2026-10-11

### Cambiado
- **Un solo tipo de proveedor**: ya no hay proveedores «de serie», «en estudio» y «propios». Todos son scripts de Python que se ven, editan, prueban, exportan, importan o borran desde **Proveedores**, en una única lista.
- **Vueling y Ryanair pasan a ser scripts** (`app/providers/catalog/incluidos.fwp`): se crean solos la primera vez que arranca esta versión, con la misma clave, así que las vigilancias, el histórico y los avisos siguen igual. **Wizz Air y Google Flights** (sin verificar) quedan en un paquete aparte (`sin-verificar.fwp`) que se importa con un clic; si alguna vigilancia ya los usaba, se crean también al actualizar.
- La **plantilla de enlace** es parte de cada proveedor (se edita en su editor). Las que hubiera en Ajustes pasan solas a su proveedor y desaparecen de Ajustes.
- `PROVIDER_SCRIPTS=0` ya no desactiva los proveedores (ahora todos son scripts): los que hay siguen funcionando, pero desde el panel no se puede crear, importar, cambiar el código ni probar ninguno.
- La API de proveedores queda en `/api/v1/providers` (lista, `/{clave}`, `/test`, `/health`, `/export`, `/import`, `/import/preview`, `/revalidate`); desaparece `/providers/scripts`.
- Si `fetch_route` acepta `max_stops`, el script recibe el máximo de escalas de la vigilancia y filtra él mismo (lo usa Google Flights).

### Añadido
- **Importar proveedores** desde un enlace (un `…/blob/…` de GitHub se cambia por el archivo en bruto) o desde un archivo, con vista previa: qué trae, si es nuevo, igual o qué cambia respecto al guardado, el código de cada uno y lo que no se podría importar. Pide la contraseña, importa todo o nada y recuerda de qué enlace vino cada proveedor.
- **Exportar** los proveedores elegidos o todos (también uno desde su editor) en un archivo `.fwp`: texto con una línea de datos en JSON por proveedor y el script tal cual debajo, para poder leerlo y compararlo antes de importarlo.
- **Consola de la prueba** encima del código en el editor: cuenta en directo (streaming) cada paso, cada petición con su URL, estado, tiempo, tamaño y forma del JSON, los `api.log`/`print` del script y, si falla, la línea del script con su código. Se puede copiar.
- Migración `0007` (solo una columna nueva que admite nulos: `provider_scripts.source`).

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
