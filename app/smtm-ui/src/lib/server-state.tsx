import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react"

export type ModelFetchState = "checking" | "downloading" | "ready" | "error"

export type ModelInfo = {
  name: string
  state: ModelFetchState
  error: string | null
}

/** One detected cell. Identified items carry name/value/per_slot; unidentified
 *  ones only have box/icon_id (and whatever OCR read). */
export type ScanItem = {
  box: [number, number, number, number]
  icon_id: string
  source: "yolo" | "ocr" | "override" | "corrected" | "added" | null
  id?: string
  name?: string
  short?: string
  width?: number
  height?: number
  value?: number
  slots?: number
  per_slot?: number
}

export type ScanResult = {
  items: ScanItem[] // identified, sorted by per_slot desc
  unidentified: ScanItem[]
  detections: number
  identified: number
  total: number
  by_yolo: number
  by_ocr: number
  by_override: number
}

/** The backend's live state, pushed over SSE. Typed to the fields the UI reads. */
export type ServerState = {
  status: "idle" | "capturing" | "scanning" | "done" | "error" | string
  error: string | null
  ts: string | null
  result: ScanResult | null
  model: ModelInfo | null
  // (price_mode, prices_age_h … also present — add as the UI grows)
}

type ServerStateValue = {
  state: ServerState | null
  /** Whether the SSE stream is currently connected. */
  connected: boolean
  /** Pull the current state from /api/latest immediately (don't wait for the next SSE
   *  push). Use after an action that changes server state, e.g. loading a session. */
  refresh: () => Promise<void>
}

const ServerStateContext = createContext<ServerStateValue>({
  state: null,
  connected: false,
  refresh: async () => {},
})

/**
 * Single Server-Sent-Events connection to the Flask backend (`/api/stream`),
 * shared across the app. The backend pushes the full state object on every
 * change, so consumers just read what they need.
 */
export function ServerStateProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<ServerState | null>(null)
  const [connected, setConnected] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/latest")
      setState((await res.json()) as ServerState)
    } catch {
      // backend offline — keep the last known state
    }
  }, [])

  useEffect(() => {
    const es = new EventSource("/api/stream")
    es.onmessage = (event) => {
      try {
        setState(JSON.parse(event.data) as ServerState)
        setConnected(true)
      } catch {
        // ignore non-JSON heartbeats
      }
    }
    es.onopen = () => setConnected(true)
    es.onerror = () => setConnected(false)
    return () => es.close()
  }, [])

  return (
    <ServerStateContext.Provider value={{ state, connected, refresh }}>
      {children}
    </ServerStateContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useServerState() {
  return useContext(ServerStateContext)
}
