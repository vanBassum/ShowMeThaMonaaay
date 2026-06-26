import { useState } from "react"
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
  const [propagate, setPropagate] = useState<{
    iconId: string
    corrected: NonNullable<Flag["corrected"]>
    boxes: ScanItem[]
    preselected: Set<string> // boxKeys checked by default (the not-yet-adjusted ones)
  } | null>(null)

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
        Click any box to fix what it should be — searches the catalog. Fixes are saved with
        this session and never change the link map. (Sharing a report comes later.)
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
