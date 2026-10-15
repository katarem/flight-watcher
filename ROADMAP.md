# Roadmap de Trip Watch

Hacia dónde va el proyecto: de vigilar vuelos a encontrar **la forma más barata de llegar a un destino**, con cualquier transporte y con alojamiento incluido.

**Versión actual:** 2.1.0 · El detalle de lo publicado está en [CHANGELOG.md](CHANGELOG.md).

Marca cada punto con `[x]` cuando esté publicado en una versión.

---

## Base actual (hasta 1.8.1)

- [x] Vigilancias de vuelos de solo ida con histórico, gráficas y calendario de precios
- [x] Viajes de ida y vuelta que juntan dos vigilancias (noches mínimas y máximas)
- [x] Avisos por Discord y Telegram con enlace directo a cada fecha
- [x] Multiusuario con canales propios por vigilancia y viaje
- [x] Proveedores como scripts gestionados desde el panel (importar/exportar `.fwp`)
- [x] Medidas anti-bot por niveles (ninguna, huella de Chrome, siempre Chrome)

---

## 1.9 — Preparar el terreno (publicada en la 1.9.0)

Es la versión que decide cuánto cuestan las siguientes: generaliza lo que hoy depende de que todo sean vuelos.

### Proveedores por tipo
- [x] Columna `kind` en `provider_scripts` (migración `0008`); los actuales pasan a `flight` (también `watches.kind`)
- [x] Contrato por tipo (`app/kinds.py`): los de transporte comparten `fetch_route`; `hotel` tiene el suyo (`fetch_stay`, 2.1)
- [x] El formato `.fwp` guarda el tipo (los paquetes antiguos se importan como `flight`)
- [x] La zona «Proveedores» filtra y agrupa por tipo

### Lugares genéricos
- [x] Modelo de lugar con tipo: aeropuerto, estación, puerto, parada de bus (sus datos, `stations.csv`, `ports.csv` y `stops.csv`, llegan con cada transporte en la 3.x)
- [x] La **ciudad** como nodo común que agrupa sus aeropuertos, estaciones, puertos y paradas
- [x] El autocompletado de lugares filtra por el tipo de transporte de la vigilancia

### Horas en los precios
- [x] `DayPrice` admite hora de salida y de llegada (opcionales)
- [x] Los scripts actuales devuelven las horas cuando la web las da (Ryanair, salida y llegada; Wizz Air, la salida si hay un solo vuelo ese día; los demás calendarios no las dan)
- [x] Se guardan en `prices` (necesario para encadenar transportes en la 4.0)

### Apartado de vuelos en el panel
- [x] Todo lo de vuelos pasa a su propio apartado (`/flights`); el Panel es un resumen de todos los apartados
- [x] Redirecciones desde `/watches/{id}` (sale en avisos ya enviados)

### Avisos enriquecidos
- [x] Los avisos generan un mensaje estructurado (título, campos, enlaces, imagen) y cada tipo de canal lo pinta a su manera
- [x] Discord: `embeds` con color por proveedor, un campo por fecha y enlace directo
- [x] Telegram: botones con enlace (inline keyboard) en lugar de enlaces en el texto
- [x] Calendario resumen como imagen PNG generada en el servidor y adjunta en ambos canales

### Nombre
- [x] Nombre del proyecto: **Trip Watch** (repo e imagen `ghcr.io/katarem/trip-watch`; antes Flight Watcher)

---

## 2.0 — El viaje como entidad principal (publicada en la 2.0.0)

Antes de los hoteles se reorganiza el modelo para que el **viaje** sea la entidad que el usuario crea y
gestiona, y las vigilancias pasen a ser **tramos internos** que el viaje posee (visión de la 4.0 traída
hacia adelante). Un «solo ida» es un viaje con solo tramo de ida. Así la estancia entra como un tramo más
sin refactorizar dos veces.

