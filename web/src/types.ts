export type Target = { id: string; name: string; role: string }
export type Objective = { id: string; text: string }
export type Scenario = {
  id: string
  kind: string
  company?: string
  targets?: Target[]
  objectives?: Objective[]
  open?: boolean
  opens_at?: string | null
}

export type ThemEvent = {
  type: string
  channel?: string
  body?: string
  subject?: string
  url?: string
  fields?: string[]
  values?: Record<string, string>
}

export type Page = { url?: string; title?: string; fields?: string[]; has_html?: boolean }

export type SimEvent =
  | { kind: "start"; sim_id: string; target: Target }
  | { kind: "status"; text: string }
  | { kind: "research"; text: string }
  | {
      kind: "us"
      touch: number | string
      channel: string
      from?: { name?: string; address?: string }
      subject?: string
      body: string
      rationale?: string
      objectives?: string[]
      page?: Page | null
    }
  | { kind: "them"; events: ThemEvent[] }
  | { kind: "won"; objectives: string[]; session_id?: string }
  | { kind: "error"; text: string }
  | { kind: "done"; sim_id: string }

export type SimRecord = {
  sim_id: string
  scenario_id: string
  target: Target
  started_at: string
  finished_at?: string
  won: string[]
  status: string
  events?: SimEvent[]
}
