// One glowing colour per node type — four, the ceiling per CLAUDE.md.
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

// Quest lines are the spine; entities are leaves (never a lineage source — the supernode
// rule). Edges inherit the colour of their higher-rank endpoint so lineage reads by thread.
const PARENT_RANK: Record<NodeType, number> = { project: 3, memory: 2, document: 1, entity: 0 }

export function edgeColor(srcType: NodeType, dstType: NodeType): string {
  return RUNE[PARENT_RANK[srcType] >= PARENT_RANK[dstType] ? srcType : dstType].color
}
