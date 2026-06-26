import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react"

import { useServerState, type ScanItem } from "./server-state"

/** A user's decision about a detection box. `corrected` set => "should be X" (carries the
 *  catalog facts so the scan list can re-value it); type "not_an_item" => false positive;
 *  type "missed_item" => a box the user drew over an item the detector missed (no detection
 *  behind it — `corrected` is the item they identified, ground-truth for training).
 *  Fixes are session-scoped (saved with the session); they never edit the link map. */
export type Flag = {
  box: [number, number, number, number]
  icon_id: string
  type: "wrong_item" | "not_an_item" | "missed_item"
  shown?: { item_id?: string; name?: string }
  corrected?: {
    item_id: string
    name: string
    short?: string
    value?: number
    width?: number
    height?: number
  }
}

export const boxKey = (b: number[]) => b.join(",")

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

type FixesValue = {
  flags: Record<string, Flag>
  flagList: Flag[]
  dirty: boolean
  saving: boolean
  /** Every detection on the loaded scan (identified + unidentified). */
  allBoxes: ScanItem[]
  /** Upsert flags; each is also applied to IoU-duplicate detections so a fix doesn't
   *  leave a twin behind. Marks the set dirty. */
  applyFlags: (flags: Flag[]) => void
  /** Remove the flags for these boxes. Marks dirty. */
  removeFlags: (boxes: number[][]) => void
  /** Persist the current fixes to the loaded session. */
  save: () => Promise<void>
}

const FixesContext = createContext<FixesValue>({
  flags: {},
  flagList: [],
  dirty: false,
  saving: false,
  allBoxes: [],
  applyFlags: () => {},
  removeFlags: () => {},
  save: async () => {},
})

/**
 * Holds the loaded session's "fixes" (box adjustments), shared across the app so the
 * Scan and Analysis views edit the same set. Loads when the session changes; the dialogs
 * in either view mutate it; "Save fixes" persists to /api/session/<ts>/fixes.
 */
export function FixesProvider({ children }: { children: ReactNode }) {
  const { state } = useServerState()
  const ts = state?.ts ?? null
  const result = state?.result ?? null

  const [flags, setFlags] = useState<Record<string, Flag>>({})
  const [dirty, setDirty] = useState(false)
  const [saving, setSaving] = useState(false)

  const allBoxes = useMemo(
    () => (result ? [...result.items, ...result.unidentified] : []),
    [result]
  )

  // Fixes belong to one session — load that session's saved fixes when it changes.
  useEffect(() => {
    if (!ts) {
      setFlags({})
      setDirty(false)
      return
    }
    let cancelled = false
    void (async () => {
      try {
        const res = await fetch(`/api/session/${ts}/fixes`)
        const data = (await res.json()) as { flags?: Flag[] }
        if (cancelled) return
        const rec: Record<string, Flag> = {}
        for (const f of data.flags ?? []) rec[boxKey(f.box)] = f
        setFlags(rec)
        setDirty(false)
      } catch {
        if (!cancelled) {
          setFlags({})
          setDirty(false)
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [ts])

  const applyFlags = useCallback(
    (incoming: Flag[]) => {
      setFlags((prev) => {
        const next = { ...prev }
        for (const flag of incoming) {
          next[boxKey(flag.box)] = flag
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
        }
        return next
      })
      setDirty(true)
    },
    [allBoxes]
  )

  const removeFlags = useCallback((boxes: number[][]) => {
    setFlags((prev) => {
      const next = { ...prev }
      for (const b of boxes) delete next[boxKey(b)]
      return next
    })
    setDirty(true)
  }, [])

  const save = useCallback(async () => {
    if (!ts) return
    setSaving(true)
    try {
      const res = await fetch(`/api/session/${ts}/fixes`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ flags: Object.values(flags) }),
      })
      const data = (await res.json()) as { ok: boolean }
      if (data.ok) setDirty(false)
    } catch {
      /* backend offline */
    } finally {
      setSaving(false)
    }
  }, [ts, flags])

  const flagList = useMemo(() => Object.values(flags), [flags])

  const value: FixesValue = {
    flags,
    flagList,
    dirty,
    saving,
    allBoxes,
    applyFlags,
    removeFlags,
    save,
  }
  return <FixesContext.Provider value={value}>{children}</FixesContext.Provider>
}

// eslint-disable-next-line react-refresh/only-export-components
export function useFixes() {
  return useContext(FixesContext)
}
