<script lang="ts">
  import { router, match } from './lib/router.svelte'
  import PillNav from './components/PillNav.svelte'
  import ScribeModal from './components/ScribeModal.svelte'
  import ScribeCapture from './components/ScribeCapture.svelte'
  import TransmuteCapture from './components/planner/TransmuteCapture.svelte'
  import Home from './routes/Home.svelte'
  import Today from './routes/Today.svelte'
  import Flow from './routes/Flow.svelte'
  import ProjectHub from './routes/ProjectHub.svelte'
  import Sanctum from './routes/Sanctum.svelte'
  import TomeReader from './routes/TomeReader.svelte'
  import Settings from './routes/Settings.svelte'
  import Placeholder from './routes/Placeholder.svelte'
  import type { Component } from 'svelte'

  interface Route {
    pattern: string
    component: Component<any>
    props?: (p: Record<string, string>) => Record<string, unknown>
  }

  // First match wins.
  const routes: Route[] = [
    { pattern: '/', component: Home },
    { pattern: '/today', component: Today },
    { pattern: '/flow', component: Flow },
    { pattern: '/project/:name', component: ProjectHub, props: (p) => ({ name: p.name }) },
    { pattern: '/sanctum', component: Sanctum },
    { pattern: '/tome/:id', component: TomeReader, props: (p) => ({ id: p.id }) },
    { pattern: '/settings', component: Settings },
  ]

  const resolved = $derived.by((): { component: Component<any>; props: Record<string, unknown> } => {
    for (const r of routes) {
      const params = match(r.pattern, router.path)
      if (params) return { component: r.component, props: r.props ? r.props(params) : {} }
    }
    return { component: Placeholder, props: { title: 'Lost in the void', eyebrow: router.path } }
  })
</script>

<div class="min-h-screen bg-bg-page text-on-surface font-body-md">
  <PillNav />
  <!-- The home constellation is full-bleed under the floating pill; every other route
       reserves headroom so its heading is not hidden behind it. -->
  <div class="min-w-0 {router.path === '/' ? '' : 'pt-16'}">
    {#key router.path}
      {@const Route = resolved.component}
      <Route {...resolved.props} />
    {/key}
  </div>
  <ScribeCapture />
  <TransmuteCapture />
  <ScribeModal />
</div>
