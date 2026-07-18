import { localDate } from './theme'

/** The local calendar date n days away from d (YYYY-MM-DD in, YYYY-MM-DD out). */
export function addDays(d: string, n: number): string {
  const dt = new Date(`${d}T00:00:00`)
  dt.setDate(dt.getDate() + n)
  return localDate(dt)
}

/** Human name for a planner day: today / yesterday / tomorrow, else "Saturday, Jul 19". */
export function dayLabel(d: string): string {
  const today = localDate()
  if (d === today) return 'today'
  if (d === addDays(today, -1)) return 'yesterday'
  if (d === addDays(today, 1)) return 'tomorrow'
  return new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { weekday: 'long', month: 'short', day: 'numeric' })
}
