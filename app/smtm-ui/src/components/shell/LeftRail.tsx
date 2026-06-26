import { Moon, Sun, Target } from "lucide-react"

import { useTheme } from "@/components/theme-provider"
import { cn } from "@/lib/utils"
import { NAV_ITEMS, type NavId, type NavItem } from "./nav"

const railButtonClass =
  "flex w-full flex-col items-center gap-1 rounded-md px-2 py-2 text-[11px] text-sidebar-foreground transition-colors hover:bg-sidebar-accent focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"

// Tarkov-ish amber accent for the active section.
const railButtonActiveClass =
  "bg-amber-500/15 font-medium text-amber-600 hover:bg-amber-500/20 dark:text-amber-400"

function RailButton({
  item,
  active,
  onSelect,
}: {
  item: NavItem
  active: boolean
  onSelect: (id: NavId) => void
}) {
  const { icon: Icon, label, id } = item
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      aria-current={active ? "page" : undefined}
      className={cn(railButtonClass, active && railButtonActiveClass)}
    >
      <Icon className="size-5" />
      <span className="leading-tight">{label}</span>
    </button>
  )
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const resolved =
    theme === "system"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
        ? "dark"
        : "light"
      : theme
  const Icon = resolved === "dark" ? Moon : Sun
  return (
    <button
      type="button"
      onClick={() => setTheme(resolved === "dark" ? "light" : "dark")}
      aria-label="Toggle theme"
      className={railButtonClass}
    >
      <Icon className="size-5" />
      <span className="leading-tight">Theme</span>
    </button>
  )
}

export function LeftRail({
  active,
  onSelect,
}: {
  active: NavId
  onSelect: (id: NavId) => void
}) {
  return (
    <aside className="flex w-20 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
      <div className="flex flex-col items-center gap-1 px-2 pt-3 pb-2">
        <Target className="size-7 text-amber-500" />
      </div>
      <div className="mx-2 mb-2 h-px bg-border" />
      <div className="flex flex-1 flex-col gap-1 overflow-y-auto px-2">
        {NAV_ITEMS.map((item) => (
          <RailButton
            key={item.id}
            item={item}
            active={item.id === active}
            onSelect={onSelect}
          />
        ))}
      </div>
      <div className="mx-2 my-2 h-px bg-border" />
      <div className="px-2 pb-2">
        <ThemeToggle />
      </div>
    </aside>
  )
}

export default LeftRail
