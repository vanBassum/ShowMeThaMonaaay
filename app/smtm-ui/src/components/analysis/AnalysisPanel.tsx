import { useEffect, useState } from "react"
import { Check, Loader2, ScanSearch } from "lucide-react"

import { cn, formatSessionTs } from "@/lib/utils"
import { useServerState, type ScanItem } from "@/lib/server-state"
import type { NavId } from "@/components/shell/nav"
import { CorrectionDialog, type Flag } from "./CorrectionDialog"

const RUB = (n: number) => n.toLocaleString("en-US")
const boxKey = (b: number[]) => b.join(",")

/** One detection drawn over the screenshot. Boxes are in source-image pixels, so we
 *  position them as percentages of the natural size — exact at any display scale.
 *  Click to report what the box should be (flag); flagged boxes turn amber. */
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
          flagged ? "block" : "hidden group-hover:block",
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

export function AnalysisPanel({ onNavigate }: { onNavigate: (id: NavId) => void }) {
  const { state } = useServerState()
  const ts = state?.ts ?? null
  const result = state?.result ?? null
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null)
  const [flags, setFlags] = useState<Record<string, Flag>>({})
  const [editing, setEditing] = useState<ScanItem | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<string | null>(null)

  // Flags belong to one screenshot — drop them when the loaded session changes.
  useEffect(() => {
    setFlags({})
    setSaved(null)
  }, [ts])

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

  const saveFlag = (flag: Flag) => {
    setFlags((f) => ({ ...f, [boxKey(flag.box)]: flag }))
    setEditing(null)
    setSaved(null)
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
    </div>
  )
}

export default AnalysisPanel
