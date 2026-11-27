import { useEffect, useState } from 'react'
import { ChevronDown, Plus, Trash2 } from 'lucide-react'

export type ActionItem = { task: string; owner?: string | null; due?: string | null; time?: string | null }
export type DecisionItem = { decision: string; by?: string | null; time?: string | null }
export type NotesEditRequest = { revision: number; summary?: string[]; actions?: ActionItem[]; decisions?: DecisionItem[] }
type HistoryChange = { section: string; kind: 'added' | 'removed' | 'changed' | 'renamed'; before: string | null; after: string | null; detail?: string }
type HistoryEntry = { revision: number; at: string; changes: HistoryChange[]; more?: number }
type Loaded = { revision: number; summary: string[]; actions: ActionItem[]; decisions: DecisionItem[]; history: HistoryEntry[] }

const clean = (value: string | null | undefined) => (value ?? '').split(/\s+/).filter(Boolean).join(' ')
const cleanAction = (item: ActionItem): ActionItem => ({ task: clean(item.task), owner: clean(item.owner), due: clean(item.due), time: clean(item.time) })
const cleanDecision = (item: DecisionItem): DecisionItem => ({ decision: clean(item.decision), by: clean(item.by), time: clean(item.time) })
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b)

/** What a meeting's file says (summary, action items, decisions, history), read again whenever `version` changes. */
function useMeetingRecord(url: string, version = 0) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    fetch(url).then((response) => response.json()).then((record) => {
      if (!cancelled) setLoaded({ revision: record.revision ?? 1, summary: record.summary ?? [], actions: record.actions ?? [], decisions: record.decisions ?? [], history: record.history ?? [] })
    }).catch(() => { if (!cancelled) setError('The notes could not be loaded.') })
    return () => { cancelled = true }
  }, [url, version])
  return { loaded, error }
}

