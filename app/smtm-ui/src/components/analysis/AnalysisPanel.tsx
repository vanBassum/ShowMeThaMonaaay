import { useState } from "react"
import { ScanSearch } from "lucide-react"

import { cn, formatSessionTs } from "@/lib/utils"
import { useServerState, type ScanItem } from "@/lib/server-state"
import type { NavId } from "@/components/shell/nav"

const RUB = (n: number) => n.toLocaleString("en-US")

/** One detection drawn over the screenshot. Boxes are in source-image pixels, so we
 *  position them as percentages of the natural size — resolution-independent and
 *  exact regardless of how the image is scaled to fit. */
function Box({
  item,
  nat,
  identified,
}: {
  item: ScanItem
  nat: { w: number; h: number }
  identified: boolean
}) {
  const [x0, y0, x1, y1] = item.box
  const style = {
    left: `${(x0 / nat.w) * 100}%`,
    top: `${(y0 / nat.h) * 100}%`,
    width: `${((x1 - x0) / nat.w) * 100}%`,
    height: `${((y1 - y0) / nat.h) * 100}%`,
  }
  const label = identified
    ? `${item.name}${item.per_slot != null ? ` · ₽${RUB(item.per_slot)}/sl` : ""}`
    : `unidentified (${item.icon_id})`
  return (
    <div
      className={cn(
        "group absolute border-2",
        identified
          ? "border-emerald-500/80 hover:bg-emerald-500/20"
          : "border-red-500/80 hover:bg-red-500/20"
      )}
      style={style}
      title={label}
    >
      <span
        className={cn(
          "pointer-events-none absolute -top-px left-0 hidden max-w-[40vw] -translate-y-full truncate rounded-t px-1 py-0.5 text-[10px] font-medium whitespace-nowrap text-white group-hover:block",
          identified ? "bg-emerald-600" : "bg-red-600"
        )}
      >
        {label}
      </span>
    </div>
  )
}

export function AnalysisPanel({ onNavigate }: { onNavigate: (id: NavId) => void }) {
  const { state } = useServerState()
  const ts = state?.ts ?? null
  const result = state?.result ?? null
  const [nat, setNat] = useState<{ w: number; h: number } | null>(null)

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

  const identified = result.items
  const unidentified = result.unidentified

  return (
    <div className="flex h-full flex-col gap-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
        <span className="tabular-nums text-muted-foreground">{formatSessionTs(ts)}</span>
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <span className="inline-block size-2.5 rounded-sm border-2 border-emerald-500" />
          identified <span className="text-foreground">{identified.length}</span>
        </span>
        <span className="flex items-center gap-1.5 text-muted-foreground">
          <span className="inline-block size-2.5 rounded-sm border-2 border-red-500" />
          unidentified <span className="text-foreground">{unidentified.length}</span>
        </span>
        <span className="ml-auto text-muted-foreground">
          total <span className="font-medium text-foreground">₽{RUB(result.total)}</span>
        </span>
      </div>

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
              {unidentified.map((it, i) => (
                <Box key={`u-${i}`} item={it} nat={nat} identified={false} />
              ))}
              {identified.map((it, i) => (
                <Box key={`i-${i}`} item={it} nat={nat} identified />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default AnalysisPanel
