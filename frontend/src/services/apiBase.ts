export interface ApiBaseEnvironment {
  VITE_API_BASE_URL?: string
  VITE_FINANCE_API_BASE_URL?: string
}

function normalized(value: string | undefined, fallback: string): string {
  const base = value?.trim() || fallback
  return base.replace(/\/+$/, '')
}

export function v1ApiBase(environment: ApiBaseEnvironment = import.meta.env): string {
  return normalized(environment.VITE_API_BASE_URL, '/api/v1')
}

export function financeApiBase(environment: ApiBaseEnvironment = import.meta.env): string {
  return normalized(environment.VITE_FINANCE_API_BASE_URL, '/api')
}
