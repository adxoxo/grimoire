import { Link, useLocation } from 'react-router-dom'
import { RUNE, type NodeType } from '../theme'

interface NavItem {
  label: string
  icon: string
  iconColor: string
  type: NodeType | null // null = the full constellation (quest lines as spine)
}

const ITEMS: NavItem[] = [
  { label: RUNE.project.nav, icon: RUNE.project.icon, iconColor: RUNE.project.color, type: null },
  { label: RUNE.document.nav, icon: RUNE.document.icon, iconColor: RUNE.document.color, type: 'document' },
  { label: RUNE.memory.nav, icon: RUNE.memory.icon, iconColor: RUNE.memory.color, type: 'memory' },
  { label: RUNE.entity.nav, icon: RUNE.entity.icon, iconColor: RUNE.entity.color, type: 'entity' },
]

export default function SideNav() {
  const loc = useLocation()
  const params = new URLSearchParams(loc.search)
  const activeType = loc.pathname === '/' ? params.get('type') : '__none__'

  return (
    <nav className="hidden md:flex fixed top-0 left-0 h-full w-64 z-40 flex-col pt-8 pb-8 bg-surface-container-lowest border-r border-border-default">
      {/* Archivist sigil */}
      <div className="px-6 mb-8 flex flex-col items-center border-b border-border-subtle pb-6">
        <Link to="/" className="w-16 h-16 rounded-full border border-rune-quest p-1 mb-4 relative group flex items-center justify-center glow-quest">
          <span className="material-symbols-outlined text-rune-quest text-[28px]">menu_book</span>
        </Link>
        <h2 className="font-headline-md text-headline-md text-primary text-center">The Archivist</h2>
        <p className="font-label-md text-label-md text-text-tertiary mt-1 uppercase tracking-widest">Level IV Seeker</p>
      </div>

      {/* Type tabs */}
      <div className="flex-1 overflow-y-auto w-full">
        <ul className="space-y-2">
          {ITEMS.map((item) => {
            const isActive = (item.type ?? null) === (activeType === '__none__' ? null : activeType)
            const to = item.type ? { pathname: '/', search: `?type=${item.type}` } : { pathname: '/' }
            return (
              <li key={item.label}>
                <Link
                  to={to}
                  className={[
                    'flex items-center gap-4 py-3 pl-4 transition-all duration-200 hover:translate-x-1 group',
                    isActive
                      ? 'text-primary font-bold border-l-4 border-primary bg-surface-container-high'
                      : 'text-text-muted hover:text-on-surface border-l-4 border-transparent hover:bg-surface-container',
                  ].join(' ')}
                >
                  <span
                    className="material-symbols-outlined opacity-80 group-hover:opacity-100 transition-opacity"
                    style={{ color: item.iconColor }}
                  >
                    {item.icon}
                  </span>
                  <span className="font-headline-sm text-headline-sm">{item.label}</span>
                </Link>
              </li>
            )
          })}
        </ul>
      </div>

      {/* CTA + footer */}
      <div className="px-6 mt-auto flex flex-col gap-4">
        <button className="w-full py-2 bg-surface text-primary-container border border-primary-container rounded hover:bg-bg-surface hover:shadow-[0_0_15px_0px_rgba(227,211,160,0.3)] transition-all duration-300 font-headline-sm text-headline-sm flex items-center justify-center gap-2">
          <span className="material-symbols-outlined">add</span>
          Scribe new node
        </button>
        <div className="border-t border-border-subtle pt-4 space-y-2">
          <Link to="/sanctum" className="flex items-center gap-4 py-2 text-text-muted hover:text-on-surface transition-colors duration-200">
            <span className="material-symbols-outlined text-[20px]">fort</span>
            <span className="font-label-md text-label-md uppercase tracking-widest">Sanctum</span>
          </Link>
          <a className="flex items-center gap-4 py-2 text-text-muted hover:text-on-surface transition-colors duration-200" href="#">
            <span className="material-symbols-outlined text-[20px]">settings</span>
            <span className="font-label-md text-label-md uppercase tracking-widest">Settings</span>
          </a>
        </div>
      </div>
    </nav>
  )
}
