export type User = {
  id: number
  nim: string
  name: string
  created_at: string
}

export type AccessLog = {
  id: number
  user_id: number | null
  current_nim?: string | null
  direction?: 'ENTRY' | 'EXIT' | null
  matched_name: string
  status: 'ALLOWED' | 'DENIED'
  similarity: number
  duration_ms?: number | null
  description?: string | null
  timestamp: string
}

export function buildQuery(params: Record<string, string | number | undefined | null>) {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') query.set(key, String(value))
  })
  const text = query.toString()
  return text ? `?${text}` : ''
}

export async function apiJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!response.ok) {
    let message = `Request failed: ${response.status}`
    try {
      const body = await response.json()
      if (body?.detail) message = body.detail
    } catch {
      // Plain status is enough when the API does not return JSON.
    }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}
