import { useCallback, useEffect, useState } from "react"
import { Flag, History, RotateCw } from "lucide-react"

import { cn, formatSessionTs } from "@/lib/utils"
import { useServerState } from "@/lib/server-state"
import type { NavId } from "@/components/shell/nav"

/** One saved scan as the grid shows it (see /api/sessions). */
type SessionCard = {
  id: string
  total: number | null
  identified: number | null
  detections: number | null
  reports: number
}

const RUB = (n: number) => n.toLocaleString("en-US")

export function SessionsPanel({ onNavigate }: { onNavigate: (id: NavId) => void }) {
  const { state } = useServerState()
  const [sessions, setSessions] = useState<SessionCard[]>([])
  const [loading, setLoading] = useState(true)
  const activeTs = state?.ts ?? null

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch("/api/sessions")
      setSessions((await res.json()) as SessionCard[])
    } catch {
      setSessions([])
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const load = async (ts: string) => {
    try {
      await fetch(`/api/load-session/${ts}`, { method: "POST" })
      onNavigate("analysis") // jump to Analysis: screenshot + detection boxes
    } catch {
      /* backend offline */
    }
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-sm text-muted-foreground">
          {sessions.length} saved scan{sessions.length === 1 ? "" : "s"}
        </span>
        <button
          type="button"
          onClick={() => void refresh()}
          className="ml-auto flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-accent"
        >
          <RotateCw className={cn("size-3.5", loading && "animate-spin")} />
          Refresh
        </button>
      </div>

      {sessions.length === 0 ? (
        <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed text-center">
          <div className="max-w-sm px-6">
            <History className="mx-auto mb-3 size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              No saved scans yet. Press <kbd className="rounded border px-1">F2</kbd>{" "}
              in-game to capture one.
            </p>
          </div>
        </div>
      ) : (
        <div className="grid min-h-0 flex-1 grid-cols-2 content-start gap-3 overflow-y-auto pr-1 sm:grid-cols-3 lg:grid-cols-4">
          {sessions.map(({ id: ts, total, identified, detections, reports }) => (
            <button
              key={ts}
              type="button"
              onClick={() => void load(ts)}
              title={formatSessionTs(ts)}
              className={cn(
                "group flex flex-col overflow-hidden rounded-lg border bg-card text-left shadow-sm transition-colors hover:border-amber-500/50",
                ts === activeTs && "border-amber-500/60 ring-1 ring-amber-500/40"
              )}
            >
              <div className="relative aspect-video w-full overflow-hidden bg-muted">
                <img
                  src={`/api/raw/${ts}`}
                  alt=""
                  loading="lazy"
                  className="size-full object-cover transition-transform group-hover:scale-[1.03]"
                />
                {total != null && (
                  <span className="absolute bottom-1 right-1 rounded bg-black/65 px-1.5 py-0.5 text-[11px] font-medium tabular-nums text-white">
                    ₽{RUB(total)}
                  </span>
                )}
                {ts === activeTs && (
                  <span className="absolute left-1 top-1 rounded bg-amber-500 px-1.5 py-0.5 text-[10px] font-medium text-black">
                    loaded
                  </span>
                )}
                {reports > 0 && (
                  <span
                    title={`${reports} saved report${reports === 1 ? "" : "s"}`}
                    className="absolute right-1 top-1 flex items-center gap-0.5 rounded bg-sky-600/90 px-1.5 py-0.5 text-[10px] font-medium text-white"
                  >
                    <Flag className="size-2.5" />
                    {reports}
                  </span>
                )}
              </div>
              <div className="flex items-center justify-between gap-2 px-2 py-1.5">
                <span className="truncate text-[11px] tabular-nums text-muted-foreground">
                  {formatSessionTs(ts)}
                </span>
                {identified != null && detections != null && (
                  <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                    {identified}/{detections}
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default SessionsPanel
