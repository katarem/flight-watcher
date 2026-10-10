# Cambios

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
