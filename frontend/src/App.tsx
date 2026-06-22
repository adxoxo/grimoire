import { Outlet } from 'react-router-dom'
import SideNav from './components/SideNav'
import ScribeModal from './components/ScribeModal'
import { AppStateProvider } from './state'

export default function App() {
  return (
    <AppStateProvider>
      <div className="min-h-screen flex bg-bg-page text-on-surface font-body-md selection:bg-rune-quest selection:text-on-primary">
        <SideNav />
        <div className="flex-1 md:ml-64 min-w-0">
          <Outlet />
        </div>
        <ScribeModal />
      </div>
    </AppStateProvider>
  )
}
