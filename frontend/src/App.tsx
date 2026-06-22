import { Outlet } from 'react-router-dom'
import SideNav from './components/SideNav'

export default function App() {
  return (
    <div className="min-h-screen flex bg-bg-page text-on-surface font-body-md selection:bg-rune-quest selection:text-on-primary">
      <SideNav />
      <div className="flex-1 md:ml-64 min-w-0">
        <Outlet />
      </div>
    </div>
  )
}
