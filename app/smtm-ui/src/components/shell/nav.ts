import { Crosshair, ScanSearch, Settings, type LucideIcon } from "lucide-react"

export type NavId = "scan" | "analysis" | "settings"

export type NavItem = {
  id: NavId
  label: string
  icon: LucideIcon
  /** One-line description shown in the big content area. */
  blurb: string
}

// The product's top-level sections. `scan` is the default (live valuer); the rest are
// saved sessions, the per-session analysis/report view, and settings. Wire each to real
// content as we migrate features in.
export const NAV_ITEMS: NavItem[] = [
  {
    id: "scan",
    label: "Scan",
    icon: Crosshair,
    blurb: "Press F2 in-game to capture your inventory and rank items by ₽/slot.",
  },
  {
    id: "analysis",
    label: "Analysis",
    icon: ScanSearch,
    blurb: "Open a session to inspect its screenshot with detection boxes overlaid.",
  },
  {
    id: "settings",
    label: "Settings",
    icon: Settings,
    blurb: "Model, prices, and app preferences.",
  },
]
