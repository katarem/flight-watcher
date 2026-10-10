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

export interface ProviderMeta {
  key: string
  label: string
  color: string
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
  enabled: boolean
  channel_ids: number[]
  created_at: string
}

export interface RunInfo {
  ok: boolean
  error: string | null
  finished_at: string | null
  n_prices: number
}

export interface BestPrice {
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
  median?: number | null
  count?: number
}

export interface WatchCard extends Watch {
  stats: ProviderStat[]
  trend: { d: string; p: number }[]
  channels: string[]
}

export interface PriceRow {
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
