import { useId, useState } from 'react'
import { Check, ChevronDown, Loader2, Pencil, Trash2, X } from 'lucide-react'
import type { Voice } from '../types'

type Props = {
  voices: Voice[]
  /** Whether the model open on the page can speak in a cloned voice. */
  canClone: boolean; modelName: string
  /** The sample on the form, when there is one ready: it can be kept as a voice. */
  sampleReady: boolean
  onUse: (voice: Voice) => Promise<string>
  onSaveSample: (name: string) => Promise<string>
  onUpdate: (voice: Voice, name: string, text: string) => Promise<string>
  onDelete: (voice: Voice) => Promise<string>
}

/** The saved voices, to pick from for any model that clones, and a way to keep the sample on the form. Folded away until wanted. */
export function VoiceLibrary({ voices, canClone, modelName, sampleReady, onUse, onSaveSample, onUpdate, onDelete }: Props) {
  const [busy, setBusy] = useState('')
  const [problem, setProblem] = useState('')
  const [editing, setEditing] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [text, setText] = useState('')
  const [confirming, setConfirming] = useState<string | null>(null)
  const [newName, setNewName] = useState('')
  const [saving, setSaving] = useState(false)
  const id = useId()
  const run = async (key: string, action: () => Promise<string>) => { setBusy(key); setProblem(''); const failed = await action(); setBusy(''); if (failed) setProblem(failed); return !failed }
  return <details className="speech-library disclosure">
    <summary><ChevronDown size={16} aria-hidden="true" className="disclosure-chevron" />Saved voices{voices.length ? ` (${voices.length})` : ''}</summary>
    <p className="field-help">Only keep voices you have permission to use.</p>
    {voices.length === 0 && <p className="field-help">None yet. Save a sample from the form, or a result's sound with Save as voice.</p>}
    <ul className="voice-list">
      {voices.map((voice) => <li key={voice.id} className="voice-row">
        {editing === voice.id
          ? <form className="voice-edit" aria-label={`Rename ${voice.name}`} onSubmit={async (event) => { event.preventDefault(); if (await run(voice.id, () => onUpdate(voice, name, text))) setEditing(null) }}>
            <label htmlFor={`${id}-n-${voice.id}`}>Name</label>
            <input id={`${id}-n-${voice.id}`} className="text-input" value={name} maxLength={80} required onChange={(event) => setName(event.target.value)} />
            <label htmlFor={`${id}-t-${voice.id}`}>What the sample says</label>
            <textarea id={`${id}-t-${voice.id}`} className="text-input" rows={2} maxLength={1000} value={text} onChange={(event) => setText(event.target.value)} />
            <div className="button-row"><button type="submit" className="button button-primary" disabled={!!busy || !name.trim()}><Check size={16} />Save</button>
              <button type="button" className="button button-secondary" onClick={() => setEditing(null)}>Cancel</button></div>
          </form>
          : <>
            <div className="voice-name"><strong>{voice.name}</strong>{voice.sample_text && <span className="voice-text">{voice.sample_text}</span>}</div>
            <div className="voice-actions">
              {confirming === voice.id
                ? <><span>Delete {voice.name}?</span>
                  <button type="button" className="button button-secondary" disabled={!!busy} onClick={async () => { if (await run(voice.id, () => onDelete(voice))) setConfirming(null) }}>Delete</button>
                  <button type="button" className="button button-secondary" onClick={() => setConfirming(null)}>Keep</button></>
                : <>
                  <button type="button" className="button button-secondary" disabled={!canClone || !!busy} aria-label={`Use ${voice.name}`}
                    title={canClone ? `Speak in this voice with ${modelName}` : `${modelName} cannot clone a voice`} onClick={() => void run(voice.id, () => onUse(voice))}>
                    {busy === voice.id ? <Loader2 size={16} className="spin" /> : null}Use</button>
                  <button type="button" className="icon-button" aria-label={`Rename ${voice.name}`} title="Rename" onClick={() => { setEditing(voice.id); setName(voice.name); setText(voice.sample_text) }}><Pencil size={16} /></button>
                  <button type="button" className="icon-button" aria-label={`Delete ${voice.name}`} title="Delete" onClick={() => setConfirming(voice.id)}><Trash2 size={16} /></button>
                </>}
            </div>
          </>}
      </li>)}
    </ul>
    {sampleReady && (saving
      ? <form className="voice-edit" aria-label="Save the sample as a voice" onSubmit={async (event) => { event.preventDefault(); if (await run('new', () => onSaveSample(newName))) { setSaving(false); setNewName('') } }}>
        <label htmlFor={`${id}-new`}>Name for the sample on the form</label>
        <input id={`${id}-new`} className="text-input" value={newName} maxLength={80} required onChange={(event) => setNewName(event.target.value)} />
        <div className="button-row"><button type="submit" className="button button-primary" disabled={!!busy || !newName.trim()}>{busy === 'new' ? <Loader2 size={16} className="spin" /> : null}Save voice</button>
          <button type="button" className="button button-secondary" onClick={() => setSaving(false)}><X size={16} />Cancel</button></div>
      </form>
      : <button type="button" className="button button-secondary" onClick={() => setSaving(true)}>Save the sample on the form as a voice</button>)}
    {problem && <p className="form-error" role="alert">{problem}</p>}
  </details>
}
