import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { CheckEvent, ChecksView } from '../types'

// Read-only companion to the reticle-checks command-hook plugin. It reads
// .claude/reticle-checks/<session_id>/events.jsonl and shows it; every hook it
// adds passes the event on unchanged, and /checks answers with no text, so
// nothing it does reaches the model's context.

const PANE = 'reticle-checks'
const EMPTY: ChecksView = { events: [], file: null, note: 'No reticle-checks events yet.' }
const view = atom({ plugin: 'reticle-checks-pane', key: 'view' } as const, EMPTY)
const EDIT_TOOLS = new Set(['Edit', 'Write', 'MultiEdit'])
const POLL_MS = 3000

/** Mirrors session_dir() in reticle_checks.py. */
export function sessionFolder(sessionId: string): string {
  const safe = sessionId.replace(/[^A-Za-z0-9_.-]/g, '_').slice(0, 128).replace(/^\.+|\.+$/g, '')
  return safe === '' ? 'unknown-session' : safe
}

export function parseEvents(text: string): CheckEvent[] {
  const rows: CheckEvent[] = []
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue
    try {
      const row = JSON.parse(line) as CheckEvent
      if (row !== null && typeof row === 'object' && typeof row.kind === 'string') rows.push(row)
    } catch {
      // a row being written right now; the next read gets it whole
    }
  }
  return rows
}

function bytes(n: number | undefined): string {
  if (n === undefined) return '?'
  return n < 1024 ? `${n}` : `${(n / 1024).toFixed(1)}k`
}

export function statusLine(events: readonly CheckEvent[]): string | undefined {
  const checks = events.filter(e => e.kind === 'check')
  const last = checks[checks.length - 1]
  if (last === undefined) return undefined
  const visible = checks.reduce((sum, e) => sum + (e.visible_bytes ?? 0), 0)
  const full = checks.reduce((sum, e) => sum + (e.full_bytes ?? 0), 0)
  const shape = last.rendered_as !== undefined && last.rendered_as !== last.mode
    ? `${last.mode}->${last.rendered_as}` : (last.mode ?? '?')
  return `checks ${checks.length} | last ${last.status ?? '?'} (${shape}) `
    + `${bytes(last.visible_bytes)}/${bytes(last.full_bytes)}B | session ${bytes(visible)}/${bytes(full)}B visible/full`
}

function clock(ts: string): string {
  const at = new Date(ts)
  return Number.isNaN(at.getTime()) ? ts : at.toTimeString().slice(0, 8)
}

export function eventRow(e: CheckEvent): string {
  if (e.kind === 'check') {
    const shape = e.rendered_as !== undefined && e.rendered_as !== e.mode
      ? `${e.mode}->${e.rendered_as}` : (e.mode ?? '?')
    const why = e.delta_fallback_reason ? ` [${e.delta_fallback_reason}]` : ''
    return `${clock(e.ts)}  ${e.trigger_file ?? '?'}  ${shape}  ${e.status ?? '?'}  `
      + `${e.visible_bytes ?? '?'}/${e.full_bytes ?? '?'} B${why}`
  }
  if (e.kind === 'skip') return `${clock(e.ts)}  ${e.trigger_file ?? '?'}  skipped (${e.reason ?? '?'})`
  if (e.kind === 'baseline_invalidated') return `${clock(e.ts)}  delta baseline invalidated (${e.reason ?? '?'})`
  return `${clock(e.ts)}  ${e.kind}`
}

async function refresh($: EngineInterface): Promise<void> {
  const sessionId = await $.session.id()
  const roots = [...new Set([await $.session.cwd(), await $.session.root()])]
  let next: ChecksView = EMPTY
  for (const root of roots) {
    const file = `${root}/.claude/reticle-checks/${sessionFolder(sessionId)}/events.jsonl`
    try {
      const text = await $.fs.read(file)
      next = { events: parseEvents(text), file, note: null }
      break
    } catch {
      next = { ...EMPTY, note: `No events file yet at ${file}` }
    }
  }
  const before = await read($, view)
  if (before.file !== next.file || before.events.length !== next.events.length || before.note !== next.note) {
    await update($, view, () => next)
  }
  $.ui.status(statusLine(next.events))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'checks',
      description: 'Show this session\'s reticle-checks events and the latest injected text',
    })
    await refresh($)
    $.clock.every(POLL_MS, () => void refresh($).catch(() => undefined))
    return next(e)
  })

  on('command.run', { command: 'checks' }, async $ => {
    await refresh($)
    await $.ui.open({ id: PANE, title: 'Reticle checks' })
    return {} // no text: the model sees nothing from this command
  })

  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    if (EDIT_TOOLS.has(String(e.tool))) await refresh($).catch(() => undefined)
    return result
  })

  on('turn.complete', async ($, e, next) => {
    await refresh($).catch(() => undefined)
    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const current = await read($, view)
    const checks = current.events.filter(row => row.kind === 'check')
    const latest = checks[checks.length - 1]
    return (
      <Box flexDirection="column">
        <Text bold>{statusLine(current.events) ?? 'No checks in this session yet.'}</Text>
        {current.note !== null && <Text dimColor>{current.note}</Text>}
        {current.file !== null && <Text dimColor wrap="truncate-start">{current.file}</Text>}
        <Text> </Text>
        <Text underline>time      file  mode  status  visible/full</Text>
        {current.events.map(row => (
          <Text dimColor={row.kind !== 'check'} wrap="truncate-end">{eventRow(row)}</Text>
        ))}
        <Text> </Text>
        <Text underline>Latest injected text{latest !== undefined ? ` (check at ${clock(latest.ts)})` : ''}</Text>
        <Text wrap="wrap">{latest?.visible_text ?? '(none yet)'}</Text>
      </Box>
    )
  })
}
