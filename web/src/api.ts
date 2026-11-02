// Thin fetch wrapper: bearer token, JSON in and out, the API's own error messages.

export type RowError = { row: number; usn: string | null; column: string | null; message: string }
export class ApiError extends Error {
  status: number
  code?: string
  errors?: RowError[]
  constructor(status: number, detail: string, code?: string, errors?: RowError[]) {
    super(detail)
    this.status = status
    this.code = code
    this.errors = errors
  }
}

const TOKEN_KEY = 'copo.token'

export function getToken(): string | null {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}
export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch { /* storage unavailable: the session lasts until reload */ }
}

let onUnauthorized: () => void = () => {}
export function setUnauthorizedHandler(fn: () => void) { onUnauthorized = fn }

export async function api<T>(path: string, opts: { method?: string; body?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(opts.body) }
  const res = await fetch(path, { method: opts.method ?? (body ? 'POST' : 'GET'), headers, body })
  if (res.status === 401 && path !== '/api/auth/login') onUnauthorized()
  const type = res.headers.get('content-type') ?? ''
  const data = type.includes('json') ? await res.json() : await res.text()
  if (!res.ok) {
    const detail = typeof data === 'object' && data
      ? (typeof data.detail === 'string' ? data.detail : Array.isArray(data.detail) ? data.detail.map((d: { msg: string }) => d.msg).join('; ') : res.statusText)
      : String(data || res.statusText)
    throw new ApiError(res.status, detail, data?.code, data?.errors)
  }
  return data as T
}

export async function download(path: string, filename: string) {
  const res = await fetch(path, { headers: { Authorization: `Bearer ${getToken() ?? ''}` } })
  if (!res.ok) throw new ApiError(res.status, 'Download failed')
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
