// Shared, app-wide state for the long maintenance jobs (compaction, re-embed, community
// detection, inbox auto-file). The server runs each on a background thread and is the
// source of truth; this store mirrors GET /api/jobs so a running job's state survives
// navigation, remounts, and tab switches — the whole point of the fix. Same rune-store
// pattern as appstate.svelte.ts.

import { api, type Job } from './api'

export const jobsState = $state<{ byKind: Record<string, Job> }>({ byKind: {} })

let polling = false

// Pull the latest status for every kind. Best-effort: a failed poll must not surface as
// an app error (the button just keeps its last known state until the next tick).
export async function refreshJobs(): Promise<void> {
  try {
    const { jobs } = await api.jobsStatus()
    jobsState.byKind = jobs
  } catch {
    /* ignore: transient poll failure */
  }
}

export function jobFor(kind: string): Job | undefined {
  return jobsState.byKind[kind]
}

export function anyRunning(): boolean {
  return Object.values(jobsState.byKind).some((j) => j.status === 'running')
}

// Poll /api/jobs every 2s while any job runs, then stop. Idempotent: only one loop runs
// at a time, so callers can fire this on mount and after starting a job without stacking
// timers. Each tick refreshes the shared store, so every mounted view updates together.
export function startPollingWhileRunning(): void {
  if (polling) return
  polling = true
  const tick = async () => {
    await refreshJobs()
    if (anyRunning()) {
      window.setTimeout(tick, 2000)
    } else {
      polling = false
    }
  }
  window.setTimeout(tick, 2000)
}
