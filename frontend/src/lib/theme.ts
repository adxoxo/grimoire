// One glowing colour per node type — four, the ceiling per CLAUDE.md. The dark arcane
// grimoire palette: quest lines gold (the primary accent), tomes arcane blue,
// chronicles ember, runes violet.
export type NodeType = 'project' | 'document' | 'memory' | 'entity'

interface Rune {
  color: string
  icon: string
  label: string // grimoire name, sentence case
  glowClass: string
  pulseClass: string
  nav: string
}

export const RUNE: Record<NodeType, Rune> = {
  project: { color: '#d4a93f', icon: 'account_tree', label: 'Quest line', glowClass: 'glow-quest', pulseClass: 'pulse-quest', nav: 'Quest lines' },
  document: { color: '#5b8dd9', icon: 'menu_book', label: 'Tome', glowClass: 'glow-tome', pulseClass: 'pulse-tome', nav: 'Tomes' },
  memory: { color: '#d98b4a', icon: 'auto_stories', label: 'Chronicle', glowClass: 'glow-chronicle', pulseClass: 'pulse-chronicle', nav: 'Chronicles' },
  entity: { color: '#9d6bd9', icon: 'token', label: 'Rune', glowClass: 'glow-entity', pulseClass: 'pulse-entity', nav: 'Runes' },
}

// V2 taxonomy scopes are structural chrome, NOT a fifth/sixth rune colour: they sit
// above content nodes and use the gold accent family (domain the brighter display gold,
// index the deeper accent gold) so the four rune hues stay reserved for content.
export type ScopeKind = 'domain' | 'index'

export interface ScopeStyle {
  color: string
  icon: string
  label: string
}

export const SCOPE: Record<ScopeKind, ScopeStyle> = {
  domain: { color: '#e3d3a0', icon: 'hub', label: 'Domain' },
  index: { color: '#c9a13b', icon: 'category', label: 'Index' },
}

// Colour for any node, scope or content, guarded against unknown types (a scope row
// reaching a content-only renderer must not throw).
export function nodeKindColor(node: { type: string; node_kind?: string | null }): string {
  if (node.node_kind === 'domain' || node.node_kind === 'index') return SCOPE[node.node_kind].color
  return RUNE[node.type as NodeType]?.color ?? '#9b96b8'
}

// Quest lines are the spine; entities are leaves (never a lineage source — the supernode
// rule). Edges inherit the colour of their higher-rank endpoint so lineage reads by thread.
const PARENT_RANK: Record<NodeType, number> = { project: 3, memory: 2, document: 1, entity: 0 }

export function edgeColor(srcType: NodeType, dstType: NodeType): string {
  return RUNE[PARENT_RANK[srcType] >= PARENT_RANK[dstType] ? srcType : dstType].color
}

// Community palette for the GLOBAL constellation view only (focus mode keeps the four
// rune colours). Derived from the aquryu greens plus muted companions — no rainbow.
export const COMMUNITY_PALETTE = [
  '#4F7A52', // leaf green
  '#7BB77E', // glow green
  '#5b8dd9', // arcane blue
  '#d4a93f', // gold
  '#9d6bd9', // violet
  '#d98b4a', // ember
  '#5FA8A0', // muted teal
  '#B76B7B', // muted rose
]

export function communityColor(id: number): string {
  const n = COMMUNITY_PALETTE.length
  return COMMUNITY_PALETTE[((id % n) + n) % n]
}

// The Eisenhower quadrants reuse the four rune colours (the design ceiling), so the
// planner needs no new palette: Q1 gold, Q2 arcane blue, Q3 ember, Q4 violet.
export type Quadrant = 'Q1' | 'Q2' | 'Q3' | 'Q4'

export interface QuadrantMeta {
  id: Quadrant
  label: string
  icon: string
  color: string
  glow: string // box-shadow rgba, matches the rune colour
}

export const QUADRANT: Record<Quadrant, QuadrantMeta> = {
  Q1: { id: 'Q1', label: 'Do now', icon: 'bolt', color: RUNE.project.color, glow: 'rgba(212,169,63,0.15)' },
  Q2: { id: 'Q2', label: 'Schedule', icon: 'event', color: RUNE.document.color, glow: 'rgba(91,141,217,0.15)' },
  Q3: { id: 'Q3', label: 'Minimize', icon: 'filter_list', color: RUNE.memory.color, glow: 'rgba(217,162,74,0.15)' },
  Q4: { id: 'Q4', label: 'Someday', icon: 'cloud', color: RUNE.entity.color, glow: 'rgba(157,107,217,0.15)' },
}

// The local calendar date (YYYY-MM-DD) the user is actually living in — the planner is
// day-centric, so views key off the browser's local day, not UTC.
export function localDate(d: Date = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
