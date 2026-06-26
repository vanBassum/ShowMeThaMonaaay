import { useState } from "react"
import { ScanSearch } from "lucide-react"

import { AnalysisPanel } from "@/components/analysis/AnalysisPanel"
import { ScanPanel } from "@/components/scan/ScanPanel"
import { SessionsModal } from "@/components/sessions/SessionsModal"
import { useServerState } from "@/lib/server-state"
import { cn, formatSessionTs } from "@/lib/utils"
import { LeftRail } from "./LeftRail"
import { ModelStatus } from "./ModelStatus"
import { NAV_ITEMS, type NavId } from "./nav"

const RUB = (n: number) => n.toLocaleString("en-US")

/** The currently-loaded session, shown in the top bar across every tab so it's always
 *  clear which scan you're looking at. Clicking it jumps to the Analysis view. Falls
 *  back to the section label when nothing is loaded. */
function HeaderTitle({
  fallback,
  onOpenAnalysis,
}: {
  fallback: string
  onOpenAnalysis: () => void
}) {
  const { state } = useServerState()
  const ts = state?.ts
  const result = state?.result
  if (!ts || !result) {
    return <h1 className="text-sm font-medium">{fallback}</h1>
  }
  return (
    <button
      type="button"
      onClick={onOpenAnalysis}
      title="Open analysis"
      className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-xs transition-colors hover:bg-amber-500/20"
    >
      <ScanSearch className="size-3.5 text-amber-500" />
      <span className="font-medium tabular-nums">{formatSessionTs(ts)}</span>
      <span className="text-muted-foreground">
        {result.identified}/{result.detections}
      </span>
      <span className="font-medium tabular-nums">₽{RUB(result.total)}</span>
    </button>
  )
}

export function AppShell() {
  const [active, setActive] = useState<NavId>("scan")
  const [sessionsOpen, setSessionsOpen] = useState(false)
  const item = NAV_ITEMS.find((i) => i.id === active) ?? NAV_ITEMS[0]
  const Icon = item.icon
  const openSessions = () => setSessionsOpen(true)

  return (
    <div className="flex h-svh overflow-hidden bg-background text-foreground">
      <LeftRail active={active} onSelect={setActive} onOpenSessions={openSessions} />

      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <header className="flex h-12 shrink-0 items-center gap-2 border-b px-4">
          <Icon className={cn("size-4", "text-amber-500")} />
          <HeaderTitle
            fallback={item.label}
            onOpenAnalysis={() => setActive("analysis")}
          />
          <div className="ml-auto">
            <ModelStatus />
          </div>
        </header>

        {/* The "big screen" — each section renders its own content here. */}
        <main className="min-h-0 flex-1 overflow-hidden p-4">
          {active === "scan" ? (
            <ScanPanel />
          ) : active === "analysis" ? (
            <AnalysisPanel onOpenSessions={openSessions} />
          ) : (
            <div className="flex h-full items-center justify-center rounded-lg border border-dashed text-center">
              <div className="max-w-sm px-6">
                <Icon className="mx-auto mb-3 size-8 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">{item.blurb}</p>
              </div>
            </div>
          )}
        </main>
      </div>

      <SessionsModal open={sessionsOpen} onOpenChange={setSessionsOpen} />
    </div>
  )
}

export default AppShell
