import { useState } from "react"
import { Check, Crosshair, Loader2, Search } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { CorrectionDialog } from "@/components/analysis/CorrectionDialog"
import { boxKey, useFixes, type Flag } from "@/lib/fixes"
import { cn } from "@/lib/utils"
import { useServerState, type ScanItem, type ScanResult } from "@/lib/server-state"

const RUB = (n: number) => n.toLocaleString("en-US")

const sourceStyle: Record<string, string> = {
  yolo: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
  ocr: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  override: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
  corrected: "bg-amber-500/20 text-amber-700 dark:text-amber-300",
  added: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
}

/** A run of identical items collapsed into one row (keeps its member boxes so a fix
 *  applies to all of them). */
type AggItem = ScanItem & { count: number; totalValue: number; members: ScanItem[] }

/** Apply the session's fixes to the raw detections: a "should be X" fix re-identifies and
 *  re-values the box (source -> "corrected"); "not an item" drops it; an unidentified box
 *  that's been fixed now counts as identified. */
function resolveWithFixes(result: ScanResult, flags: Record<string, Flag>): ScanItem[] {
  const out: ScanItem[] = []
  const consider = (it: ScanItem, identified: boolean) => {
    const f = flags[boxKey(it.box)]
    if (f?.type === "not_an_item") return
    if (f?.type === "wrong_item" && f.corrected) {
      const w = f.corrected.width ?? 1
      const h = f.corrected.height ?? 1
      const value = f.corrected.value ?? 0
      out.push({
        ...it,
        id: f.corrected.item_id,
        name: f.corrected.name,
        short: f.corrected.short ?? it.short,
        value,
        width: w,
        height: h,
        slots: w * h,
        per_slot: value / (w * h),
        source: "corrected",
      })
    } else if (identified) {
      out.push(it)
    }
  }
  result.items.forEach((it) => consider(it, true))
  result.unidentified.forEach((it) => consider(it, false))
  // Items the detector missed and the user added by hand (no detection behind them) —
  // they live only in the fixes, so synthesize a row from the chosen catalog item.
  for (const f of Object.values(flags)) {
    if (f.type !== "missed_item" || !f.corrected) continue
    const w = f.corrected.width ?? 1
    const h = f.corrected.height ?? 1
    const value = f.corrected.value ?? 0
    out.push({
      box: f.box,
      icon_id: "",
      id: f.corrected.item_id,
      name: f.corrected.name,
      short: f.corrected.short,
      value,
      width: w,
      height: h,
      slots: w * h,
      per_slot: value / (w * h),
      source: "added",
    })
  }
  return out
}

/** Collapse duplicate items (same catalog id) into one row with a count, summed value,
 *  and member boxes, then rank by ₽/slot descending. */
function dedupe(items: ScanItem[]): AggItem[] {
  const byId = new Map<string, AggItem>()
  for (const it of items) {
    const key = it.id ?? it.icon_id
    const existing = byId.get(key)
    if (existing) {
      existing.count += 1
      existing.totalValue += it.value ?? 0
      existing.members.push(it)
    } else {
      byId.set(key, { ...it, count: 1, totalValue: it.value ?? 0, members: [it] })
    }
  }
  return [...byId.values()].sort((a, b) => (b.per_slot ?? 0) - (a.per_slot ?? 0))
}

