# Flight Watcher

Panel web + bot que vigila los precios de vuelos en **Vueling** y **Ryanair** (y en las aerolíneas que añadas), guarda todo el histórico en SQLite (o PostgreSQL / MySQL / MariaDB), dibuja gráficas de evolución por web y te avisa por **Discord** y/o **Telegram** con un **enlace directo a cada fecha**.

Sustituye al script suelto anterior: ya no hay que editar archivos ni tocar el cron. Todo se configura desde el panel.

## Puesta en marcha

```bash
cp .env.example .env        # usuario y contraseña del panel
docker compose up -d --build
```

Abre `http://localhost:8000`. En el primer arranque se crean dos vigilancias: **Sevilla → Tenerife** (`SVQ → TCI`) y **Tenerife → Sevilla**, con Vueling y Ryanair y un aviso a partir de 40 €.

`TCI` es el código de ciudad de Tenerife: el bot consulta **Tenerife Norte (TFN)** y **Tenerife Sur (TFS)** y se queda con el precio más bajo de cada día, indicando el aeropuerto (p. ej. `SVQ→TFS`). Puedes usar `TFN` o `TFS` si solo te interesa uno.

### Carpeta de datos y base de datos

Todo se configura en `.env`:

| Variable | Por defecto | Para qué |
|---|---|---|
| `DATA_PATH` | `./data` | Carpeta **del host** montada en `/data`: BD SQLite y archivos de diagnóstico |
| `DB_ENGINE` | `sqlite` | `sqlite`, `postgres`, `mysql` o `mariadb` |
| `DB_HOST`, `DB_PORT` | `localhost`, 5432 / 3306 | Servidor (se ignoran con SQLite) |
| `DB_NAME` | `flight_watcher` | La base de datos debe existir; las tablas se crean solas |
| `DB_USER`, `DB_PASSWORD` | vacíos | Credenciales |

Con MySQL/MariaDB las tablas se crean en `utf8mb4`. Cambiar de motor no migra los datos: el nuevo arranca vacío con las vigilancias iniciales.

El esquema se gestiona con **Alembic**: al arrancar, la app aplica sola las migraciones pendientes (`app/migrations/`), también sobre bases de datos SQLite creadas con versiones anteriores.

Después, en el panel:

1. **Ajustes → Notificaciones:** pega el webhook de Discord y/o el token y chat ID de Telegram y pulsa *Enviar mensaje de prueba*.
2. **Ajustes → Programación:** elige a qué hora(s) se comprueba (p. ej. `8` o `8,20`) y la zona horaria.
3. Pulsa **Comprobar todo** para traer los primeros precios.

## Aerolíneas y cómo se consultan

Todo funciona en **headless**. Siempre que se puede se usa la API JSON pública que la propia web usa para su calendario (sin navegador: más rápido y estable).

| Aerolínea | Rutas Sevilla ↔ Tenerife | Método | Estado (2026-09-30) |
|---|---|---|---|
| Vueling | SVQ ↔ TFN directo, todo el año | API `apiw.vueling.com/api/v1/availability` | ✅ ~1 año en una petición |
| Ryanair | SVQ ↔ TFS directo, **estacional** (sin precios en invierno) | API `ryanair.com/api/farfnd/v4/.../cheapestPerDay` | ✅ una petición por mes |
| Binter | SVQ ↔ TFN directo, 5 días/semana | — | ❌ descartada: Cloudflare bloquea web y API a clientes automatizados |
| Iberia | Solo con escala (Madrid) | — | ❌ descartada: 403 al navegador headless |
| Air Europa | Solo con escala (TFN → Madrid → SVQ) | — | ❌ descartada: 403 al navegador headless |

Según Aena (2026-09-30), **no hay más aerolíneas directas**: SVQ ↔ TFN solo Vueling y Binter; SVQ ↔ TFS solo Ryanair.

Si una web bloquea, la comprobación falla con un mensaje claro («bloquea el navegador automatizado (HTTP 403)») y te avisa. **No se usan técnicas para esquivar sistemas anti-bot.**

Para depurar: **Ajustes → Navegador y diagnóstico → Guardar capturas, HTML y JSON**, pulsa **Comprobar ahora** y abre **Diagnóstico** (en los proveedores por API se guarda la respuesta JSON de cada petición).

