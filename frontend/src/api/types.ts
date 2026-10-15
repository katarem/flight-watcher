/** Tipos de las respuestas de la API (`app/api/*.py`). */

export interface User {
  id: number
  username: string
  display_name: string
  role: 'admin' | 'user'
  enabled: boolean
  avatar: string | null
  created_at: string
}

export interface Me extends User {
  notify_errors: boolean
}

export type Coverage = 'network' | 'probe' | 'universal'

/** Medidas anti-bot de un proveedor: 0 ninguna, 1 huella de Chrome (y Chrome si bloquean), 2 siempre Chrome. */
export type StealthLevel = 0 | 1 | 2

/** Transporte de un viaje (y de sus tramos) o tipo de un proveedor (`app/kinds.py`). */
export type KindKey = 'flight' | 'ship' | 'train' | 'bus' | 'hotel'

export interface KindMeta {
  key: KindKey
  /** «Vuelos». */
  label: string
  noun: string
  plural: string
  /** Tipo de lugar donde empieza y acaba (airport, station, port, stop); '' si no es un transporte. */
  node: string
  node_label: string
  available: boolean
  /** Versión prevista si aún no está disponible. */
  since: string
  transport: boolean
}

export interface ProviderMeta {
  key: string
  kind: KindKey
  label: string
  color: string
  coverage: Coverage
  max_routes: number | null
}

/** Lugar (`app/places.py`): de un transporte (aeropuerto, estación, puerto, parada) o que los agrupa (ciudad, país,
 *  grupo). */
export interface Place {
  code: string
  kind: 'airport' | 'station' | 'port' | 'stop' | 'city' | 'country' | 'group'
  kind_label: string
  label: string
  detail: string
  country: string
  /** Transportes con algún lugar (flight, ship…). */
  modes: string[]
  /** Lugares reales por transporte. */
  nodes: Record<string, string[]>
  airports: string[]
}

export interface ChannelField {
  key: string
  label: string
  secret: boolean
  placeholder: string
}

export interface ChannelKind {
  key: string
  label: string
  fields: ChannelField[]
}

export interface Meta {
  version: string
  kinds: KindMeta[]
  providers: ProviderMeta[]
  channel_kinds: ChannelKind[]
  avatar_max_bytes: number
  max_pairs: number
}

export interface Status {
  running: boolean
  current: string
  next_run: string | null
}

export interface Watch {
  id: number
  kind: KindKey
  name: string
  origin: string
  destination: string
  providers: string[]
  max_price: number | null
  discount_pct: number
  date_from: string | null
  date_to: string | null
  /** 0 = solo directos; null = sin límite. */
  max_stops: number | null
  enabled: boolean
  channel_ids: number[]
  created_at: string
  origin_place: Place
  destination_place: Place
  coverage: WatchCoverage[]
}

/** Pares de aeropuertos que cubre cada proveedor del tramo ("SVQ-TFN"). */
export interface WatchCoverage {
  key: string
  routes: string[]
  active: boolean
  checked_at: string | null
}

/** Moneda original, escalas y horas de un precio (el precio siempre va en euros). */
export interface PriceExtras {
  currency: string
  orig_price: number | null
  stops: number | null
  /** Salida y llegada («AAAA-MM-DDTHH:MM», hora local de cada lugar) si la web las da. */
  departs_at?: string | null
  arrives_at?: string | null
}

export interface RunInfo {
  ok: boolean
  error: string | null
  finished_at: string | null
  n_prices: number
}

export interface BestPrice extends PriceExtras {
  flight_date: string
  price: number
  checked_at: string
  origin: string | null
  destination: string | null
  route: string | null
  link: string
  deal: 'fixed' | 'relative' | null
}

export interface ProviderStat {
  key: string
  label: string
  color: string
  base: number | null
  best: BestPrice | null
  run: RunInfo | null
  active: boolean
  routes: string[]
  checked_at: string | null
  median?: number | null
  count?: number
}

