import { useEffect, useRef, useState } from "react"
import { Ban, Search, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
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

/** Dialog to fix what a detected box SHOULD be. Searches the catalog and records a flag
 *  — it never edits the link map (read-only; fixes are triaged offline later). */
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
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent
        className="flex max-h-[80vh] flex-col gap-0 overflow-hidden p-0 sm:max-w-md"
        onOpenAutoFocus={(e) => {
          e.preventDefault()
          inputRef.current?.focus()
        }}
      >
        <DialogHeader className="flex-row items-center gap-3 space-y-0 border-b p-3 pr-10 text-left">
          <img
            src={cropUrl}
            alt=""
            className="size-14 shrink-0 rounded border bg-muted object-contain"
          />
          <div className="min-w-0 flex-1">
            <DialogDescription className="text-[11px]">detected as</DialogDescription>
            <DialogTitle className="truncate text-sm font-medium">{shown}</DialogTitle>
            {existing?.corrected && (
              <div className="truncate text-[11px] text-amber-600 dark:text-amber-400">
                fixed → {existing.corrected.name}
              </div>
            )}
            {existing?.type === "not_an_item" && (
              <div className="text-[11px] text-red-600 dark:text-red-400">
                flagged → not an item
              </div>
            )}
          </div>
        </DialogHeader>

        <div className="relative border-b p-2">
          <Search className="absolute top-1/2 left-4 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search for the correct item…"
            className="pl-9"
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

        <DialogFooter className="flex-row justify-start gap-2 border-t p-2 sm:justify-start">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={markNotItem}
            className={cn(
              existing?.type === "not_an_item" &&
                "border-red-500/50 text-red-600 dark:text-red-400"
            )}
          >
            <Ban className="size-3.5" /> Not an item
          </Button>
          {existing && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onClear}
              className="text-muted-foreground"
            >
              <Trash2 className="size-3.5" /> Remove flag
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export default CorrectionDialog