Si alguna vigilancia antigua tenía `iberia` marcada, se ignora al comprobar; al editarla y guardarla desaparece.

> Ejecútalo desde una IP residencial: las aerolíneas suelen bloquear IPs de centros de datos.

## Enlaces con las fechas elegidas

Cada precio del panel y cada aviso lleva un enlace a esa fecha concreta.

- **Vueling:** usa el formato oficial de deeplink (`o`, `d`, `dd` obligatorios):
  `https://tickets.vueling.com/booking?o={origin}&d={destination}&dd={date}&adt=1&chd=0&inf=0&c=es-ES&cur=EUR`.
  Residentes en islas o Ceuta pueden añadir `&dt=1` en Ajustes.
- **Ryanair:** `https://www.ryanair.com/es/es/trip/flights/select?...&dateOut={date}&isReturn=false&originIata={origin}&destinationIata={destination}`.

## Reglas de aviso

Por cada vigilancia y web se avisa de una fecha si:

- su precio es **≤ el precio máximo** que definas, **o**
- es un **X % inferior a lo habitual** (mediana de los precios guardados de esa ruta y web; se activa con las *muestras mínimas* de Ajustes, 30 por defecto).

No se repite el aviso de la misma fecha salvo que el precio baje aún más. Si no hay ningún canal configurado, los avisos no se marcan como enviados y se mandarán cuando lo configures.

Puedes limitar cada vigilancia a un rango de fechas; sin límites se comprueban todas las que tengan precio desde hoy.

## Panel

- **Panel:** mejor precio actual por web y ruta, con enlace, etiqueta *chollo*, errores y últimos avisos.
- **Detalle de una vigilancia:**
  - Gráfica de la **evolución del precio mínimo** por web.
  - Gráfica del **precio actual por fecha de vuelo** (qué días salen baratos en cada web).
  - **Historial de una fecha concreta** (cómo cambia el precio del mismo vuelo con el tiempo).
  - Tabla de mejores precios con enlace (filtrable por web), historial de comprobaciones y avisos enviados.
- **Ejecuciones** y **Diagnóstico** para ver qué pasó en cada comprobación.

## Añadir otra aerolínea

1. Crea `app/providers/<nombre>.py`. Si la web tiene un endpoint JSON accesible, hereda de `ApiProvider` e implementa `fetch_route` (mira `vueling.py` o `ryanair.py`). Si hay que recorrer la web:

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

Aparece sola en los formularios, gráficas, avisos y en la plantilla de enlace de Ajustes.

Para añadir otro código de ciudad (como `TCI`), añádelo a `METRO_AREAS` en `app/providers/__init__.py`.

## Seguridad

- Define `PANEL_USER` y `PANEL_PASSWORD` (Basic Auth) o pon el panel detrás de tu proxy con autenticación. **No lo expongas sin protección:** guarda el webhook de Discord y el token de Telegram en la base de datos en texto plano.
- Solo se aceptan webhooks de Discord con la URL oficial y los campos secretos nunca se devuelven al navegador.
- Respeta los términos de uso de cada aerolínea; una comprobación al día es una frecuencia razonable.

## Estructura

```
app/
  main.py         panel web y API de gráficas
  checker.py      ronda de comprobaciones + reglas de aviso
  scheduler.py    planificación (se cambia desde Ajustes)
  notify.py       Discord / Telegram
  db.py           acceso a datos (SQLAlchemy Core: SQLite, PostgreSQL, MySQL, MariaDB)
  migrations/     migraciones de Alembic
  providers/      base.py (abstracción), extract.py, vueling.py, ryanair.py
  templates/, static/
tests/
  smoke_test.py         extremo a extremo con datos simulados (sin red)
  browser_mock_test.py  Playwright real contra una web simulada
```

Pruebas (necesitan además `pip install httpx`): `python -m tests.smoke_test` y `python -m tests.browser_mock_test` (esta última necesita Chromium; con uno propio: `FW_CHROMIUM=/ruta/chromium`).

## Limitaciones conocidas

- Solo ida por vigilancia (para ida y vuelta, crea dos vigilancias, como en tu configuración inicial).
- Los precios del calendario son «desde» y no incluyen equipaje facturado.
- La regla «habitual» compara con la mediana de la ruta, no con la de esa misma fecha.
