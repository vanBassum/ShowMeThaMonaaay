import { useCallback, useEffect, useState, type ReactNode } from "react"
import { AlertTriangle, Box, ChevronDown, Loader2 } from "lucide-react"

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"
import { useServerState, type ModelInfo } from "@/lib/server-state"

type ModelOption = {
  name: string
  present: boolean
  fingerprint: string | null
  classes: number | null
}

const triggerClass =
  "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium transition-colors hover:bg-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"

/** What to show on the trigger, derived from the live (SSE) model fetch state. */
function triggerContent(
  model: ModelInfo | null,
  connected: boolean
): { icon: ReactNode; text: string; cls: string } {
  if (!connected && !model)
    return { icon: <Loader2 className="size-3.5 animate-spin" />, text: "Connecting…", cls: "text-muted-foreground" }
  if (!model || model.state === "checking" || model.state === "downloading")
    return {
      icon: <Loader2 className="size-3.5 animate-spin" />,
      text: model?.state === "downloading" ? "Fetching model…" : "Checking model…",
      cls: "text-muted-foreground",
    }
  if (model.state === "error")
    return { icon: <AlertTriangle className="size-3.5" />, text: "Model error", cls: "text-destructive" }
  return { icon: <Box className="size-3.5 text-amber-500" />, text: model.name, cls: "text-foreground" }
}

/** Top-right model indicator + switcher. Shows fetch progress on first start,
 *  the active model name once ready, and a dropdown to switch between models. */
export function ModelStatus() {
  const { state, connected } = useServerState()
  const model = state?.model ?? null

  const [available, setAvailable] = useState<ModelOption[]>([])
  const [active, setActive] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const res = await fetch("/api/models")
      const data = (await res.json()) as { active: string; available: ModelOption[] }
      setAvailable(data.available ?? [])
      setActive(data.active ?? null)
    } catch {
      // backend offline — leave the list empty
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const select = async (name: string) => {
    if (name === active) return
    setActive(name) // optimistic; SSE will reflect the real fetch state
    try {
      await fetch("/api/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      })
    } finally {
      void refresh()
    }
  }

  const { icon, text, cls } = triggerContent(model, connected)
  const current = model?.state === "ready" ? model.name : active

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className={cn(triggerClass, cls)} title="Detector model">
        {icon}
        {text}
        <ChevronDown className="size-3.5 opacity-60" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="min-w-56">
        <DropdownMenuLabel className="text-xs text-muted-foreground">
          Detector model
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={current ?? ""}
          onValueChange={(v) => void select(v)}
        >
          {available.map((m) => (
            <DropdownMenuRadioItem
              key={m.name}
              value={m.name}
              className="flex-col items-start gap-0.5"
            >
              <span className="flex w-full items-center gap-2">
                <span className="flex-1">{m.name}</span>
                {!m.present && (
                  <span className="text-[10px] text-muted-foreground">
                    not downloaded
                  </span>
                )}
              </span>
              {m.classes != null && (
                <span className="text-[10px] text-muted-foreground">
                  {m.classes} items
                </span>
              )}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export default ModelStatus
