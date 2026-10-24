export type HealthResponse = {
  status: 'ok'
}

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResponse> {
  const response = await fetch('/api/health', { signal })
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`)
  }
  return (await response.json()) as HealthResponse
}