function ItemRow({
  item,
  ts,
  onEdit,
}: {
  item: AggItem
  ts: string | null
  onEdit: (item: AggItem) => void
}) {
  const slots = item.slots ?? 1
  const cropUrl =
    ts != null ? `/api/crop/${ts}?box=${item.box.join(",")}` : undefined
  return (
    <li>
      <button
        type="button"
        onClick={() => onEdit(item)}
        title="Fix what this should be"
        className="flex w-full items-center gap-2 rounded-md border px-2 py-1.5 text-left transition-colors hover:border-amber-500/50 hover:bg-accent"
      >
        {cropUrl && (
          <img
            src={cropUrl}
            alt=""
            loading="lazy"
            className="size-9 shrink-0 rounded bg-muted object-contain"
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm">{item.name}</span>
            {item.count > 1 && (
              <Badge variant="secondary" className="shrink-0 px-1 tabular-nums">
                ×{item.count}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <span className="truncate">{item.short}</span>
            <span>·</span>
            <span>
              {slots} slot{slots > 1 ? "s" : ""}
            </span>
            {item.source && (
              <Badge
                className={cn(
                  "px-1 py-px",
                  sourceStyle[item.source] ?? "bg-muted text-muted-foreground"
                )}
              >
                {item.source}
              </Badge>
            )}
          </div>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-sm font-medium tabular-nums">
            ₽{RUB(item.per_slot ?? 0)}
            <span className="text-[11px] font-normal text-muted-foreground">/sl</span>
          </div>
          <div className="text-[11px] tabular-nums text-muted-foreground">
            ₽{RUB(item.totalValue)}
          </div>
        </div>
      </button>
    </li>
  )
}

function ItemList({
  items,
  ts,
  onEdit,
}: {
  items: AggItem[]
  ts: string | null
  onEdit: (item: AggItem) => void
}) {
  return (
    <ul className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1">
      {items.map((item, i) => (
        <ItemRow key={`${item.icon_id}-${i}`} item={item} ts={ts} onEdit={onEdit} />
      ))}
    </ul>
  )
}

export function ScanPanel() {
  const { state } = useServerState()
  const { flags, flagList, dirty, saving, applyFlags, removeFlags, save } = useFixes()
  const [editing, setEditing] = useState<AggItem | null>(null)
  const [query, setQuery] = useState("")

  const status = state?.status ?? "idle"
  const result = state?.result ?? null
  const ts = state?.ts ?? null
  const busy = status === "capturing" || status === "scanning"

  const statusText =
    status === "capturing"
      ? "Capturing…"
      : status === "scanning"
        ? "Scanning…"
        : status === "error"
          ? (state?.error ?? "Error")
          : status === "done"
            ? "Done"
            : "Idle"

  // Apply fixes, then dedupe to unique items ranked by ₽/slot, then split into two
  // non-overlapping halves: KEEP = higher-value half, DITCH = lower-value (lowest first).
  const resolved = result ? resolveWithFixes(result, flags) : []
  const total = resolved.reduce((s, it) => s + (it.value ?? 0), 0)
  const ranked = dedupe(resolved)
  const half = Math.ceil(ranked.length / 2)
  // The search filters each column in place, so a match keeps its keep/ditch side.
  const q = query.trim().toLowerCase()
  const match = (it: AggItem) =>
    !q ||
    (it.name ?? "").toLowerCase().includes(q) ||
    (it.short ?? "").toLowerCase().includes(q)
  const keep = ranked.slice(0, half).filter(match)
  const ditch = ranked.slice(half).reverse().filter(match)

  // A fix on a deduped row applies to every member box of that row.
  const saveRowFix = (flag: Flag) => {
    if (!editing) return
    applyFlags(
      editing.members.map((m) => ({
        box: m.box,
        icon_id: m.icon_id,
        type: flag.type,
        shown: { item_id: m.id, name: m.name },
        corrected: flag.corrected,
      }))
    )
    setEditing(null)
  }
  const clearRowFix = () => {
    if (!editing) return
    removeFlags(editing.members.map((m) => m.box))
    setEditing(null)
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        {busy && <Loader2 className="size-4 animate-spin text-muted-foreground" />}
        <span
          className={cn(
            "text-sm",
            status === "error" ? "text-destructive" : "text-muted-foreground"
          )}
        >
          {statusText}
        </span>
        {result && (
          <span className="text-sm text-muted-foreground">
            <span className="text-foreground">
              {resolved.length}/{result.detections}
            </span>{" "}
            identified · total{" "}
            <span className="font-medium text-foreground">₽{RUB(total)}</span>
          </span>
        )}

        {result && (
          <div className="flex flex-1 justify-center">
            <div className="relative w-full max-w-xs">
              <Search className="absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Filter items…"
                className="h-8 pl-8"
              />
            </div>
          </div>
        )}

        {result && (
          <div className="flex items-center gap-2">
            {!dirty && flagList.length > 0 && (
              <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
                <Check className="size-3.5" /> Saved
              </span>
            )}
            <Button
              type="button"
              size="sm"
              variant="outline"
              onClick={() => void save()}
              disabled={!dirty || saving}
              className={cn(
                dirty &&
                  !saving &&
                  "border-amber-500/50 bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 hover:text-amber-700 dark:text-amber-400"
              )}
            >
              {saving && <Loader2 className="size-3.5 animate-spin" />}
              Save fixes{flagList.length ? ` (${flagList.length})` : ""}
            </Button>
          </div>
        )}
      </div>

      {result ? (
        <div className="flex min-h-0 flex-1 gap-4">
          <ItemList items={keep} ts={ts} onEdit={setEditing} />
          <div className="w-px shrink-0 bg-border" />
          <ItemList items={ditch} ts={ts} onEdit={setEditing} />
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed text-center">
          <div className="max-w-sm px-6">
            <Crosshair className="mx-auto mb-3 size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              Press <kbd className="rounded border px-1">F2</kbd> in-game to capture
              your inventory and rank items by ₽/slot. Or load a saved scan from the
              apps menu (top-left).
            </p>
          </div>
        </div>
      )}

      {editing && ts && (
        <CorrectionDialog
          ts={ts}
          item={editing}
          existing={flags[boxKey(editing.box)]}
          onClose={() => setEditing(null)}
          onSave={saveRowFix}
          onClear={clearRowFix}
        />
      )}
    </div>
  )
}

export default ScanPanel