### Backend
- [x] Modelo: `watches.trip_id` (FK → `trips` ON DELETE CASCADE) y `watches.role` (ida/vuelta); `trips` pierde `outbound_id`/`return_id` (migración `0009`)
- [x] La migración envuelve las vigilancias sueltas en viajes de solo ida y duplica los tramos compartidos entre viajes sin perder histórico
- [x] `create_trip`/`update_trip` crean y poseen sus tramos; borrar el viaje borra sus tramos; `toggle` pausa también los tramos
- [x] Evaluación y avisos **por viaje** (se retira el aviso por tramo); combinaciones y mensaje de «solo ida»; `trip_quotes`/`trip_alerts` admiten vuelta nula
- [x] Canales consolidados en el viaje (`watch.max_price` → `trip.max_total`, `watch_channels` → `trip_channels` al migrar)
- [x] API: `/trips` con tramos inline (ida obligatoria, vuelta opcional); fuera el CRUD suelto de `/watches` (queda el detalle del tramo, `/places` y `/route-check`)
- [x] Tests (smoke, migración y `alembic check`) reescritos al modelo viaje-céntrico, en verde
- [x] Las BD anteriores a los usuarios también migran: sus vigilancias sin dueño pasan a viajes que `bootstrap_admin()` asigna al administrador
- [x] `/alerts` da los avisos de los viajes; las ejecuciones llevan su viaje; la lista de usuarios cuenta viajes

### Frontend
- [x] Tipos (`types.ts`), piezas de viaje (`parts.tsx`) y detalle de viaje adaptados (tramo de vuelta opcional)
- [x] Formulario de viaje con tramos inline (sub-formulario por tramo con su comprobación de ruta) y casilla «solo ida»
- [x] El detalle de vigilancia pasa a ser el de un tramo (`LegDetailPage`, solo lectura; se edita desde el viaje)
- [x] Quitar del panel el CRUD suelto de vigilancias (`WatchesPage`/`WatchFormPage`) y rehacer rutas y navegación (todo bajo `/trips`, sin la sección `/flights`; el tramo en `/trips/{viaje}/legs/{tramo}`)
- [x] Panel de inicio (dashboard), `queries.ts` y `legacy.tsx` al modelo viaje-céntrico (`/watches/…` y `/flights/…` llevan al tramo dentro de su viaje)
- [x] Formulario de viaje: «Al revés que la ida», precarga con `?origin=…&destination=…` y campos con nombre propio por tramo
- [x] Tests del panel (Vitest/Playwright + axe), `CHANGELOG` y versión 2.0.0

---

## 2.1 — Alojamiento y viajeros (publicada en la 2.1.0, salvo los proveedores)

Sobre el modelo de la 2.0 la estancia entra como un tramo más del viaje (`role` = `stay`). Como solo añade y no rompe nada, va como versión menor. Decisiones del usuario (2026-10-15): el alojamiento no tiene apartado propio, va **dentro de los viajes** (un viaje puede ser de solo alojamiento, para una escapada sin transporte); el destino es **texto libre** que resuelve cada web; los **viajeros** son del viaje y cambian también el precio del transporte; los proveedores reales, al final (hace falta probarlos contra la web real).

### Estancias
- [x] Tramo de estancia: destino en texto libre, entrada (el día de la ida, o cada fecha de la ventana sin transporte), noches del viaje y los viajeros del viaje
- [x] Filtros para que el precio sea comparable: habitaciones, tipo de alojamiento (fuera los hostales, p. ej.), alojamiento entero, puntuación y estrellas mínimas, régimen, cancelación gratuita y servicios
- [x] Acotar consultas (fecha de entrada × noches): como mucho 40 por web y ronda; con transporte, solo las fechas de ida más baratas; rotando por las más antiguas
- [x] Histórico, gráficas y reglas de aviso (precio fijo, por persona y relativo) como en vuelos
- [x] ~~Apartado propio de alojamiento en el panel~~ → dentro de los viajes: viajes de **solo alojamiento**

