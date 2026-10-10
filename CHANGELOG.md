# Cambios

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
