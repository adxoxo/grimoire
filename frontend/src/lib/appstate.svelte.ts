// App-wide UI state shared across views. Svelte 5 runes let a plain exported object be
// reactive everywhere it is read — no context provider boilerplate (the React version
// needed AppStateProvider + useContext for exactly this).

import { localDate } from './theme'

export const appState = $state({
  scribeOpen: false,
  // The quick-capture dialog (thought + attachments), opened from the pill nav.
  captureOpen: false,
  // The transmute dialog (planner chat), opened from the pill nav on planner pages.
  transmuteOpen: false,
  // The day the planner surfaces (Today board + Flow) are looking at, shared so
  // switching day in one carries to the other. YYYY-MM-DD, local.
  plannerDate: localDate(),
  // Bumped to make graph-backed views refetch after a write (scribe / delete / compact).
  graphVersion: 0,
  // Bumped after a transmute action so planner views reload immediately.
  plannerVersion: 0,
})

export function openScribe(): void {
  appState.scribeOpen = true
}

export function closeScribe(): void {
  appState.scribeOpen = false
}

export function openCapture(): void {
  appState.captureOpen = true
}

export function closeCapture(): void {
  appState.captureOpen = false
}

export function openTransmute(): void {
  appState.transmuteOpen = true
}

export function closeTransmute(): void {
  appState.transmuteOpen = false
}

export function refreshPlanner(): void {
  appState.plannerVersion++
}

export function refreshGraph(): void {
  appState.graphVersion++
}
