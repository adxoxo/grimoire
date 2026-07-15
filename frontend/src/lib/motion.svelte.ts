// Single source of truth for "should we animate". Svelte's JS transitions don't read
// prefers-reduced-motion on their own, so every transition duration in the app flows
// through dur() — which collapses to 0 when the user asked for reduced motion.

export const motion = $state({ reduced: false })

if (typeof window !== 'undefined' && window.matchMedia) {
  const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
  motion.reduced = mq.matches
  mq.addEventListener('change', () => (motion.reduced = mq.matches))
}

/** A transition duration, or 0 when the user prefers reduced motion. */
export function dur(ms: number): number {
  return motion.reduced ? 0 : ms
}
