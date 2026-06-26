import { useEffect, useMemo, useState } from "react"
import { Check, Copy, Loader2, ScanSearch, X } from "lucide-react"

import { cn, formatSessionTs } from "@/lib/utils"
import { useServerState, type ScanItem } from "@/lib/server-state"
import type { NavId } from "@/components/shell/nav"
import { CorrectionDialog, type Flag } from "./CorrectionDialog"

const RUB = (n: number) => n.toLocaleString("en-US")
const boxKey = (b: number[]) => b.join(",")

// YOLO sometimes emits two boxes for one item (different icon-id, near-identical box).
// Treat boxes above this overlap as the same physical item so a fix applies to both.
const DUP_IOU = 0.6
function iou(a: number[], b: number[]) {
  const ix0 = Math.max(a[0], b[0]),
    iy0 = Math.max(a[1], b[1]),
    ix1 = Math.min(a[2], b[2]),
    iy1 = Math.min(a[3], b[3])
  const inter = Math.max(0, ix1 - ix0) * Math.max(0, iy1 - iy0)
  if (!inter) return 0
  const union =
    (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
  return union ? inter / union : 0
}

/** One detection drawn over the screenshot. Boxes are in source-image pixels, so we
 *  position them as percentages of the natural size — exact at any display scale.
 *  Click to report what the box should be. Colour states (labels are hover-only):
 *    emerald/red = identified/unidentified   ·   amber = flagged "should be X"
 *    red (solid) = flagged "not an item" */
function Box({
  item,
  nat,
  identified,
  flag,
  onClick,
}: {
  item: ScanItem
  nat: { w: number; h: number }
  identified: boolean
  flag?: Flag
  onClick: () => void
}) {
  const [x0, y0, x1, y1] = item.box
  const style = {
    left: `${(x0 / nat.w) * 100}%`,
    top: `${(y0 / nat.h) * 100}%`,
    width: `${((x1 - x0) / nat.w) * 100}%`,
    height: `${((y1 - y0) / nat.h) * 100}%`,
  }
  const flagged = !!flag
  const label = flagged
    ? flag.type === "not_an_item"
      ? "✕ not an item"
      : `→ ${flag.corrected?.name ?? ""}`
    : identified
      ? `${item.name}${item.per_slot != null ? ` · ₽${RUB(item.per_slot)}/sl` : ""}`
      : `unidentified (${item.icon_id})`
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "group absolute border-2 transition-colors",
        flagged
          ? flag.type === "not_an_item"
            ? "border-red-400 bg-red-500/25"
            : "border-amber-400 bg-amber-400/25"
          : identified
            ? "border-emerald-500/80 hover:bg-emerald-500/20"
            : "border-red-500/80 hover:bg-red-500/20"
      )}
      style={style}
      title={label}
    >
      <span
        className={cn(
          "pointer-events-none absolute -top-px left-0 max-w-[40vw] -translate-y-full truncate rounded-t px-1 py-0.5 text-[10px] font-medium whitespace-nowrap text-white",
          "hidden group-hover:block", // label hover-only to keep the screenshot clear
          flagged
            ? flag.type === "not_an_item"
              ? "bg-red-600"
              : "bg-amber-600"
            : identified
              ? "bg-emerald-600"
              : "bg-red-600"
        )}
      >
        {label}
      </span>
    </button>
  )
}

/** After fixing one box, ask whether the other boxes with the SAME detected icon-id are
 *  the same item. Each match is shown as a toggleable crop (all selected by default) so a
 *  user can deselect a wrong one before applying the fix to the rest. */
