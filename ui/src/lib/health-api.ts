import type { McpHealth } from './types'

const POLL_INTERVAL_MS = 5000

function mapResponse(data: Record<string, unknown>): McpHealth {
  return {
    status:             (data.status as McpHealth['status']) ?? 'unavailable',
    toolsDiscovered:    (data.tools_discovered as number)    ?? 0,
    lastSuccessfulCall: (data.last_successful_call as string | null) ?? null,
    reconnectAttempts:  (data.reconnect_attempts as number)  ?? 0,
    serverVersion:      (data.server_version as string)      ?? '—',
    error:              (data.error as string | null)        ?? null,
  }
}

export function pollMcpHealth(
  apiUrl: string,
  onUpdate: (health: McpHealth) => void,
  signal: AbortSignal,
): void {
  async function tick() {
    try {
      const res  = await fetch(`${apiUrl}/health`, { signal })
      const data = await res.json() as Record<string, unknown>
      onUpdate(mapResponse(data))
    } catch {
      // Fetch aborted or network error — emit unavailable so badge reflects reality
      if (!signal.aborted) {
        onUpdate({
          status:             'unavailable',
          toolsDiscovered:    0,
          lastSuccessfulCall: null,
          reconnectAttempts:  0,
          serverVersion:      '—',
          error:              'Health endpoint unreachable',
        })
      }
    }
  }

  // Fire immediately, then on interval
  tick()
  const id = setInterval(tick, POLL_INTERVAL_MS)
  signal.addEventListener('abort', () => clearInterval(id))
}
