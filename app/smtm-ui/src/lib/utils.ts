import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** A session id "20260626-104125" -> "2026-06-26 10:41:25" (the raw id otherwise). */
export function formatSessionTs(ts: string): string {
  const m = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/.exec(ts)
  if (!m) return ts
  const [, y, mo, d, h, mi, s] = m
  return `${y}-${mo}-${d} ${h}:${mi}:${s}`
}
