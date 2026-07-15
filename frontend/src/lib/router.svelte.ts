// A tiny dependency-free hash router. Hash routing needs zero server rewrite config
// (the FastAPI host or `vite preview` can serve one index.html), which keeps the app
// as light as the rewrite set out to be. Params (/project/:name) and a query string
// (/?type=document) are both supported.

interface RouteState {
  path: string
  query: Record<string, string>
}

function parse(): RouteState {
  const raw = window.location.hash.replace(/^#/, '') || '/'
  const [path, qs] = raw.split('?')
  const query: Record<string, string> = {}
  if (qs) for (const [k, v] of new URLSearchParams(qs)) query[k] = v
  return { path: path || '/', query }
}

// Reactive singleton the whole app reads from.
export const router = $state<RouteState>(parse())

window.addEventListener('hashchange', () => {
  const next = parse()
  router.path = next.path
  router.query = next.query
  // Route change = fresh screen; start it at the top.
  window.scrollTo(0, 0)
})

/** Programmatic navigation. Plain <a href="#/..."> works too and is preferred. */
export function navigate(to: string): void {
  window.location.hash = to
}

/** Href for a hash link. `link('/today')` -> '#/today'. */
export function link(to: string): string {
  return `#${to}`
}

/**
 * Match a pattern against a path, returning the captured params or null.
 *   match('/project/:name', '/project/roar') -> { name: 'roar' }
 *   match('/sanctum', '/project/roar')       -> null
 */
export function match(pattern: string, path: string): Record<string, string> | null {
  const pp = pattern.split('/').filter(Boolean)
  const ap = path.split('/').filter(Boolean)
  if (pp.length !== ap.length) return null
  const params: Record<string, string> = {}
  for (let i = 0; i < pp.length; i++) {
    if (pp[i].startsWith(':')) params[pp[i].slice(1)] = decodeURIComponent(ap[i])
    else if (pp[i] !== ap[i]) return null
  }
  return params
}
