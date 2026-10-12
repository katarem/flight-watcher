# Roadmap

Hacia dónde va el proyecto: de vigilar vuelos a encontrar **la forma más barata de llegar a un destino**, con cualquier transporte y con alojamiento incluido.

**Versión actual:** 1.8.1 · El detalle de lo publicado está en [CHANGELOG.md](CHANGELOG.md).

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

## 1.9 — Preparar el terreno

Es la versión que decide cuánto cuestan las siguientes: generaliza lo que hoy depende de que todo sean vuelos.

### Proveedores por tipo
- [ ] Columna `kind` en `provider_scripts` (migración nueva); los actuales pasan a `FLIGHT`
- [ ] Contrato por tipo: los de transporte comparten `fetch_route`; `HOTEL` tendrá el suyo
- [ ] El formato `.fwp` guarda el tipo (los paquetes antiguos se importan como `FLIGHT`)
- [ ] La zona «Proveedores» filtra y agrupa por tipo

### Lugares genéricos
- [ ] Modelo de lugar con tipo: aeropuerto, estación, puerto, parada de bus
- [ ] La **ciudad** como nodo común que agrupa sus aeropuertos, estaciones, puertos y paradas
- [ ] El autocompletado de lugares filtra por el tipo de transporte de la vigilancia

### Horas en los precios
- [ ] `DayPrice` admite hora de salida y de llegada (opcionales)
- [ ] Los scripts actuales devuelven las horas cuando la web las da
- [ ] Se guardan en `prices` (necesario para encadenar transportes en la 4.0)

### Apartado de vuelos en el panel
- [ ] Todo lo de vuelos pasa a su propio apartado; el resto del panel deja de asumir que todo son vuelos
- [ ] Redirecciones desde `/watches/{id}` (sale en avisos ya enviados)

### Avisos enriquecidos
- [ ] Los avisos generan un mensaje estructurado (título, campos, enlaces, imagen) y cada tipo de canal lo pinta a su manera
- [ ] Discord: `embeds` con color por proveedor, un campo por fecha y enlace directo
- [ ] Telegram: botones con enlace (inline keyboard) en lugar de enlaces en el texto
- [ ] Calendario resumen como imagen PNG generada en el servidor y adjunta en ambos canales

### Por decidir
- [ ] Nombre del proyecto (repo e imagen `ghcr.io/katarem/flight-watcher`) si deja de ser solo de vuelos

---

## 2.0 — Alojamiento (hoteles y alquiler vacacional)

### Estancias
- [ ] Entidad «estancia»: destino, fecha de entrada, noches, personas
- [ ] Filtros para que el precio sea comparable: zona, puntuación mínima, tipo de alojamiento
- [ ] Acotar consultas (fecha de entrada × noches): noches fijas o rango corto, o solo las fechas de ida que ya sean buenas
- [ ] Histórico, gráficas y reglas de aviso (precio fijo y relativo) como en vuelos
- [ ] Apartado propio de alojamiento en el panel

### Viajes con alojamiento
- [ ] Un viaje puede incluir una estancia: total = ida + vuelta + alojamiento de esas noches
- [ ] Avisos de viaje con el desglose de transporte y alojamiento

### Proveedores `HOTEL`
- [ ] Contrato de script para alojamiento (`fetch_stay` o similar)
- [ ] Un agregador primero (p. ej. Google Hotels), que cubra muchos alojamientos con un solo proveedor; en vuelos cada aerolínea es el suyo (p. ej. Iberia Express)
- [ ] Booking (estudiar viabilidad: su API es solo para afiliados)
- [ ] Airbnb (estudiar viabilidad: no tiene API pública)

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
- [ ] Alojamiento opcional, como en la 2.0

### Rutas con transbordos
- [ ] Propuesta de 2 a 5 ciudades intermedias según la cobertura conocida de los proveedores
- [ ] Los tramos se crean como vigilancias internas (sin que el usuario las gestione)
- [ ] Combinación por precio respetando horas: tiempo mínimo de transbordo y desplazamiento dentro de la ciudad (aeropuerto → estación)
- [ ] Aviso visible de que los billetes son independientes (perder un tramo no protege el siguiente)
- [ ] Límite de peticiones por ronda para que los tramos internos no disparen los bloqueos

### Panel y avisos
- [ ] Vista de la ruta con cada tramo, horas, transporte y precio
- [ ] Avisos con la ruta completa y el desglose por tramo
