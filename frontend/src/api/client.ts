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
  if (method !== 'GET') headers['X-Requested-With'] = 'flight-watcher'
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

export const get = <T,>(path: string) => api<T>(path)
export const post = <T,>(path: string, body?: Body) => api<T>(path, { method: 'POST', body: body ?? {} })
export const put = <T,>(path: string, body: Body) => api<T>(path, { method: 'PUT', body })
export const del = <T = void,>(path: string) => api<T>(path, { method: 'DELETE' })

export const errorList = (e: unknown): string[] =>
  e instanceof ApiError ? e.errors : [e instanceof Error ? e.message : 'Error inesperado.']