export interface PriceRow extends PriceExtras {
  provider: string
  flight_date: string
  price: number
  route: string | null
  link: string
  deal: 'fixed' | 'relative' | null
}

export interface CheckSummary {
  provider: string
  checked_at: string
  n: number
  mn: number
  av: number
}

/** Detalle de un tramo (una vigilancia interna de un viaje). */
export interface WatchDetail {
  watch: Watch
  role: LegRole
  stats: ProviderStat[]
  prices: PriceRow[]
  checks: CheckSummary[]
  /** El viaje del que este tramo forma parte. */
  trip: { id: number; name: string }
}

export interface Series {
  labels: string[]
  series: Record<string, (number | null)[]>
}

export interface Charts {
  min_over_time: Series
  by_flight_date: Series
}

export interface Run {
  id: number
  /** El tramo comprobado y su viaje. */
  watch_id: number
  watch_name: string
  watch_kind: KindKey
  trip_id: number
  trip_name: string
  provider: string
  trigger: string
  started_at: string
  finished_at: string | null
  ok: boolean | null
  n_prices: number
  n_deals: number
  error: string | null
}

export interface Channel {
  id: number
  kind: string
  kind_label: string
  name: string
  enabled: boolean
}

export interface ChannelFieldValue extends ChannelField {
  value: string
  saved: boolean
}

export interface ChannelDetail extends Channel {
  fields: ChannelFieldValue[]
}

export interface AdminUser extends User {
  n_trips: number
  n_channels: number
}

export interface SettingsData {
  values: Record<string, string>
}

export interface DebugFile {
  name: string
  size_kb: number
  mtime: string
  image: boolean
}

export type CoverageStatus = 'ok' | 'none' | 'error' | 'timeout' | 'too_many'

export interface RouteCheckProvider {
  key: string
  label: string
  color: string
  coverage: Coverage
  status: CoverageStatus
  ok: boolean
  routes: string[]
  reason: string
  elapsed_ms: number
}

export interface RouteCheck {
  origin: Place
  destination: Place
  pairs: string[]
  providers: RouteCheckProvider[]
}

export type HealthStatus = 'ok' | 'empty' | 'blocked' | 'error' | 'timeout' | 'skipped'

export interface HealthStep {
  name: string
  status: HealthStatus
  detail: string
  http_status: number | null
  ms: number
  route?: string
}

/** Último resultado de la prueba de acceso de un proveedor. */
export interface ProviderLast {
  status: HealthStatus
  detail: HealthStep[]
  latency_ms: number
  checked_at: string
}

/** Proveedor: un script de Python que cumple el contrato de app/providers/scripted.py. */
export interface Provider {
  key: string
  kind: KindKey
  kind_label: string
  label: string
  color: string
  coverage: Coverage
  coverage_label: string
  max_routes: number | null
  health_origin: string
  health_destination: string
  link_template: string
  notes: string
  min_interval: number
  enabled: boolean
  created_at: string
  updated_at: string
  updated_by: string
  /** Enlace del paquete del que se importó (null = escrito en el panel o importado de un archivo). */
  source: string | null
  /** Cargado y en uso (activo y sin errores). */
  loaded: boolean
  /** Por qué no se pudo cargar (activo pero roto). */
  error: string | null
  /** «Medidas anti-bot» (app/providers/stealth.py): 0 ninguna, 1 huella de Chrome (y Chrome si bloquean), 2 siempre Chrome. */
  stealth: StealthLevel
  /** `fetch_route` acepta `max_stops` (filtra él mismo por escalas). */
  stops_filter: boolean
  n_watches: number
  last: ProviderLast | null
  code?: string
}

