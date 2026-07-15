import { crossfade, fade } from 'svelte/transition'
import { quintOut } from 'svelte/easing'
import { dur } from './motion.svelte'

// One shared crossfade pair for task chips. Because it is a single instance imported by
// every quadrant, a chip that leaves one quadrant (out:taskSend) and arrives in another
// (in:taskReceive) with the same key visibly FLIES across the matrix — Svelte's
// signature move-between-lists transition. Duration is a getter so it honours
// prefers-reduced-motion at transition time.
export const [taskSend, taskReceive] = crossfade({
  duration: () => dur(320),
  easing: quintOut,
  fallback: (node) => fade(node, { duration: dur(160) }),
})
