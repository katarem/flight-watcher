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

export interface ProviderMeta {
  key: string
  label: string
  color: string
  coverage: Coverage
  max_routes: number | null
}

/** Aeropuerto, ciudad, país o grupo (`app/places.py`). */
export interface Place {
  code: string
  kind: 'airport' | 'city' | 'country' | 'group'
  kind_label: string
  label: string
  detail: string
  country: string
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

/** Pares de aeropuertos que cubre cada proveedor de la vigilancia ("SVQ-TFN"). */
export interface WatchCoverage {
  key: string
  routes: string[]
  active: boolean
  checked_at: string | null
}

/** Moneda original y escalas de un precio (el precio siempre va en euros). */
export interface PriceExtras {
  currency: string
  orig_price: number | null
  stops: number | null
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

export interface WatchCard extends Watch {
  stats: ProviderStat[]
  trend: { d: string; p: number }[]
  channels: string[]
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

export interface Alert {
  id: number
  watch_id: number
  watch_name: string
  provider: string
  flight_date: string
  price: number
  link: string | null
  sent_at: string
}

export interface WatchDetail {
  watch: Watch
  stats: ProviderStat[]
  prices: PriceRow[]
  checks: CheckSummary[]
  alerts: Alert[]
  /** Viajes de los que esta vigilancia es tramo. */
  trips: { id: number; name: string }[]
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
  watch_id: number
  watch_name: string
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
  n_watches: number
  n_channels: number
}

export interface SettingsData {
  values: Record<string, string>
  providers: { key: string; label: string; default_link_template: string }[]
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

export interface ProviderInfo {
  key: string
  label: string
  color: string
  coverage: Coverage
  coverage_label: string
  needs_browser: boolean
  max_routes: number | null
  stops_filter: boolean
  min_interval: number
  health_route: string
  verified: string | null
  notes: string
  last: { status: HealthStatus; detail: HealthStep[]; latency_ms: number; checked_at: string } | null
}

export interface Candidate {
  key: string
  label: string
  url: string
  notes: string
}

export interface ProvidersData {
  providers: ProviderInfo[]
  candidates: Candidate[]
  status_labels: Record<string, string>
}

export interface HealthResult {
  key: string
  status: HealthStatus
  route: string
  steps: HealthStep[]
  latency_ms: number
  checked_at: string
}

export interface CandidateResult extends Candidate {
  status: HealthStatus
  steps: HealthStep[]
  checked_at: string
}

export interface HealthRun {
  results: HealthResult[]
  fx: HealthStep | null
  candidates: CandidateResult[]
}

/** Tramo de un viaje: una vigilancia del usuario. */
export interface TripLeg {
  id: number
  name: string
  origin: string
  destination: string
  enabled: boolean
}

export interface Trip {
  id: number
  name: string
  outbound_id: number
  return_id: number
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
  return: TripLeg
  /** Avisos que no impiden guardar (tramos en pausa o que no encajan). */
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

/** Una combinación ida + vuelta: fecha de ida, noches y total. */
export interface TripCombo {
  out_date: string
  ret_date: string
  nights: number
  total: number
  deal: 'fixed' | 'relative' | null
  out: TripPrice
  ret: TripPrice
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
  ret_date: string
  total: number
  sent_at: string
}

export interface TripDetail {
  trip: Trip
  base: number | null
  /** La combinación más barata de cada fecha de ida. */
  quotes: TripCombo[]
  trend: TripTrend[]
  alerts: TripAlert[]
}