function PropagateDialog({
  ts,
  name,
  boxes,
  preselected,
  onApply,
  onSkip,
}: {
  ts: string
  name: string
  boxes: ScanItem[]
  preselected: Set<string>
  onApply: (chosen: ScanItem[]) => void
  onSkip: () => void
}) {
  // Boxes already adjusted start deselected so re-applying won't overwrite them.
  const [selected, setSelected] = useState<Set<number>>(
    () => new Set(boxes.flatMap((b, i) => (preselected.has(boxKey(b.box)) ? [i] : [])))
  )
  const toggle = (i: number) =>
    setSelected((s) => {
      const next = new Set(s)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  const chosen = boxes.filter((_, i) => selected.has(i))

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onSkip}
    >
      <div
        className="flex max-h-[80vh] w-full max-w-md flex-col rounded-lg border bg-card p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-2 text-sm font-medium">
          <Copy className="mt-0.5 size-4 shrink-0 text-orange-500" />
          <span className="flex-1">
            {boxes.length} other box{boxes.length === 1 ? "" : "es"} have the same detected
            id
          </span>
          <button
            type="button"
            onClick={onSkip}
            title="Close without changes"
            className="-mt-1 -mr-1 rounded p-1 text-muted-foreground hover:bg-accent"
          >
            <X className="size-4" />
          </button>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          Deselect any that are <span className="font-medium">not</span>{" "}
          <span className="font-medium text-foreground">{name}</span>.
        </p>
        {/* p-1 so the selected crops' outer ring isn't clipped by the scroll container
            (overflow-y-auto also clips horizontal overflow). */}
        <div className="mt-3 grid min-h-0 flex-1 grid-cols-6 gap-1.5 overflow-y-auto p-1">
          {boxes.map((it, i) => {
            const on = selected.has(i)
            return (
              <button
                key={i}
                type="button"
                onClick={() => toggle(i)}
                title={on ? "Selected — click to skip" : "Skipped — click to include"}
                className={cn(
                  // Ring sits AROUND the crop (not over it) so the image is always fully
                  // shown; deselected crops dim + desaturate.
                  "aspect-square overflow-hidden rounded bg-muted transition-all",
                  on
                    ? "ring-2 ring-amber-500 ring-offset-1 ring-offset-card"
                    : "opacity-35 grayscale hover:opacity-60"
                )}
              >
                <img
                  src={`/api/crop/${ts}?box=${it.box.join(",")}`}
                  alt=""
                  className="size-full object-contain"
                />
              </button>
            )
          })}
        </div>
        <div className="mt-4 flex justify-end">
          <button
            type="button"
            onClick={() => onApply(chosen)}
            disabled={!chosen.length}
            className={cn(
              "rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
              chosen.length
                ? "border-amber-500/50 bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 dark:text-amber-400"
                : "text-muted-foreground"
            )}
          >
            Mark {chosen.length} as {name}
          </button>
        </div>
      </div>
    </div>
  )
}

