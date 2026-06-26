import { Crosshair, Loader2 } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import { useServerState, type ScanItem } from "@/lib/server-state"

const RUB = (n: number) => n.toLocaleString("en-US")

const sourceStyle: Record<string, string> = {
  yolo: "bg-sky-500/15 text-sky-600 dark:text-sky-400",
  ocr: "bg-amber-500/15 text-amber-600 dark:text-amber-400",
  override: "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400",
}

/** A run of identical items collapsed into one row. */
type AggItem = ScanItem & { count: number; totalValue: number }

/** Collapse duplicate items (same catalog id) into one row with a count and
 *  summed value, then rank by ₽/slot descending. */
function dedupe(items: ScanItem[]): AggItem[] {
  const byId = new Map<string, AggItem>()
  for (const it of items) {
    const key = it.id ?? it.icon_id
    const existing = byId.get(key)
    if (existing) {
      existing.count += 1
      existing.totalValue += it.value ?? 0
    } else {
      byId.set(key, { ...it, count: 1, totalValue: it.value ?? 0 })
    }
  }
  return [...byId.values()].sort((a, b) => (b.per_slot ?? 0) - (a.per_slot ?? 0))
}

function ItemRow({ item, ts }: { item: AggItem; ts: string | null }) {
  const slots = item.slots ?? 1
  const cropUrl =
    ts != null ? `/api/crop/${ts}?box=${item.box.join(",")}` : undefined
  return (
    <li className="flex items-center gap-2 rounded-md border px-2 py-1.5">
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
    </li>
  )
}

function ItemList({
  title,
  accent,
  items,
  ts,
}: {
  title: string
  accent: string
  items: AggItem[]
  ts: string | null
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className={cn("mb-2 text-xs font-semibold tracking-wide uppercase", accent)}>
        {title} <span className="text-muted-foreground">({items.length})</span>
      </div>
      <ul className="flex min-h-0 flex-1 flex-col gap-1 overflow-y-auto pr-1">
        {items.map((item, i) => (
          <ItemRow key={`${item.icon_id}-${i}`} item={item} ts={ts} />
        ))}
      </ul>
    </div>
  )
}

export function ScanPanel() {
  const { state } = useServerState()

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

  // Dedupe to unique items ranked by ₽/slot, then split into two non-overlapping
  // halves: KEEP = the higher-value half, DITCH = the lower-value half (lowest first).
  const ranked = result ? dedupe(result.items) : []
  const half = Math.ceil(ranked.length / 2)
  const keep = ranked.slice(0, half)
  const ditch = ranked.slice(half).reverse()

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
          <span className="ml-auto text-sm text-muted-foreground">
            <span className="text-foreground">
              {result.identified}/{result.detections}
            </span>{" "}
            identified · total{" "}
            <span className="font-medium text-foreground">₽{RUB(result.total)}</span>
          </span>
        )}
      </div>

      {result ? (
        <div className="flex min-h-0 flex-1 gap-4">
          <ItemList title="Keep" accent="text-emerald-500" items={keep} ts={ts} />
          <div className="w-px shrink-0 bg-border" />
          <ItemList title="Ditch" accent="text-red-500" items={ditch} ts={ts} />
        </div>
      ) : (
        <div className="flex flex-1 items-center justify-center rounded-lg border border-dashed text-center">
          <div className="max-w-sm px-6">
            <Crosshair className="mx-auto mb-3 size-8 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              Press <kbd className="rounded border px-1">F2</kbd> in-game to capture
              your inventory and rank items by ₽/slot. Or load a saved scan from{" "}
              <span className="font-medium text-foreground">Sessions</span>.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

export default ScanPanel
