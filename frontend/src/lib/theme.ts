// One glowing colour per node type — four, the ceiling per CLAUDE.md. Re-pigmented
// around the aquryu brand green: quest lines are green (the primary/brand hue), tomes
// aqua, so green + aqua literally reads as "aqua dragon".
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
  project: { color: '#6fbf73', icon: 'account_tree', label: 'Quest line', glowClass: 'glow-quest', pulseClass: 'pulse-quest', nav: 'Quest lines' },
  document: { color: '#4fb6c9', icon: 'menu_book', label: 'Tome', glowClass: 'glow-tome', pulseClass: 'pulse-tome', nav: 'Tomes' },
  memory: { color: '#d9a24a', icon: 'auto_stories', label: 'Chronicle', glowClass: 'glow-chronicle', pulseClass: 'pulse-chronicle', nav: 'Chronicles' },
  entity: { color: '#9d6bd9', icon: 'token', label: 'Rune', glowClass: 'glow-entity', pulseClass: 'pulse-entity', nav: 'Runes' },
}

// Quest lines are the spine; entities are leaves (never a lineage source — the supernode
// rule). Edges inherit the colour of their higher-rank endpoint so lineage reads by thread.
const PARENT_RANK: Record<NodeType, number> = { project: 3, memory: 2, document: 1, entity: 0 }

export function edgeColor(srcType: NodeType, dstType: NodeType): string {
  return RUNE[PARENT_RANK[srcType] >= PARENT_RANK[dstType] ? srcType : dstType].color
}

// The Eisenhower quadrants reuse the four rune colours (the design ceiling), so the
// planner needs no new palette: Q1 green, Q2 aqua, Q3 amber, Q4 violet.
export type Quadrant = 'Q1' | 'Q2' | 'Q3' | 'Q4'

export interface QuadrantMeta {
  id: Quadrant
  label: string
  icon: string
  color: string
  glow: string // box-shadow rgba, matches the rune colour
}

export const QUADRANT: Record<Quadrant, QuadrantMeta> = {
  Q1: { id: 'Q1', label: 'Do now', icon: 'bolt', color: RUNE.project.color, glow: 'rgba(111,191,115,0.15)' },
  Q2: { id: 'Q2', label: 'Schedule', icon: 'event', color: RUNE.document.color, glow: 'rgba(79,182,201,0.15)' },
  Q3: { id: 'Q3', label: 'Minimize', icon: 'filter_list', color: RUNE.memory.color, glow: 'rgba(217,162,74,0.15)' },
  Q4: { id: 'Q4', label: 'Someday', icon: 'cloud', color: RUNE.entity.color, glow: 'rgba(157,107,217,0.15)' },
}

// The local calendar date (YYYY-MM-DD) the user is actually living in — the planner is
// day-centric, so views key off the browser's local day, not UTC.
export function localDate(d: Date = new Date()): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
