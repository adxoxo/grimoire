import { createContext, useContext, useState, type ReactNode } from 'react'

interface AppState {
  scribeOpen: boolean
  setScribeOpen: (open: boolean) => void
  graphVersion: number // bump to make graph-backed views refetch
  refreshGraph: () => void
}

const Ctx = createContext<AppState | null>(null)

export function AppStateProvider({ children }: { children: ReactNode }) {
  const [scribeOpen, setScribeOpen] = useState(false)
  const [graphVersion, setGraphVersion] = useState(0)
  return (
    <Ctx.Provider
      value={{ scribeOpen, setScribeOpen, graphVersion, refreshGraph: () => setGraphVersion((v) => v + 1) }}
    >
      {children}
    </Ctx.Provider>
  )
}

export function useAppState(): AppState {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAppState must be used within AppStateProvider')
  return ctx
}
