/** One row of .claude/reticle-checks/<session_id>/events.jsonl, as the pane uses it. */
export type CheckEvent = {
  kind: 'check' | 'skip' | 'baseline_invalidated' | string
  ts: string
  trigger_file?: string
  mode?: string
  rendered_as?: string
  status?: string
  tests_run?: number | null
  visible_bytes?: number
  full_bytes?: number
  delta_fallback_reason?: string | null
  reason?: string
  log_path?: string
  visible_text?: string
}

/** What the mod last read: the rows, and the file it read them from (or why not). */
export type ChecksView = {
  events: CheckEvent[]
  file: string | null
  note: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'reticle-checks-pane': { view: ChecksView }
  }
}