/** Fix the notes of a finished meeting: reword, add or remove summary points, action items and decisions. */
export function NotesEditor({ url, onSave, onClose }: { url: string; onSave: (edit: NotesEditRequest) => Promise<string>; onClose: (saved: boolean) => void }) {
  const { loaded, error: loadError } = useMeetingRecord(url)
  const [draft, setDraft] = useState<{ summary: string[]; actions: ActionItem[]; decisions: DecisionItem[] } | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => { if (loaded && !draft) setDraft({ summary: loaded.summary, actions: loaded.actions, decisions: loaded.decisions }) }, [loaded, draft])
  if (loadError) return <small className="operation-error" role="alert">{loadError}</small>
  if (!loaded || !draft) return <small>Loading the notes…</small>
  const summary = draft.summary.map(clean).filter(Boolean)
  const actions = draft.actions.map(cleanAction).filter((item) => item.task)
  const decisions = draft.decisions.map(cleanDecision).filter((item) => item.decision)
  const was = { summary: loaded.summary, actions: loaded.actions.map(cleanAction), decisions: loaded.decisions.map(cleanDecision) }
  const changed = { summary: !same(summary, was.summary), actions: !same(actions, was.actions), decisions: !same(decisions, was.decisions) }
  const count = Object.values(changed).filter(Boolean).length
  const save = async () => {
    setSaving(true); setError('')
    // Empty owner, due and time are left out, so a saved item stays as short as the worker's.
    const strip = <T extends Record<string, string | null | undefined>>(item: T) => Object.fromEntries(Object.entries(item).filter(([, value]) => value)) as T
    const problem = await onSave({
      revision: loaded.revision,
      ...(changed.summary ? { summary } : {}),
      ...(changed.actions ? { actions: actions.map(strip) } : {}),
      ...(changed.decisions ? { decisions: decisions.map(strip) } : {}),
    })
    setSaving(false)
    if (problem) setError(problem); else onClose(true)
  }
  const setAt = <K extends keyof typeof draft>(key: K, index: number, value: (typeof draft)[K][number]) =>
    setDraft({ ...draft, [key]: draft[key].map((item, at) => at === index ? value : item) })
  const removeAt = (key: keyof typeof draft, index: number) => setDraft({ ...draft, [key]: draft[key].filter((_, at) => at !== index) })
  return <section className="job-section notes-editor" aria-label="Edit notes">
    <div className="transcript-editor-bar">
      <strong>Edit notes</strong>
      <span className="transcript-editor-actions">
        {count > 0 && <small>{count} {count === 1 ? 'section' : 'sections'} changed</small>}
        <button type="button" className="button button-primary" disabled={!count || saving} onClick={() => void save()}>{saving ? 'Saving…' : 'Save changes'}</button>
        <button type="button" className="button button-secondary" disabled={saving} onClick={() => onClose(false)}>Cancel</button>
      </span>
    </div>
    {error && <small className="operation-error" role="alert">{error}</small>}
    <fieldset className="notes-block"><legend>Summary{changed.summary && <em> (changed)</em>}</legend>
      {draft.summary.map((point, index) => <div className="notes-row" key={index}>
        <textarea rows={2} maxLength={600} value={point} aria-label={`Summary point ${index + 1}`} onChange={(event) => setAt('summary', index, event.target.value)} />
        <button type="button" className="icon-button" aria-label={`Remove summary point ${index + 1}`} title="Remove" onClick={() => removeAt('summary', index)}><Trash2 size={16} /></button>
      </div>)}
      <button type="button" className="button button-secondary button-small" onClick={() => setDraft({ ...draft, summary: [...draft.summary, ''] })}><Plus size={14} />Add a point</button>
    </fieldset>
    <fieldset className="notes-block"><legend>Action items{changed.actions && <em> (changed)</em>}</legend>
      {draft.actions.map((item, index) => <div className="notes-row notes-row-fields" key={index}>
        <input type="text" className="notes-wide" maxLength={400} value={item.task} placeholder="What needs doing" aria-label={`Task of action item ${index + 1}`} onChange={(event) => setAt('actions', index, { ...item, task: event.target.value })} />
        <input type="text" maxLength={80} value={item.owner ?? ''} placeholder="Owner" aria-label={`Owner of action item ${index + 1}`} onChange={(event) => setAt('actions', index, { ...item, owner: event.target.value })} />
        <input type="text" maxLength={80} value={item.due ?? ''} placeholder="Due" aria-label={`Due date of action item ${index + 1}`} onChange={(event) => setAt('actions', index, { ...item, due: event.target.value })} />
        <input type="text" maxLength={80} value={item.time ?? ''} placeholder="Time" aria-label={`Time in the meeting of action item ${index + 1}`} onChange={(event) => setAt('actions', index, { ...item, time: event.target.value })} />
        <button type="button" className="icon-button" aria-label={`Remove action item ${index + 1}`} title="Remove" onClick={() => removeAt('actions', index)}><Trash2 size={16} /></button>
      </div>)}
      <button type="button" className="button button-secondary button-small" onClick={() => setDraft({ ...draft, actions: [...draft.actions, { task: '' }] })}><Plus size={14} />Add an action item</button>
    </fieldset>
    <fieldset className="notes-block"><legend>Decisions{changed.decisions && <em> (changed)</em>}</legend>
      {draft.decisions.map((item, index) => <div className="notes-row notes-row-fields" key={index}>
        <input type="text" className="notes-wide" maxLength={400} value={item.decision} placeholder="What was decided" aria-label={`Text of decision ${index + 1}`} onChange={(event) => setAt('decisions', index, { ...item, decision: event.target.value })} />
        <input type="text" maxLength={80} value={item.by ?? ''} placeholder="Decided by" aria-label={`Who made decision ${index + 1}`} onChange={(event) => setAt('decisions', index, { ...item, by: event.target.value })} />
        <input type="text" maxLength={80} value={item.time ?? ''} placeholder="Time" aria-label={`Time in the meeting of decision ${index + 1}`} onChange={(event) => setAt('decisions', index, { ...item, time: event.target.value })} />
        <button type="button" className="icon-button" aria-label={`Remove decision ${index + 1}`} title="Remove" onClick={() => removeAt('decisions', index)}><Trash2 size={16} /></button>
      </div>)}
      <button type="button" className="button button-secondary button-small" onClick={() => setDraft({ ...draft, decisions: [...draft.decisions, { decision: '' }] })}><Plus size={14} />Add a decision</button>
    </fieldset>
  </section>
}

const SECTION = { summary: 'Summary', actions: 'Action items', decisions: 'Decisions', transcript: 'Transcript' } as Record<string, string>
const KIND = { added: 'Added', removed: 'Removed', changed: 'Changed', renamed: 'Renamed' } as const
const when = (iso: string) => { const date = new Date(iso); return Number.isNaN(date.getTime()) ? iso : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) }

/** What people changed in a meeting's notes and transcript after it was made, newest first. Nothing is shown for a
 * meeting nobody has edited. `version` changes after a save, so the list is read again. */
export function MeetingHistory({ url, version }: { url: string; version: number }) {
  const { loaded } = useMeetingRecord(url, version)
  if (!loaded || loaded.history.length === 0) return null
  const entries = [...loaded.history].reverse()
  return <details className="job-section job-document disclosure meeting-history">
    <summary><ChevronDown size={16} aria-hidden="true" className="disclosure-chevron" />Change history <small>({entries.length})</small></summary>
    <ol className="history-entries">{entries.map((entry) => <li key={`${entry.revision}-${entry.at}`} className="history-entry">
      <div className="history-entry-head"><strong>Edit {entry.revision - 1}</strong><time dateTime={entry.at}>{when(entry.at)}</time></div>
      <ul className="history-changes">{entry.changes.map((change, index) => <li key={index} className={`history-change history-${change.kind}`}>
        <span className="history-tag">{KIND[change.kind]} · {SECTION[change.section] ?? change.section}{change.detail ? ` · ${change.detail}` : ''}</span>
        {change.before != null && <del>{change.before}</del>}
        {change.after != null && <ins>{change.after}</ins>}
      </li>)}</ul>
      {entry.more ? <small>{entry.more} more changes not listed.</small> : null}
    </li>)}</ol>
  </details>
}