export function AnalysisPanel({ onNavigate }: { onNavigate: (id: NavId) => void }) {
  const { state } = useServerState()
  const ts = state?.ts ?? null
  const result = state?.result ?? null
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null)
  const [flags, setFlags] = useState<Record<string, Flag>>({})
  const [editing, setEditing] = useState<ScanItem | null>(null)
  const [propagate, setPropagate] = useState<{
    iconId: string
    corrected: { item_id: string; name: string }
    boxes: ScanItem[]
    preselected: Set<string> // boxKeys checked by default (the not-yet-adjusted ones)
  } | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)

  // Flags belong to one screenshot — drop them when the loaded session changes.
  useEffect(() => {
    setFlags({})
    setSaved(null)
    setPropagate(null)
  }, [ts])

  // All detections on this screenshot (identified + unidentified), in one list.
  const allBoxes = useMemo(
    () => (result ? [...result.items, ...result.unidentified] : []),
    [result]
  )

  if (!ts || !result) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-dashed text-center">
        <div className="max-w-sm px-6">
          <ScanSearch className="mx-auto mb-3 size-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            No session loaded. Open one from{" "}
            <button
              type="button"
              onClick={() => onNavigate("sessions")}
              className="font-medium text-amber-600 hover:underline dark:text-amber-400"
            >
              Sessions
            </button>{" "}
            to inspect its detection boxes.
          </p>
        </div>
      </div>
    )
  }

  const flagList = Object.values(flags)

  // Apply a flag to a box AND to any duplicate detection of it (same item, double-
  // detected), so a fix doesn't leave a red twin box behind.
  const setFlagWithDuplicates = (flag: Flag, base: Record<string, Flag>) => {
    const next = { ...base, [boxKey(flag.box)]: flag }
    for (const b of allBoxes) {
      if (boxKey(b.box) === boxKey(flag.box)) continue
      if (iou(b.box, flag.box) >= DUP_IOU) {
        next[boxKey(b.box)] = {
          ...flag,
          box: b.box,
          icon_id: b.icon_id,
          shown: { item_id: b.id, name: b.name },
        }
      }
    }
    return next
  }

  const saveFlag = (flag: Flag) => {
    const next = setFlagWithDuplicates(flag, flags)
    setFlags(next)
    setEditing(null)
    setSaved(null)
    // Offer to apply the same fix to other boxes YOLO gave the same icon-id. Already-
    // adjusted siblings are shown too but start deselected (so we don't overwrite them).
    if (flag.type === "wrong_item" && flag.corrected) {
      const siblings = allBoxes.filter(
        (b) => b.icon_id === flag.icon_id && boxKey(b.box) !== boxKey(flag.box)
      )
      const preselected = new Set(
        siblings.filter((b) => !next[boxKey(b.box)]).map((b) => boxKey(b.box))
      )
      if (preselected.size) {
        setPropagate({
          iconId: flag.icon_id,
          corrected: flag.corrected,
          boxes: siblings,
          preselected,
        })
      }
    }
  }

  const clearFlag = () => {
    if (!editing) return
    setFlags((f) => {
      const next = { ...f }
      delete next[boxKey(editing.box)]
      return next
    })
    setEditing(null)
  }

  const applyPropagation = (chosen: ScanItem[]) => {
    if (!propagate) return
    setFlags((f) => {
      let next = { ...f }
      for (const b of chosen) {
        next = setFlagWithDuplicates(
          {
            box: b.box,
            icon_id: b.icon_id,
            type: "wrong_item",
            shown: { item_id: b.id, name: b.name },
            corrected: propagate.corrected,
          },
          next
        )
      }
      return next
    })
    setPropagate(null)
  }

  const submit = async () => {
    if (!flagList.length) return
    setSaving(true)
    try {
      const res = await fetch("/api/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_ts: ts, flags: flagList }),
      })
      const data = (await res.json()) as { ok: boolean; report_id?: string }
      if (data.ok) {
        setSaved(data.report_id ?? "saved")
        setFlags({})
      }
    } catch {
      /* backend offline */
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span className="tabular-nums text-muted-foreground">{formatSessionTs(ts)}</span>
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <span className="inline-block size-2.5 rounded-sm border-2 border-emerald-500" />
          identified <span className="text-foreground">{result.identified}</span>
        </span>
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <span className="inline-block size-2.5 rounded-sm border-2 border-red-500" />
          unidentified <span className="text-foreground">{result.unidentified.length}</span>
        </span>
        <span className="text-muted-foreground">
          total <span className="font-medium text-foreground">₽{RUB(result.total)}</span>
        </span>

        <div className="ml-auto flex items-center gap-2">
          {saved && !flagList.length && (
            <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400">
              <Check className="size-3.5" /> Report saved ({saved})
            </span>
          )}
          <button
            type="button"
            onClick={() => void submit()}
            disabled={!flagList.length || saving}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition-colors",
              flagList.length && !saving
                ? "border-amber-500/50 bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 dark:text-amber-400"
                : "text-muted-foreground"
            )}
          >
            {saving && <Loader2 className="size-3.5 animate-spin" />}
            Save report{flagList.length ? ` (${flagList.length})` : ""}
          </button>
        </div>
      </div>

      <p className="text-xs text-muted-foreground">
        Click any box to report what it should be — searches the catalog. Reports are saved
        locally for now (not sent), and never change the link map.
      </p>

      {/* Fit the whole screenshot in the panel; boxes overlay it 1:1 via percentages. */}
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto rounded-lg border bg-muted/30 p-2">
        <div className="relative inline-block">
          <img
            src={`/api/raw/${ts}`}
            alt={`Session ${ts}`}
            onLoad={(e) =>
              setNat({
                w: e.currentTarget.naturalWidth,
                h: e.currentTarget.naturalHeight,
              })
            }
            className="block max-h-full max-w-full select-none"
          />
          {nat && (
            <div className="absolute inset-0">
              {result.unidentified.map((it, i) => (
                <Box
                  key={`u-${i}`}
                  item={it}
                  nat={nat}
                  identified={false}
                  flag={flags[boxKey(it.box)]}
                  onClick={() => setEditing(it)}
                />
              ))}
              {result.items.map((it, i) => (
                <Box
                  key={`i-${i}`}
                  item={it}
                  nat={nat}
                  identified
                  flag={flags[boxKey(it.box)]}
                  onClick={() => setEditing(it)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {editing && (
        <CorrectionDialog
          ts={ts}
          item={editing}
          existing={flags[boxKey(editing.box)]}
          onClose={() => setEditing(null)}
          onSave={saveFlag}
          onClear={clearFlag}
        />
      )}

      {propagate && (
        <PropagateDialog
          ts={ts}
          name={propagate.corrected.name}
          boxes={propagate.boxes}
          preselected={propagate.preselected}
          onApply={(chosen) => applyPropagation(chosen)}
          onSkip={() => setPropagate(null)}
        />
      )}
    </div>
  )
}

export default AnalysisPanel
