import { useEffect, useRef } from 'react'

/**
 * Keep a view fresh without manual reloads: refetch on a steady interval AND the
 * instant the tab regains focus/visibility. Only fires while the tab is visible, so
 * background tabs do not hammer the API. Pass `enabled: false` to pause (e.g. while
 * the user is mid-drag or editing) so a refetch never clobbers in-flight work.
 */
export function useLiveRefresh(
  refetch: () => void,
  opts: { intervalMs?: number; enabled?: boolean } = {},
): void {
  const { intervalMs = 20000, enabled = true } = opts
  const ref = useRef(refetch)
  ref.current = refetch

  useEffect(() => {
    if (!enabled) return
    const fire = () => { if (document.visibilityState === 'visible') ref.current() }
    const id = window.setInterval(fire, intervalMs)
    window.addEventListener('focus', fire)
    document.addEventListener('visibilitychange', fire)
    return () => {
      clearInterval(id)
      window.removeEventListener('focus', fire)
      document.removeEventListener('visibilitychange', fire)
    }
  }, [enabled, intervalMs])
}
