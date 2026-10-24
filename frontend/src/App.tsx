import { useEffect, useState } from 'react'
import { fetchHealth } from './api/health'

type BackendStatus = 'checking' | 'ok' | 'unavailable'

function App() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>('checking')

  useEffect(() => {
    const controller = new AbortController()
    fetchHealth(controller.signal)
      .then(() => setBackendStatus('ok'))
      .catch(() => {
        if (!controller.signal.aborted) {
          setBackendStatus('unavailable')
        }
      })
    return () => controller.abort()
  }, [])

  return (
    <main>
      <h1>Portfolio</h1>
      <p>
        Backend status: <span data-testid="backend-status">{backendStatus}</span>
      </p>
    </main>
  )
}

export default App
