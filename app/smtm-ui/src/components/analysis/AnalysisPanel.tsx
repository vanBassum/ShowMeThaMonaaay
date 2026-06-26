import { useEffect, useMemo, useState } from "react"
import { Check, Copy, Loader2, ScanSearch } from "lucide-react"

import { cn, formatSessionTs } from "@/lib/utils"
import { useServerState, type ScanItem } from "@/lib/server-state"
import type { NavId } from "@/components/shell/nav"
import { CorrectionDialog, type Flag } from "./CorrectionDialog"

const RUB = (n: number) => n.toLocaleString("en-US")
const boxKey = (b: number[]) => b.join(",")

/** One detection drawn over the screenshot. Boxes are in source-image pixels, so we
 *  position them as percentages of the natural size — exact at any display scale.
 *  Click to report what the box should be. Colour states:
 *    emerald/red = identified/unidentified (unflagged)
 *    amber (solid) = flagged "should be X"   ·   red (solid) = flagged "not an item"
 *    orange (dashed) = candidate — same detected id as something you already fixed */
function Box({
  item,
  nat,
  identified,
  flag,
  candidate,
  onClick,
}: {
  item: ScanItem
  nat: { w: number; h: number }
  identified: boolean
  flag?: Flag
  candidate?: string
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
    : candidate
      ? `same id → ${candidate}?`
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
          : candidate
            ? "border-dashed border-orange-400 bg-orange-400/25 hover:bg-orange-400/35"
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
          flagged || candidate ? "block" : "hidden group-hover:block",
          flagged
            ? flag.type === "not_an_item"
              ? "bg-red-600"
              : "bg-amber-600"
            : candidate
              ? "bg-orange-500"
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
 *  the same item — so a user can fix all duplicates in one click. */
function PropagateDialog({
  ts,
  name,
  boxes,
  onApply,
  onSkip,
}: {
  ts: string
  name: string
  boxes: ScanItem[]
  onApply: () => void
  onSkip: () => void
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onSkip}
    >
      <div
        className="w-full max-w-md rounded-lg border bg-card p-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 text-sm font-medium">
          <Copy className="size-4 text-orange-500" />
          {boxes.length} other box{boxes.length === 1 ? "" : "es"} have the same detected
          id
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          They're highlighted orange. Are they also{" "}
          <span className="font-medium text-foreground">{name}</span>?
        </p>
        <div className="mt-3 flex flex-wrap gap-2">
          {boxes.map((it, i) => (
            <img
              key={i}
              src={`/api/crop/${ts}?box=${it.box.join(",")}`}
              alt=""
              className="size-12 rounded border bg-muted object-contain"
            />
          ))}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={onSkip}
            className="rounded-md border px-3 py-1.5 text-xs text-muted-foreground hover:bg-accent"
          >
            Just this one
          </button>
          <button
            type="button"
            onClick={onApply}
            className="rounded-md border border-amber-500/50 bg-amber-500/10 px-3 py-1.5 text-xs font-medium text-amber-600 hover:bg-amber-500/20 dark:text-amber-400"
          >
            Mark all {boxes.length} as {name}
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

  // icon-id -> the correction a user already chose for it (drives the orange "same id"
  // candidate hints on still-unflagged boxes).
  const correctionByIcon = useMemo(() => {
    const m: Record<string, { item_id: string; name: string }> = {}
    for (const f of Object.values(flags)) {
      if (f.type === "wrong_item" && f.corrected) m[f.icon_id] = f.corrected
    }
    return m
  }, [flags])

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

  const setFlag = (flag: Flag, prev?: Record<string, Flag>) => ({
    ...(prev ?? flags),
    [boxKey(flag.box)]: flag,
  })

  const saveFlag = (flag: Flag) => {
    const next = setFlag(flag)
    setFlags(next)
    setEditing(null)
    setSaved(null)
    // Offer to apply the same fix to other boxes YOLO gave the same icon-id.
    if (flag.type === "wrong_item" && flag.corrected) {
      const siblings = allBoxes.filter(
        (b) => b.icon_id === flag.icon_id && !next[boxKey(b.box)]
      )
      if (siblings.length) {
        setPropagate({ iconId: flag.icon_id, corrected: flag.corrected, boxes: siblings })
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

  const applyPropagation = () => {
    if (!propagate) return
    setFlags((f) => {
      const next = { ...f }
      for (const b of propagate.boxes) {
        next[boxKey(b.box)] = {
          box: b.box,
          icon_id: b.icon_id,
          type: "wrong_item",
          shown: { item_id: b.id, name: b.name },
          corrected: propagate.corrected,
        }
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
                  candidate={
                    !flags[boxKey(it.box)]
                      ? correctionByIcon[it.icon_id]?.name
                      : undefined
                  }
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
                  candidate={
                    !flags[boxKey(it.box)]
                      ? correctionByIcon[it.icon_id]?.name
                      : undefined
                  }
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
          onApply={applyPropagation}
          onSkip={() => setPropagate(null)}
        />
      )}
    </div>
  )
}

export default AnalysisPanel
