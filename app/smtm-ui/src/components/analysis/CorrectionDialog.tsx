import { useEffect, useRef, useState } from "react"
import { Ban, Search, Trash2, X } from "lucide-react"

import { cn } from "@/lib/utils"
import type { ScanItem } from "@/lib/server-state"

const RUB = (n: number) => n.toLocaleString("en-US")

/** A catalog search hit (see /api/search). */
type Hit = {
  id: string
  name: string
  short: string
  width: number
  height: number
  value: number
}

/** What the user decided about one box. `corrected` set => "should be X";
 *  type "not_an_item" => false positive. */
export type Flag = {
  box: [number, number, number, number]
  icon_id: string
  type: "wrong_item" | "not_an_item"
  shown?: { item_id?: string; name?: string }
  corrected?: { item_id: string; name: string }
}

/** Modal to report what a detected box SHOULD be. Searches the catalog and records a
 *  flag — it never edits the link map (read-only; reports are triaged offline). */
export function CorrectionDialog({
  ts,
  item,
  existing,
  onClose,
  onSave,
  onClear,
}: {
  ts: string
  item: ScanItem
  existing?: Flag
  onClose: () => void
  onSave: (flag: Flag) => void
  onClear: () => void
}) {
  const [q, setQ] = useState("")
  const [hits, setHits] = useState<Hit[]>([])
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const cropUrl = `/api/crop/${ts}?box=${item.box.join(",")}`
  const shown = item.name ?? `unidentified (${item.icon_id})`

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  // Debounced catalog search.
  useEffect(() => {
    const term = q.trim()
    if (!term) {
      setHits([])
      return
    }
    setLoading(true)
    const t = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(term)}`)
        setHits((await res.json()) as Hit[])
      } catch {
        setHits([])
      } finally {
        setLoading(false)
      }
    }, 200)
    return () => clearTimeout(t)
  }, [q])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose()
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [onClose])

  const pick = (h: Hit) =>
    onSave({
      box: item.box,
      icon_id: item.icon_id,
      type: "wrong_item",
      shown: { item_id: item.id, name: item.name },
      corrected: { item_id: h.id, name: h.name },
    })

  const markNotItem = () =>
    onSave({
      box: item.box,
      icon_id: item.icon_id,
      type: "not_an_item",
      shown: { item_id: item.id, name: item.name },
    })

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[80vh] w-full max-w-md flex-col overflow-hidden rounded-lg border bg-card shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b p-3">
          <img
            src={cropUrl}
            alt=""
            className="size-14 shrink-0 rounded border bg-muted object-contain"
          />
          <div className="min-w-0 flex-1">
            <div className="text-[11px] text-muted-foreground">detected as</div>
            <div className="truncate text-sm font-medium">{shown}</div>
            {existing?.corrected && (
              <div className="truncate text-[11px] text-amber-600 dark:text-amber-400">
                flagged → {existing.corrected.name}
              </div>
            )}
            {existing?.type === "not_an_item" && (
              <div className="text-[11px] text-red-600 dark:text-red-400">
                flagged → not an item
              </div>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted-foreground hover:bg-accent"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="relative border-b p-2">
          <Search className="absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search for the correct item…"
            className="w-full rounded-md border bg-background py-2 pr-3 pl-9 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </div>

        <ul className="min-h-0 flex-1 overflow-y-auto p-1">
          {loading && (
            <li className="px-3 py-2 text-sm text-muted-foreground">Searching…</li>
          )}
          {!loading && q.trim() && hits.length === 0 && (
            <li className="px-3 py-2 text-sm text-muted-foreground">No matches.</li>
          )}
          {hits.map((h) => (
            <li key={h.id}>
              <button
                type="button"
                onClick={() => pick(h)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-accent"
              >
                <img
                  src={`/api/cat-icon/${h.id}`}
                  alt=""
                  loading="lazy"
                  className="size-8 shrink-0 rounded bg-muted object-contain"
                />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm">{h.name}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {h.short} · {h.width}×{h.height}
                  </div>
                </div>
                <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                  ₽{RUB(h.value)}
                </span>
              </button>
            </li>
          ))}
        </ul>

        <div className="flex items-center gap-2 border-t p-2">
          <button
            type="button"
            onClick={markNotItem}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs transition-colors hover:bg-accent",
              existing?.type === "not_an_item" &&
                "border-red-500/50 text-red-600 dark:text-red-400"
            )}
          >
            <Ban className="size-3.5" /> Not an item
          </button>
          {existing && (
            <button
              type="button"
              onClick={onClear}
              className="flex items-center gap-1.5 rounded-md border px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-accent"
            >
              <Trash2 className="size-3.5" /> Remove flag
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

export default CorrectionDialog
