import { useEffect, useState } from 'react'
import { Check, Copy, Plug } from 'lucide-react'
import { JobModal } from './Runtime'
import type { SavedHost } from '../hosts'
import type { HostSession } from '../session'
import type { Runtime } from '../types'

type Kind = 'chat' | 'decide'
const KEY = 'generation-station.connect-tool' // the tool last picked, per device, for each kind

/** The name a tool uses for this computer: loopback for a server that listens only here, else the name this dashboard used. */
export function addressOf(runtime: Runtime, host: SavedHost) {
  let name = '127.0.0.1'
  if (runtime.bind === '0.0.0.0') {
    try { name = host.url ? new URL(host.url).hostname : window.location.hostname } catch { name = window.location.hostname }
  }
  return `http://${name.includes(':') ? `[${name}]` : name}:${runtime.port}`
}

type Snippet = { title: string; where?: string; code: string }

function chatSnippets(address: string, model: string, name: string): Record<string, Snippet> {
  const base = `${address}/v1`
  return {
    'Aider': { title: 'Aider', where: 'In a shell, then start Aider:', code: `export OPENAI_API_BASE=${base}\nexport OPENAI_API_KEY=none\naider --model openai/${model}` },
    'OpenCode': { title: 'OpenCode', where: 'In opencode.json (the project folder or ~/.config/opencode), then pick the model with /models:', code: JSON.stringify({
      $schema: 'https://opencode.ai/config.json',
      provider: { 'generation-station': { npm: '@ai-sdk/openai-compatible', name: 'Generation Station', options: { baseURL: base }, models: { [model]: { name } } } },
    }, null, 2) },
    'Open WebUI': { title: 'Open WebUI', where: 'Admin Settings, Connections, add an OpenAI API connection:', code: `URL: ${base}\nKey: none (any text; the server has no login)\nModel: ${model}` },
    'curl': { title: 'curl', code: `curl ${base}/chat/completions \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify({ model, messages: [{ role: 'user', content: 'Hello' }] })}'` },
    'Python (OpenAI SDK)': { title: 'Python', code: `from openai import OpenAI\n\nclient = OpenAI(base_url="${base}", api_key="none")\nreply = client.chat.completions.create(model="${model}", messages=[{"role": "user", "content": "Hello"}])\nprint(reply.choices[0].message.content)` },
  }
}

const SAMPLE = { state: 'Hi, I was charged twice for my March order.', questions: { team: { type: 'choice', instructions: 'Which team should handle this?', criteria: { billing: 'Charges and refunds', shipping: 'Deliveries' } }, urgent: { type: 'noul', instructions: 'Does this need a reply today?' } } }

function decideSnippets(address: string): Record<string, Snippet> {
  const url = `${address}/v1/systemone`
  return {
    'curl': { title: 'curl', code: `curl ${url} \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(SAMPLE)}'` },
    'Python (requests)': { title: 'Python', code: `import requests\n\nreply = requests.post("${url}", json=${JSON.stringify(SAMPLE, null, 2).replace(/^/gm, '    ').trimStart()})\nprint(reply.json()["answers"])` },
    'JavaScript (fetch)': { title: 'JavaScript', code: `const reply = await fetch("${url}", {\n  method: "POST",\n  headers: { "Content-Type": "application/json" },\n  body: JSON.stringify(${JSON.stringify(SAMPLE, null, 2).replace(/^/gm, '  ').trimStart()}),\n})\nconsole.log((await reply.json()).answers)` },
  }
}

function CopyButton({ text, label }: { text: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return <button type="button" className="icon-button" aria-label={label} title={label} onClick={async () => {
    try { await navigator.clipboard.writeText(text); setCopied(true); window.setTimeout(() => setCopied(false), 1500) } catch { /* the text is shown to select */ }
  }}>{copied ? <Check size={16} aria-hidden="true" /> : <Copy size={16} aria-hidden="true" />}</button>
}

/** A link that opens how to reach a running model directly from a tool on the host: its own address, and the settings of the tool picked. */
export function ConnectLink({ kind, runtime, host, session }: { kind: Kind; runtime: Runtime; host: SavedHost; session: HostSession }) {
  const [open, setOpen] = useState(false)
  const [model, setModel] = useState<string | null>(null)
  const [tool, setTool] = useState(() => { try { return localStorage.getItem(`${KEY}.${kind}`) ?? '' } catch { return '' } })
  useEffect(() => {
    if (kind !== 'chat' || !open) return
    let live = true
    setModel(null)
    session.connection(runtime).then((answer) => { if (live) setModel(answer.model) }).catch(() => { if (live) setModel(null) })
    return () => { live = false }
  }, [kind, open, runtime.id, session]) // eslint-disable-line react-hooks/exhaustive-deps
  const address = addressOf(runtime, host)
  const snippets = kind === 'chat' ? chatSnippets(address, model ?? 'default', runtime.name) : decideSnippets(address)
  const names = Object.keys(snippets)
  const chosen = names.includes(tool) ? tool : names[0]
  const snippet = snippets[chosen]
  const local = runtime.bind !== '0.0.0.0'
  return <>
    <button type="button" className="text-button connect-link" onClick={() => setOpen(true)} title={`How to connect a tool to ${runtime.name}`}><Plug size={16} aria-hidden="true" />Connect a tool</button>
    <JobModal open={open} onClose={() => setOpen(false)} title={`Connect a tool to ${runtime.name}`}>
    <div className="connect-body">
      <p className="connect-address"><span>Address</span><code>{kind === 'chat' ? `${address}/v1` : `${address}/v1/systemone`}</code>
        <CopyButton text={kind === 'chat' ? `${address}/v1` : `${address}/v1/systemone`} label="Copy the address" /></p>
      <p className="connect-note">{local ? 'This model listens on this computer only, so use the tool on this computer. ' : 'This model listens on every network interface and has no login: use it only on a network you trust. '}
        {kind === 'chat' ? 'It speaks the OpenAI chat API; no key is needed, so any text will do.' : 'It speaks TypeSafe’s System One API: the same request works against the hosted service.'}
        {local && <> To reach it from another machine, set <code>"host": "0.0.0.0"</code> on this model in <code>runtimes.json</code> and restart it.</>}</p>
      <label className="connect-tool"><span>Tool</span>
        <select aria-label="Tool" value={chosen} onChange={(event) => { setTool(event.target.value); try { localStorage.setItem(`${KEY}.${kind}`, event.target.value) } catch { /* per-device preference only */ } }}>
          {names.map((item) => <option key={item} value={item}>{item}</option>)}
        </select></label>
      {snippet.where && <p className="connect-where">{snippet.where}</p>}
      <div className="connect-code"><pre><code>{snippet.code}</code></pre><CopyButton text={snippet.code} label={`Copy the ${snippet.title} settings`} /></div>
    </div>
    </JobModal>
  </>
}
