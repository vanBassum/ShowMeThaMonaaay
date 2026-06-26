import { useRef, useState } from "react"
import { Check, Copy, Loader2, ScanSearch } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { cn, formatSessionTs } from "@/lib/utils"
import { useServerState, type ScanItem } from "@/lib/server-state"
import { boxKey, useFixes, type Flag } from "@/lib/fixes"
import { CorrectionDialog } from "./CorrectionDialog"

const RUB = (n: number) => n.toLocaleString("en-US")

type BoxKind = "identified" | "unidentified" | "wrong_item" | "not_an_item" | "missed_item"

// border/fill for the box · background for its hover label
const BOX_STYLE: Record<BoxKind, { box: string; tag: string }> = {
  identified: { box: "border-emerald-500/80 hover:bg-emerald-500/20", tag: "bg-emerald-600" },
  unidentified: { box: "border-red-500/80 hover:bg-red-500/20", tag: "bg-red-600" },
  wrong_item: { box: "border-amber-400 bg-amber-400/25", tag: "bg-amber-600" },
  not_an_item: { box: "border-red-400 bg-red-500/25", tag: "bg-red-600" },
  missed_item: { box: "border-sky-400 bg-sky-400/25", tag: "bg-sky-600" },
}

/** One box drawn over the screenshot. Boxes are in source-image pixels, so we position
 *  them as percentages of the natural size — exact at any display scale. Click to fix what
 *  the box should be. Colour states (labels are hover-only):
 *    emerald/red = identified/unidentified  ·  amber = "should be X"  ·  red = "not an item"
 *    sky         = a missed item the user added */
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
  const kind: BoxKind = flag ? flag.type : identified ? "identified" : "unidentified"
  const label =
    kind === "missed_item"
      ? `+ ${flag?.corrected?.name ?? "item"}`
      : kind === "wrong_item"
        ? `→ ${flag?.corrected?.name ?? ""}`
        : kind === "not_an_item"
          ? "✕ not an item"
          : identified
            ? `${item.name}${item.per_slot != null ? ` · ₽${RUB(item.per_slot)}/sl` : ""}`
            : `unidentified (${item.icon_id})`
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn("group absolute border-2 transition-colors", BOX_STYLE[kind].box)}
      style={style}
      title={label}
    >
      <span
        className={cn(
          "pointer-events-none absolute -top-px left-0 max-w-[40vw] -translate-y-full truncate rounded-t px-1 py-0.5 text-[10px] font-medium whitespace-nowrap text-white",
          "hidden group-hover:block", // label hover-only to keep the screenshot clear
          BOX_STYLE[kind].tag
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
    <Dialog open onOpenChange={(o) => !o && onSkip()}>
      <DialogContent className="flex max-h-[80vh] flex-col sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-sm">
            <Copy className="size-4 shrink-0 text-orange-500" />
            {boxes.length} other box{boxes.length === 1 ? "" : "es"} have the same detected
            id
          </DialogTitle>
          <DialogDescription>
            Deselect any that are <span className="font-medium">not</span>{" "}
            <span className="font-medium text-foreground">{name}</span>.
          </DialogDescription>
        </DialogHeader>
        {/* p-1 so the selected crops' outer ring isn't clipped by the scroll container
            (overflow-y-auto also clips horizontal overflow). */}
        <div className="grid min-h-0 flex-1 grid-cols-6 gap-1.5 overflow-y-auto p-1">
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
        <DialogFooter>
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => onApply(chosen)}
            disabled={!chosen.length}
            className="border-amber-500/50 bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 hover:text-amber-700 dark:text-amber-400"
          >
            Mark {chosen.length} as {name}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

export function AnalysisPanel({ onOpenSessions }: { onOpenSessions: () => void }) {
  const { state } = useServerState()
  const { flags, flagList, dirty, saving, allBoxes, applyFlags, removeFlags, save } =
    useFixes()
  const ts = state?.ts ?? null
  const result = state?.result ?? null
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null)
  const [editing, setEditing] = useState<ScanItem | null>(null)
  // A box the user drew over a missed item (or an already-added one they re-opened), being
  // identified in the catalog dialog.
  const [missed, setMissed] = useState<ScanItem | null>(null)
  // Live rubber-band while dragging a new box, in overlay-local pixels.
  const [draw, setDraw] = useState<{ ax: number; ay: number; bx: number; by: number } | null>(
    null
  )
  const overlayRef = useRef<HTMLDivElement>(null)
  const [propagate, setPropagate] = useState<{
    iconId: string
    corrected: NonNullable<Flag["corrected"]>
    boxes: ScanItem[]
    preselected: Set<string> // boxKeys checked by default (the not-yet-adjusted ones)
  } | null>(null)

  // The user's manually-added missed items (drawn boxes), rendered as their own overlay.
  const missedFlags = flagList.filter((f) => f.type === "missed_item")
  const addedValue = missedFlags.reduce((s, f) => s + (f.corrected?.value ?? 0), 0)

  if (!ts || !result) {
    return (
      <div className="flex h-full items-center justify-center rounded-lg border border-dashed text-center">
        <div className="max-w-sm px-6">
          <ScanSearch className="mx-auto mb-3 size-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            No session loaded. Open one from{" "}
            <button
              type="button"
              onClick={onOpenSessions}
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

  const saveFlag = (flag: Flag) => {
    applyFlags([flag])
    setEditing(null)
    // Offer to apply the same fix to other boxes YOLO gave the same icon-id. Already-
    // adjusted siblings are shown too but start deselected (so we don't overwrite them).
    if (flag.type === "wrong_item" && flag.corrected) {
      const siblings = allBoxes.filter(
        (b) => b.icon_id === flag.icon_id && boxKey(b.box) !== boxKey(flag.box)
      )
      const preselected = new Set(
        siblings.filter((b) => !flags[boxKey(b.box)]).map((b) => boxKey(b.box))
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
    removeFlags([editing.box])
    setEditing(null)
  }

  const applyPropagation = (chosen: ScanItem[]) => {
    if (!propagate) return
    applyFlags(
      chosen.map((b) => ({
        box: b.box,
        icon_id: b.icon_id,
        type: "wrong_item" as const,
        shown: { item_id: b.id, name: b.name },
        corrected: propagate.corrected,
      }))
    )
    setPropagate(null)
  }

  const saveMissed = (flag: Flag) => {
    applyFlags([flag])
    setMissed(null)
  }
  const clearMissed = () => {
    if (missed) removeFlags([missed.box])
    setMissed(null)
  }

  // --- drawing a box over a missed item -------------------------------------------------
  // Map a pointer event to overlay-local pixels (clamped to the image).
  const localXY = (e: React.PointerEvent) => {
    const r = overlayRef.current!.getBoundingClientRect()
    return {
      x: Math.max(0, Math.min(r.width, e.clientX - r.left)),
      y: Math.max(0, Math.min(r.height, e.clientY - r.top)),
    }
  }
  const onDrawDown = (e: React.PointerEvent) => {
    // Only start on empty space (clicks on a box bubble from the child button) + left mouse.
    if (e.button !== 0 || e.target !== e.currentTarget) return
    const { x, y } = localXY(e)
    overlayRef.current?.setPointerCapture(e.pointerId)
    setDraw({ ax: x, ay: y, bx: x, by: y })
  }
  const onDrawMove = (e: React.PointerEvent) => {
    if (!draw) return
    const { x, y } = localXY(e)
    setDraw((d) => (d ? { ...d, bx: x, by: y } : d))
  }
  const onDrawUp = (e: React.PointerEvent) => {
    if (!draw || !nat) return setDraw(null)
    overlayRef.current?.releasePointerCapture(e.pointerId)
    const r = overlayRef.current!.getBoundingClientRect()
    const [lx0, lx1] = [Math.min(draw.ax, draw.bx), Math.max(draw.ax, draw.bx)]
    const [ly0, ly1] = [Math.min(draw.ay, draw.by), Math.max(draw.ay, draw.by)]
    setDraw(null)
    if (lx1 - lx0 < 6 || ly1 - ly0 < 6) return // too small -> treat as a stray click
    // overlay-local px -> source-image px
    const box: [number, number, number, number] = [
      Math.round((lx0 / r.width) * nat.w),
      Math.round((ly0 / r.height) * nat.h),
      Math.round((lx1 / r.width) * nat.w),
      Math.round((ly1 / r.height) * nat.h),
    ]
    setMissed({ box, icon_id: "", source: null })
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
        {missedFlags.length > 0 && (
          <span className="flex items-center gap-1.5 text-muted-foreground">
            <span className="inline-block size-2.5 rounded-sm border-2 border-sky-400" />
            added <span className="text-foreground">{missedFlags.length}</span>
          </span>
        )}
        <span className="text-muted-foreground">
          total{" "}
          <span className="font-medium text-foreground">
            ₽{RUB(result.total + addedValue)}
          </span>
        </span>

        <div className="ml-auto flex items-center gap-2">
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
      </div>

      <p className="text-xs text-muted-foreground">
        Click any box to fix what it should be. <span className="text-sky-600 dark:text-sky-400">
        Drag over empty space</span> to box an item the detector missed, then name it. Fixes
        are saved with this session and never change the link map.
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
            <div
              ref={overlayRef}
              onPointerDown={onDrawDown}
              onPointerMove={onDrawMove}
              onPointerUp={onDrawUp}
              className="absolute inset-0 cursor-crosshair touch-none"
            >
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
              {/* user-added missed items — click to re-identify or remove */}
              {missedFlags.map((f, i) => (
                <Box
                  key={`m-${i}`}
                  item={{ box: f.box, icon_id: "", source: "added" }}
                  nat={nat}
                  identified={false}
                  flag={f}
                  onClick={() => setMissed({ box: f.box, icon_id: "", source: "added" })}
                />
              ))}
              {/* live rubber-band while drawing a new box */}
              {draw && (
                <div
                  className="pointer-events-none absolute border-2 border-dashed border-sky-400 bg-sky-400/20"
                  style={{
                    left: Math.min(draw.ax, draw.bx),
                    top: Math.min(draw.ay, draw.by),
                    width: Math.abs(draw.bx - draw.ax),
                    height: Math.abs(draw.by - draw.ay),
                  }}
                />
              )}
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

      {missed && (
        <CorrectionDialog
          ts={ts}
          item={missed}
          existing={flags[boxKey(missed.box)]}
          forMissed
          onClose={() => setMissed(null)}
          onSave={saveMissed}
          onClear={clearMissed}
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