export interface ProvidersData {
  providers: Provider[]
  /** false si el servidor no deja cambiar código desde el panel (PROVIDER_SCRIPTS=0). */
  editable: boolean
  template: string
  status_labels: Record<string, string>
  /** Enlaces de los que ya se han importado proveedores. */
  sources: string[]
  /** Paquetes publicados con la aplicación. */
  catalogs: { label: string; url: string }[]
  /** Tipos que puede tener un proveedor. */
  kinds: KindMeta[]
}

export interface HealthResult {
  key: string
  status: HealthStatus
  route: string
  steps: HealthStep[]
  latency_ms: number
  checked_at: string
}

export interface ScriptSample {
  day: string
  price: number
  currency: string
  origin: string
  destination: string
  stops: number | null
  departs_at: string | null
  arrives_at: string | null
}

export interface ScriptTestResult extends HealthResult {
  sample: ScriptSample[]
  n_prices: number
}

export type ConsoleLevel = 'step' | 'info' | 'ok' | 'warn' | 'error' | 'http' | 'script'

/** Una línea de la consola de la prueba del editor (llegan en streaming mientras se ejecuta). */
export interface ConsoleEvent {
  t: number
  level: ConsoleLevel
  text: string
}

export interface HealthRun {
  results: HealthResult[]
  fx: HealthStep | null
}

export interface ImportItem {
  key: string
  kind: KindKey
  label: string
  color: string
  coverage: string
  coverage_label: string
  notes: string
  code: string
  /** new = no existe; changed = sustituye a uno con cambios; same = igual que el guardado. */
  status: 'new' | 'changed' | 'same'
  changes: string[]
  errors: string[]
  n_watches: number
  enabled: boolean | null
}

export interface ImportPreview {
  source: string | null
  text: string
  providers: ImportItem[]
}

/** Papel de un tramo en su viaje. */
export type LegRole = 'outbound' | 'return'

/** Tramo de un viaje (una vigilancia interna), con lo necesario para pintarlo y editarlo dentro del viaje. */
export interface TripLeg {
  id: number
  kind: KindKey
  name: string
  origin: string
  destination: string
  enabled: boolean
  origin_place: Place
  destination_place: Place
  providers: string[]
  coverage: WatchCoverage[]
  /** 0 = solo directos; null = sin límite. */
  max_stops: number | null
}

export interface Trip {
  id: number
  name: string
  /** Transporte del viaje, derivado del tramo de ida. */
  kind: KindKey
  min_nights: number
  max_nights: number
  date_from: string | null
  date_to: string | null
  max_total: number | null
  discount_pct: number
  enabled: boolean
  channel_ids: number[]
  created_at: string
  outbound: TripLeg
  /** null = viaje de solo ida. */
  return: TripLeg | null
  /** Avisos que no impiden guardar (tramos que no encajan). */
  warnings: string[]
}

/** Vuelo más barato de un tramo para un día (en euros, con su web y su enlace). */
export interface TripPrice extends PriceExtras {
  flight_date: string
  price: number
  provider: string
  route: string | null
  link: string
  checked_at: string
}

/** Una combinación de un viaje: fecha de ida y total. En un viaje de solo ida no hay vuelta ni noches. */
export interface TripCombo {
  out_date: string
  ret_date: string | null
  nights: number | null
  total: number
  deal: 'fixed' | 'relative' | null
  out: TripPrice
  ret: TripPrice | null
}

export interface TripTrend {
  d: string
  p: number
}

export interface TripCard extends Trip {
  base: number | null
  best: TripCombo | null
  n_dates: number
  trend: TripTrend[]
  channels: string[]
}

export interface TripAlert {
  id: number
  trip_id: number
  out_date: string
  ret_date: string | null
  total: number
  sent_at: string
}

/** Aviso de cualquiera de los viajes del usuario (/alerts), con el nombre del viaje. */
export interface UserAlert extends TripAlert {
  trip_name: string
}

export interface TripDetail {
  trip: Trip
  base: number | null
  /** La combinación más barata de cada fecha de ida. */
  quotes: TripCombo[]
  trend: TripTrend[]
  alerts: TripAlert[]
}
