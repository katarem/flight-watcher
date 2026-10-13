/** Cliente de la API: JSON, cookie de sesión y cabecera anti-CSRF en todo lo que cambia algo. */

export const API = '/api/v1'

export class ApiError extends Error {
  status: number
  errors: string[]

  constructor(status: number, errors: string[]) {
    super(errors[0] ?? `Error ${status}`)
    this.status = status
    this.errors = errors
  }
}

/** Se llama cuando la sesión caduca (401) para volver al login. Lo registra el proveedor de sesión. */
let onUnauthorized: () => void = () => {}
export const setUnauthorizedHandler = (fn: () => void) => {
  onUnauthorized = fn
}

type Body = object | FormData | undefined

export async function api<T>(path: string, init: { method?: string; body?: Body } = {}): Promise<T> {
  const method = init.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  let body: BodyInit | undefined
  if (method !== 'GET') headers['X-Requested-With'] = 'trip-watch'
  if (init.body instanceof FormData) body = init.body
  else if (init.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(init.body)
  }

  let res: Response
  try {
    res = await fetch(API + path, { method, headers, body, credentials: 'same-origin' })
  } catch {
    throw new ApiError(0, ['No hay conexión con el servidor.'])
  }
  if (res.status === 204) return undefined as T
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    if (res.status === 401 && path !== '/session') onUnauthorized()
    const errors: string[] = data?.errors ?? [data?.detail ?? `Error ${res.status}`]
    throw new ApiError(res.status, errors)
  }
  return data as T
}

/**
 * POST que responde en streaming con NDJSON (una línea JSON por evento), como la prueba de un proveedor:
 * llama a `onEvent` con cada línea según llega. Si la API rechaza la petición, lanza `ApiError` como `api()`.
 */
export async function stream<T>(path: string, body: object, onEvent: (event: T) => void): Promise<void> {
  let res: Response
  try {
    res = await fetch(API + path, {
      method: 'POST',
      headers: { Accept: 'application/x-ndjson', 'Content-Type': 'application/json', 'X-Requested-With': 'trip-watch' },
      body: JSON.stringify(body),
      credentials: 'same-origin',
    })
  } catch {
    throw new ApiError(0, ['No hay conexión con el servidor.'])
  }
  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => null)
    if (res.status === 401) onUnauthorized()
    throw new ApiError(res.status, data?.errors ?? [data?.detail ?? `Error ${res.status}`])
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const flush = (all: boolean) => {
    const lines = buffer.split('\n')
    buffer = all ? '' : lines.pop() ?? ''
    for (const line of lines) if (line.trim()) onEvent(JSON.parse(line) as T)
  }
  for (;;) {
    const { done, value } = await reader.read().catch(() => {
      throw new ApiError(0, ['Se ha cortado la conexión con el servidor.'])
    })
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    flush(false)
  }
  buffer += decoder.decode()
  flush(true)
}

export const get = <T,>(path: string) => api<T>(path)
export const post = <T,>(path: string, body?: Body) => api<T>(path, { method: 'POST', body: body ?? {} })
export const put = <T,>(path: string, body: Body) => api<T>(path, { method: 'PUT', body })
export const del = <T = void,>(path: string) => api<T>(path, { method: 'DELETE' })

export const errorList = (e: unknown): string[] =>
  e instanceof ApiError ? e.errors : [e instanceof Error ? e.message : 'Error inesperado.']