### Viajeros
- [x] Viajeros del viaje: adultos y menores con su edad, descuento de residente (Canarias, Baleares, Ceuta, Melilla) y familia numerosa
- [x] Las webs que admiten varios viajeros reciben `passengers` y dan el precio de todos; las demás, el de un adulto × plazas (estimado)
- [x] Regla de aviso por persona (total / viajeros)

### Viajes con alojamiento
- [x] Un viaje puede incluir una estancia: total = ida + vuelta + alojamiento de esas noches
- [x] Avisos de viaje con el desglose de transporte y alojamiento (y el precio por persona)

### Proveedores `HOTEL`
- [x] Contrato de script para alojamiento (`fetch_stay` → `StayOffer`), su prueba de acceso y su editor
- [ ] Un agregador primero, que cubra muchos alojamientos con un solo proveedor; en vuelos cada aerolínea es el suyo (p. ej. Iberia Express)
- [ ] Booking (estudiar viabilidad: su API es solo para afiliados)
- [ ] Airbnb (estudiar viabilidad: no tiene API pública)
- [ ] Pasar `passengers` (residente, familia numerosa) en los scripts de vuelos del catálogo que lo admitan (Binter, Vueling, Iberia Express…)

---

## 3.x — Más transportes

Si la 1.9 generaliza bien, cada tipo es sobre todo escribir sus proveedores y ajustar el formulario. Como no traen cambios incompatibles, van como versiones menores. El orden es por lo que más aporta.

### 3.0 — Barcos
- [ ] Vigilancias de barco (puerto a puerto) con su apartado en el panel
- [ ] Opción de pasajeros y vehículo (cambia el precio)
- [ ] Viajes de ida y vuelta solo en barco
- [ ] Proveedores `SHIP`: Naviera Armas (Armas Trasmediterránea), Fred. Olsen Express, Baleària

### 3.1 — Trenes
- [ ] Vigilancias de tren (estación a estación) con su apartado en el panel
- [ ] Viajes de ida y vuelta solo en tren
- [ ] Cobertura de rutas con los horarios abiertos de Renfe (GTFS)
- [ ] Proveedores `TRAIN`: Renfe (incluye Avlo), Iryo, Ouigo; Trainline como agregador

### 3.2 — Buses
- [ ] Vigilancias de bus (parada a parada) con su apartado en el panel
- [ ] Viajes de ida y vuelta solo en bus
- [ ] Proveedores `BUS`: ALSA, FlixBus, BlaBlaCar Bus; Omio o Checkmybus como agregadores

---

## 4.0 — Viajes sin límites

Llegar del origen al destino al menor precio, sin importar el transporte.

### Viajes entre ciudades
- [ ] Un viaje va de ciudad a ciudad, no de aeropuerto a aeropuerto
- [ ] Elegir qué transportes se permiten (avión, tren, barco, bus)
- [ ] Alojamiento opcional, como en la 2.1

### Rutas con transbordos
- [ ] Propuesta de 2 a 5 ciudades intermedias según la cobertura conocida de los proveedores
- [ ] Los tramos se crean como vigilancias internas (sin que el usuario las gestione)
- [ ] Combinación por precio respetando horas: tiempo mínimo de transbordo y desplazamiento dentro de la ciudad (aeropuerto → estación)
- [ ] Aviso visible de que los billetes son independientes (perder un tramo no protege el siguiente)
- [ ] Límite de peticiones por ronda para que los tramos internos no disparen los bloqueos

### Panel y avisos
- [ ] Vista de la ruta con cada tramo, horas, transporte y precio
- [ ] Avisos con la ruta completa y el desglose por tramo
- [ ] **Mapa** (Google Maps, OpenStreetMap/Leaflet o similar; lo pidió el usuario el 2026-10-15): los lugares de cada viaje, las rutas pintadas en la web y el destino del alojamiento elegido sobre el mapa en vez de en texto libre
