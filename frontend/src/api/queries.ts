/** Consultas compartidas (TanStack Query). Las claves agrupan lo que se refresca junto. */
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { toast } from 'sonner'
import { ApiError, get } from './client'
import type {
  AdminUser, Alert, Channel, ChannelDetail, Charts, DebugFile, Me, Meta, Run, Series, SettingsData, Status,
  User, WatchCard, WatchDetail,
} from './types'

export const keys = {
  me: ['me'] as const,
  meta: ['meta'] as const,
  status: ['status'] as const,
  watches: ['watches'] as const,
  watch: (id: number) => ['watches', id] as const,
  charts: (id: number) => ['watches', id, 'charts'] as const,
  dateHistory: (id: number, date: string) => ['watches', id, 'date', date] as const,
  alerts: ['alerts'] as const,
  runs: ['runs'] as const,
  channels: (base: string) => ['channels', base] as const,
  channel: (base: string, id: number) => ['channels', base, id] as const,
  users: ['users'] as const,
  user: (id: number) => ['users', id] as const,
  settings: ['settings'] as const,
  debug: ['debug'] as const,
}

export function useMe() {
  return useQuery({
    queryKey: keys.me,
    queryFn: async () => {
      try {
        return (await get<{ user: Me }>('/me')).user
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null
        throw e
      }
    },
    staleTime: 60_000,
    retry: false,
  })
}

export const useMeta = () =>
  useQuery({ queryKey: keys.meta, queryFn: () => get<Meta>('/meta'), staleTime: Infinity })

/** Proveedor por clave (etiqueta y color), con un valor razonable si ya no existe. */
export function useProviders() {
  const meta = useMeta().data
  const map = new Map((meta?.providers ?? []).map((p) => [p.key, p]))
  return (key: string) => map.get(key) ?? { key, label: key, color: '#8892a6' }
}

/** Estado de la ronda: se consulta a menudo mientras corre y, al terminar, se refresca todo lo demás. */
export function useStatus() {
  const qc = useQueryClient()
  const query = useQuery({
    queryKey: keys.status,
    queryFn: () => get<Status>('/status'),
    refetchInterval: (q) => (q.state.data?.running ? 2500 : 30_000),
  })
  const wasRunning = useRef(false)
  const running = query.data?.running ?? false
  useEffect(() => {
    if (wasRunning.current && !running) {
      qc.invalidateQueries({ queryKey: keys.watches })
      qc.invalidateQueries({ queryKey: keys.alerts })
      qc.invalidateQueries({ queryKey: keys.runs })
      toast.success('Comprobación terminada', { description: 'Precios, avisos y gráficas actualizados.' })
    }
    wasRunning.current = running
  }, [running, qc])
  return query
}

export const useWatches = () =>
  useQuery({ queryKey: keys.watches, queryFn: async () => (await get<{ watches: WatchCard[] }>('/watches')).watches })

export const useWatch = (id: number) =>
  useQuery({ queryKey: keys.watch(id), queryFn: () => get<WatchDetail>(`/watches/${id}`), enabled: id > 0 })

export const useCharts = (id: number) =>
  useQuery({ queryKey: keys.charts(id), queryFn: () => get<Charts>(`/watches/${id}/charts`) })

export const useDateHistory = (id: number, date: string) =>
  useQuery({
    queryKey: keys.dateHistory(id, date),
    queryFn: () => get<Series>(`/watches/${id}/date-history?date=${encodeURIComponent(date)}`),
    enabled: !!date,
    placeholderData: keepPreviousData,
  })

export const useAlerts = (limit = 8) =>
  useQuery({ queryKey: [...keys.alerts, limit], queryFn: async () => (await get<{ alerts: Alert[] }>(`/alerts?limit=${limit}`)).alerts })

export const useRuns = (limit = 50) =>
  useQuery({ queryKey: [...keys.runs, limit], queryFn: async () => (await get<{ runs: Run[] }>(`/runs?limit=${limit}`)).runs })

/** `base` es '' (canales propios) o '/users/{id}' (los de un usuario, para el admin). */
export const useChannels = (base: string) =>
  useQuery({ queryKey: keys.channels(base), queryFn: async () => (await get<{ channels: Channel[] }>(`${base}/channels`)).channels })

export const useChannel = (base: string, id: number | null) =>
  useQuery({
    queryKey: keys.channel(base, id ?? 0),
    queryFn: async () => (await get<{ channel: ChannelDetail }>(`${base}/channels/${id}`)).channel,
    enabled: id != null,
  })

export const useUsers = () =>
  useQuery({ queryKey: keys.users, queryFn: async () => (await get<{ users: AdminUser[] }>('/users')).users })

export const useUser = (id: number | null) =>
  useQuery({
    queryKey: keys.user(id ?? 0),
    queryFn: async () => (await get<{ user: User }>(`/users/${id}`)).user,
    enabled: id != null,
  })

export const useSettings = () => useQuery({ queryKey: keys.settings, queryFn: () => get<SettingsData>('/settings') })

export const useDebugFiles = () =>
  useQuery({ queryKey: keys.debug, queryFn: async () => (await get<{ files: DebugFile[] }>('/debug/files')).files })
