import type { NodeType } from './theme'

export interface GraphNode {
  id: string
  type: NodeType
  title: string
  status: string | null
  updated_at: string
}

export interface GraphEdge {
  src: string
  dst: string
  rel: string
}

export interface Graph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface LinkedNode {
  id: string
  type: NodeType
  title: string
  status: string | null
  rel: string
}

export interface Project {
  id: string
  type: string
  title: string
  status: string
  meta: Record<string, unknown>
  context_summary: string | null
  created_at: string
  updated_at: string
  linked: LinkedNode[]
}

export interface ReviewItem {
  id: string
  type: NodeType
  title: string
  status: string | null
  context_summary: string | null
  updated_at: string
}

export interface Document {
  id: string
  title: string
  status: string | null
  meta: Record<string, unknown>
  content: string
}

export interface SearchHit {
  chunk_id: string
  node_id: string
  title: string
  type: NodeType
  score: number
  content: string
}

async function get<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

async function post<T>(url: string): Promise<T> {
  const res = await fetch(url, { method: 'POST' })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export const api = {
  graph: () => get<Graph>('/api/graph'),
  project: (name: string) => get<Project>(`/api/projects/${encodeURIComponent(name)}`),
  node: (id: string) => get<Record<string, unknown>>(`/api/nodes/${encodeURIComponent(id)}`),
  review: () => get<{ items: ReviewItem[] }>('/api/review'),
  markReviewed: (id: string) => post<{ node_id: string; status: string }>(`/api/nodes/${encodeURIComponent(id)}/review`),
  document: (id: string) => get<Document>(`/api/documents/${encodeURIComponent(id)}`),
  search: (q: string, project?: string) =>
    get<{ results: SearchHit[] }>(
      `/api/search?q=${encodeURIComponent(q)}${project ? `&project=${encodeURIComponent(project)}` : ''}`,
    ),
}
