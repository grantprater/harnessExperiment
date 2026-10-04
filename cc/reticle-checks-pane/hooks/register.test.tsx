import { describe, expect, mock, test } from 'claude-code/testing'

import { eventRow, parseEvents, sessionFolder, statusLine } from './register'

const SESSION = 'sess-abc'
const ROOT = '/proj'
const FILE = `${ROOT}/.claude/reticle-checks/${SESSION}/events.jsonl`
const INJECTED = 'Post-edit check failed; tests=5; failing=1; trigger=calc.py; check #2; mode=delta.\nFull log: /proj/x.log'
const ROWS = [
  { kind: 'check', ts: '2026-10-03T10:00:00.000Z', trigger_file: 'calc.py', mode: 'delta', rendered_as: 'selective',
    status: 'failed', tests_run: 5, visible_bytes: 580, full_bytes: 1764, delta_fallback_reason: 'no_baseline',
    visible_text: 'first' },
  { kind: 'skip', ts: '2026-10-03T10:00:01.000Z', trigger_file: 'calc.py', reason: 'source_unchanged' },
  { kind: 'baseline_invalidated', ts: '2026-10-03T10:00:02.000Z', reason: 'PreCompact:auto' },
  { kind: 'check', ts: '2026-10-03T10:00:03.000Z', trigger_file: 'calc.py', mode: 'delta', rendered_as: 'delta',
    status: 'failed', tests_run: 5, visible_bytes: 300, full_bytes: 1800, delta_fallback_reason: null,
    visible_text: INJECTED },
]
const JSONL = ROWS.map(row => JSON.stringify(row)).join('\n') + '\n{"kind": "check", "ts"' // torn last line

const PANE_PROPS = {
  title: 'Reticle checks', isFocused: false, bodyColumns: 100, placement: 'dock' as const,
  scroll: { offset: 0, bodyRows: 40 }, view: {},
}

describe('pure helpers', () => {
  test('parses rows and skips a torn line', async () => {
    const rows = parseEvents(JSONL)
    expect(rows.length).toBe(4)
    expect(rows[3]?.visible_text).toBe(INJECTED)
  })

  test('status line counts checks only and sums bytes', async () => {
    expect(statusLine(parseEvents(JSONL))).toBe(
      'checks 2 | last failed (delta) 300/1.8kB | session 880/3.5kB visible/full')
    expect(statusLine([])).toBeUndefined()
  })

  test('rows show mode->rendering and the fallback reason', async () => {
    const rows = parseEvents(JSONL)
    expect(eventRow(rows[0]!)).toContain('calc.py  delta->selective  failed  580/1764 B [no_baseline]')
    expect(eventRow(rows[1]!)).toContain('skipped (source_unchanged)')
    expect(eventRow(rows[2]!)).toContain('delta baseline invalidated (PreCompact:auto)')
  })

  test('session folder matches the Python sanitiser', async () => {
    expect(sessionFolder('a/b:c')).toBe('a_b_c')
    expect(sessionFolder('')).toBe('unknown-session')
  })
})

test('/checks opens the pane, answers no text, and the pane shows the latest injected text', async ($, on) => {
  const reads: string[] = []
  let status: string | undefined = 'unset'
  // Calls on `$` are answered beneath the plugin as { value } or { deny }.
  on('session.id', async () => ({ value: SESSION }))
  on('session.cwd', async () => ({ value: ROOT }))
  on('session.root', async () => ({ value: ROOT }))
  on('fs.read', async ($inner, e) => {
    // The engine resolves the path before hooks see it (C:\proj\... on Windows).
    const path = e.path.replace(/\\/g, '/').replace(/^[A-Za-z]:/, '')
    reads.push(path)
    return path === FILE ? { value: JSONL } : { deny: 'ENOENT' }
  })
  on('ui.status', async ($inner, e) => {
    status = e.text
    return { value: undefined }
  })
  on('ui.open', async () => ({ value: { isPlaced: true as const } }))
  mock.clock(on)

  const answer = await $.command.run({
    command: 'checks', args: '', origin: { kind: 'composer' },
    presentation: { isFullscreen: true, columns: 160 },
  })
  expect(answer.text).toBeUndefined()
  expect(answer.context).toBeUndefined()
  expect(reads).toContain(FILE)
  expect(status).toBe('checks 2 | last failed (delta) 300/1.8kB | session 880/3.5kB visible/full')

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'reticle-checks-pane', surface, component: 'Pane',
      requestId: 'reticle-checks', props: PANE_PROPS })
    expect((await ui.find({ type: 'Text', text: INJECTED }))?.text).toBe(INJECTED)
    expect(await ui.find({ type: 'Text', text: 'delta->selective  failed  580/1764 B [no_baseline]' })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: 'delta baseline invalidated' })).toBeDefined()
    await ui.unmount()
  }
})
