/**
 * Keep a view fresh without manual reloads: refetch on a steady interval AND the
 * instant the tab regains focus/visibility. Only fires while the tab is visible, so
 * background tabs do not hammer the API. Pass `enabled` as a getter returning false to
 * pause (e.g. while the user is mid-drag or a dialog is open) so a refetch never
 * clobbers in-flight work.
 *
 * Call this once at the top of a component's <script> (component-init context).
 */
export function liveRefresh(
  refetch: () => void,
  opts: { intervalMs?: number; enabled?: () => boolean } = {},
): void {
  const intervalMs = opts.intervalMs ?? 20000

  $effect(() => {
    // Read the getter inside the effect so toggling it re-subscribes.
    const enabled = opts.enabled ? opts.enabled() : true
    if (!enabled) return

    const fire = () => {
      if (document.visibilityState === 'visible') refetch()
    }
    const id = window.setInterval(fire, intervalMs)
    window.addEventListener('focus', fire)
    document.addEventListener('visibilitychange', fire)
    return () => {
      clearInterval(id)
      window.removeEventListener('focus', fire)
      document.removeEventListener('visibilitychange', fire)
    }
  })
}
