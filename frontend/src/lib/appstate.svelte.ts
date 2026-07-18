// App-wide UI state shared across views. Svelte 5 runes let a plain exported object be
// reactive everywhere it is read — no context provider boilerplate (the React version
// needed AppStateProvider + useContext for exactly this).

export const appState = $state({
  scribeOpen: false,
  // The quick-capture dialog (thought + attachments), opened from the pill nav.
  captureOpen: false,
  // Bumped to make graph-backed views refetch after a write (scribe / delete / compact).
  graphVersion: 0,
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

export function refreshGraph(): void {
  appState.graphVersion++
}
