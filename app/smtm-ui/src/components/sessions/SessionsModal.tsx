import { useCallback, useEffect, useRef, useState } from "react"
import { History, ImagePlus, Loader2, RotateCw, Wrench } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn, formatSessionTs } from "@/lib/utils"
import { useServerState } from "@/lib/server-state"

/** One saved scan as the grid shows it (see /api/sessions). */
type SessionCard = {
  id: string
  total: number | null
  identified: number | null
  detections: number | null
  fixes: number
}

const RUB = (n: number) => n.toLocaleString("en-US")

/** Global session switcher — opened from the apps (9-dots) launcher on any page. Picking
 *  a session loads it into state and closes; the top-bar chip + Analysis tab show it. */
export function SessionsModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const { state, refresh: refreshState } = useServerState()
  const [sessions, setSessions] = useState<SessionCard[]>([])
  const [loading, setLoading] = useState(true)
  const [creating, setCreating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
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

  // (Re)load the list each time the modal opens.
  useEffect(() => {
    if (open) void refresh()
  }, [open, refresh])

  const load = async (ts: string) => {
    try {
      await fetch(`/api/load-session/${ts}`, { method: "POST" })
      await refreshState() // reflect the new loaded state now (don't wait for the SSE push)
      onOpenChange(false)
    } catch {
      /* backend offline */
    }
  }

  // Upload an image -> scan it into a new session (same pipeline as an F2 capture). The
  // scan runs in the background; poll /api/latest until it's done, then load the result.
  const createFromImage = async (file: File) => {
    setError(null)
    setCreating(true)
    try {
      const body = new FormData()
      body.append("file", file)
      const res = await fetch("/api/scan-image", { method: "POST", body })
      if (!res.ok) {
        setError(res.status === 409 ? "A scan is already running." : "Couldn't read that image.")
        return
      }
      // wait for the background scan to finish (status -> done | error)
      for (let i = 0; i < 120; i++) {
        await new Promise((r) => setTimeout(r, 500))
        const s = await (await fetch("/api/latest")).json()
        if (s.status === "done" && s.ts) {
          await load(s.ts as string)
          return
        }
        if (s.status === "error") {
          setError(s.error ?? "Scan failed.")
          return
        }
      }
      setError("Scan timed out.")
    } catch {
      setError("Backend offline.")
    } finally {
      setCreating(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[80vh] flex-col sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            Sessions
            <span className="text-sm font-normal text-muted-foreground">
              {sessions.length} saved scan{sessions.length === 1 ? "" : "s"}
            </span>
            <div className="ml-auto flex items-center gap-2">
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={creating}
                onClick={() => fileRef.current?.click()}
                className="border-amber-500/50 bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 hover:text-amber-700 dark:text-amber-400"
              >
                {creating ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <ImagePlus className="size-3.5" />
                )}
                {creating ? "Scanning…" : "Create from image"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => void refresh()}
                className="text-muted-foreground"
              >
                <RotateCw className={cn("size-3.5", loading && "animate-spin")} />
                Refresh
              </Button>
            </div>
          </DialogTitle>
          <DialogDescription>
            Pick a scan to load it — it stays loaded as you switch pages.
          </DialogDescription>
        </DialogHeader>

        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0]
            e.target.value = "" // allow re-picking the same file
            if (f) void createFromImage(f)
          }}
        />
        {error && <p className="text-sm text-destructive">{error}</p>}

        {sessions.length === 0 ? (
          <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed py-10 text-center">
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
            {sessions.map(({ id: ts, total, identified, detections, fixes }) => (
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
                    <Badge className="absolute bottom-1 right-1 bg-black/65 tabular-nums text-white">
                      ₽{RUB(total)}
                    </Badge>
                  )}
                  {ts === activeTs && (
                    <Badge className="absolute left-1 top-1 bg-amber-500 text-black">
                      loaded
                    </Badge>
                  )}
                  {fixes > 0 && (
                    <Badge
                      title={`${fixes} saved fix${fixes === 1 ? "" : "es"}`}
                      className="absolute right-1 top-1 gap-0.5 bg-amber-500/90 text-black"
                    >
                      <Wrench className="size-2.5" />
                      {fixes}
                    </Badge>
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
      </DialogContent>
    </Dialog>
  )
}

export default SessionsModal
