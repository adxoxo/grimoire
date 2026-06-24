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

async function post<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'POST',
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

async function del<T>(url: string): Promise<T> {
  const res = await fetch(url, { method: 'DELETE' })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

async function patch<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'PATCH',
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

async function put<T>(url: string, body?: unknown): Promise<T> {
  const res = await fetch(url, {
    method: 'PUT',
    headers: body ? { 'content-type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

export interface NewNode {
  type: 'project' | 'entity' | 'document'
  title: string
  context?: string
  project?: string
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
  createNode: (node: NewNode) => post<{ id: string; type: string; title: string }>('/api/nodes', node),
  scribe: (message: string) =>
    post<{ id: string; type: NodeType; title: string; project?: string }>('/api/scribe', { message }),
  ingest: async (files: File[], project?: string) => {
    const fd = new FormData()
    for (const f of files) fd.append('files', f)
    if (project) fd.append('project', project)
    const res = await fetch('/api/ingest', { method: 'POST', body: fd })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    return res.json() as Promise<{
      project: string
      ingested: { filename: string; title?: string; node_id?: string; chunks?: number; error?: string }[]
    }>
  },
  deleteNode: (id: string) => del<{ deleted: number; node_id: string }>(`/api/nodes/${encodeURIComponent(id)}`),
  deleteEdge: (src: string, dst: string, rel: string) =>
    del<{ deleted: number }>(
      `/api/edges?src=${encodeURIComponent(src)}&dst=${encodeURIComponent(dst)}&rel=${encodeURIComponent(rel)}`,
    ),
  compact: () =>
    post<{ compacted: { project: string; clusters_merged: number; originals_archived: number }[] }>(
      '/api/maintenance/compact',
    ),
  reembed: () => post<{ reembedded: number }>('/api/maintenance/reembed'),
}

// ---------------------------------------------------------------------------
// Planner (Today + Flow tabs)
// ---------------------------------------------------------------------------

export type Quadrant = 'Q1' | 'Q2' | 'Q3' | 'Q4'

export interface Task {
  id: string
  title: string
  notes: string | null
  important: number
  urgent_manual: number | null
  urgent_computed: number
  estimate_minutes: number | null
  status: string
  due: string | null
  goal_id: string | null
  project_id: string | null
  goal_title?: string | null
  area_name?: string | null
  area_color?: string | null
  quadrant?: Quadrant
  effective_urgent?: boolean
}

export interface Streak {
  current: number
  best: number
}

export interface HabitProgress {
  count: number
  target?: number
  met?: boolean
  done_today?: boolean
}

export interface Habit {
  id: string
  name: string
  cadence_type: 'daily' | 'weekly'
  weekly_target: number | null
  target: string | null
  duration_minutes: number
  window_preference: string
  hard_constraint: string | null
  flexibility: string
  streak_current: number
  streak_best: number
  active: number
  streak?: Streak
  progress?: HabitProgress
}

export interface Goal {
  id: string
  title: string
  why: string | null
  area_id: string | null
  target_date: string | null
  priority: number
  status: string
  project_id: string | null
  area_name?: string | null
  area_color?: string | null
  open_tasks?: number
  done_tasks?: number
}

export interface LifeArea {
  id: string
  name: string
  color: string | null
  sort_order: number
}

export interface AreaGroup {
  id: string | null
  name: string
  color: string | null
  sort_order?: number
  goals: Goal[]
}

// Write-side inputs (booleans, not the SQLite ints the row types carry).
export interface TaskInput {
  title: string
  notes?: string
  important?: boolean
  urgent_manual?: boolean
  estimate_minutes?: number
  due?: string
  goal_id?: string
  project_id?: string
}

export interface HabitInput {
  name: string
  cadence_type?: 'daily' | 'weekly'
  weekly_target?: number
  target?: string
  duration_minutes?: number
  window_preference?: string
  hard_constraint?: string
  flexibility?: string
  active?: boolean
}

export interface GoalInput {
  title: string
  why?: string
  area?: string
  target_date?: string
  priority?: number
  status?: string
  project_id?: string
}

export interface WeeklyReport {
  week_start: string
  overall_percent: number
  habits: { habit_id: string; name: string; cadence_type: string; done: number; expected: number; percent: number; streak: Streak }[]
}

export interface TodayData {
  date: string
  habits: Habit[]
  quadrants: Record<Quadrant, Task[]>
  goals: AreaGroup[]
  weekly: WeeklyReport
  estimate: { minutes: number; hours: number; counted: number; untimed: number; total_tasks: number; label: string }
}

export interface Block {
  start: string
  end: string
  type: 'anchor' | 'habit' | 'task' | 'goal' | 'break'
  title: string
  ref_id: string | null
  goal_block: boolean
  locked: boolean
  kind: string | null
}

export interface Deferred {
  type: string
  title: string
  ref_id?: string | null
  reason: string
}

export interface DayPlan {
  date: string
  wake_time: string | null
  sleep_target: string | null
  blocks: Block[]
  if_enabled: boolean
  first_meal: string | null
  eating_hours: number
  generated_at?: string | null
}

export interface PlanResult extends DayPlan {
  deferred: Deferred[]
  window_minutes: number
  requested_minutes: number
  overcommit_minutes: number
  goal_block_present: boolean
  notice: string | null
}

export interface Anchor {
  id: string
  title: string
  date: string | null
  kind: 'hard' | 'soft'
  start: string | null
  window_start: string | null
  window_end: string | null
  wake_relative: string | null
  duration_minutes: number
}

export interface Overlay {
  eating_start: string
  eating_end: string
  eating_hours: number
}

export interface Template {
  template_id: string
  template_name: string
  n: number
}

export interface FlowData {
  date: string
  plan: DayPlan | null
  anchors: Anchor[]
  overlay: Overlay | null
  templates: Template[]
}

export interface ChatResponse {
  reply: string
  actions: { tool: string; args: Record<string, unknown>; result: Record<string, unknown> }[]
  error?: boolean
}

const q = (params: Record<string, string | undefined>) => {
  const u = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v) u.set(k, v)
  const s = u.toString()
  return s ? `?${s}` : ''
}

export const planner = {
  today: (date?: string) => get<TodayData>(`/api/planner/today${q({ date })}`),
  weeklyReport: (date?: string) => get<WeeklyReport>(`/api/planner/weekly-report${q({ date })}`),

  createTask: (body: TaskInput) => post<Task>('/api/planner/tasks', body),
  modifyTask: (id: string, body: Partial<TaskInput>) => patch<Task>(`/api/planner/tasks/${id}`, body),
  completeTask: (id: string, done = true) =>
    post<Task>(`/api/planner/tasks/${id}/complete${q({ done: String(done) })}`),
  deleteTask: (id: string) => del<{ deleted: number }>(`/api/planner/tasks/${id}`),

  createHabit: (body: HabitInput) => post<Habit>('/api/planner/habits', body),
  modifyHabit: (id: string, body: Partial<HabitInput>) => patch<Habit>(`/api/planner/habits/${id}`, body),
  toggleHabit: (id: string, date?: string) =>
    post<Habit & { done_today: boolean }>(`/api/planner/habits/${id}/toggle${q({ date })}`),
  deleteHabit: (id: string) => del<{ deleted: number }>(`/api/planner/habits/${id}`),

  areas: () => get<{ areas: LifeArea[] }>('/api/planner/areas'),
  goals: (status = 'active') => get<{ goals: Goal[]; by_area: AreaGroup[] }>(`/api/planner/goals${q({ status })}`),
  createGoal: (body: GoalInput) => post<Goal>('/api/planner/goals', body),
  modifyGoal: (id: string, body: Partial<GoalInput>) => patch<Goal>(`/api/planner/goals/${id}`, body),
  deleteGoal: (id: string) => del<{ deleted: number }>(`/api/planner/goals/${id}`),

  projectTasks: (projectId: string, status = 'open') =>
    get<{ tasks: Task[] }>(`/api/planner/projects/${projectId}/tasks${q({ status })}`),
  sweep: () => post<{ recomputed: number }>('/api/planner/sweep'),

  flow: (date?: string) => get<FlowData>(`/api/planner/flow${q({ date })}`),
  generateDay: (body: { date?: string; wake_time: string; sleep_target: string; now?: string; if_enabled?: boolean; first_meal?: string; eating_hours?: number }) =>
    post<PlanResult>('/api/planner/flow/generate', body),
  reflow: (body: { date?: string; now?: string }) => post<PlanResult>('/api/planner/flow/reflow', body),
  saveBlocks: (date: string, blocks: Block[]) => put<{ blocks: Block[] }>(`/api/planner/flow/${date}/blocks`, { blocks }),
  flowMeta: (date: string, body: { if_enabled?: boolean; first_meal?: string; eating_hours?: number }) =>
    patch<{ plan: DayPlan; overlay: Overlay | null }>(`/api/planner/flow/${date}/meta`, body),
  lockBlock: (date: string, body: { ref_id?: string; start?: string; locked?: boolean }) =>
    patch<{ blocks: Block[] }>(`/api/planner/flow/${date}/block`, body),

  createAnchor: (body: Partial<Anchor> & { title: string }) => post<Anchor>('/api/planner/anchors', body),
  deleteAnchor: (id: string) => del<{ deleted: number }>(`/api/planner/anchors/${id}`),
  saveTemplate: (name: string, date?: string) =>
    post<{ template_id: string; name: string; anchors: number }>('/api/planner/flow/templates', { name, date }),
  loadTemplate: (templateId: string, date?: string) =>
    post<{ created: Anchor[] }>(`/api/planner/flow/templates/${templateId}/load`, { date }),

  chat: (message: string, context?: Record<string, unknown>, history?: unknown[]) =>
    post<ChatResponse>('/api/planner/chat', { message, context, history }),
}
