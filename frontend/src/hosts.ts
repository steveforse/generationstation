// Saved hosts live in this browser's storage, including their access tokens (the user chose
// "remember on this device"). Storage can be unavailable; then hosts last for this page only.
export type SavedHost = { id: string; label: string; url: string; token: string }

const HOSTS_KEY = 'generation-station.hosts'
const OLD_URL_KEY = 'generation-station.server-url'

export function newHostId() {
  const bytes = crypto.getRandomValues(new Uint8Array(6))
  return 'h' + Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
}

function valid(entry: unknown): entry is SavedHost {
  if (!entry || typeof entry !== 'object') return false
  const host = entry as Record<string, unknown>
  return typeof host.id === 'string' && /^[A-Za-z0-9_-]{1,40}$/.test(host.id) && typeof host.label === 'string'
    && typeof host.url === 'string' && typeof host.token === 'string'
}

export function loadHosts(): SavedHost[] {
  try {
    const raw = localStorage.getItem(HOSTS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed)) return parsed.filter(valid)
    }
    const oldUrl = localStorage.getItem(OLD_URL_KEY)
    return [{ id: 'local', label: '', url: oldUrl ?? '', token: '' }]
  } catch {
    return [{ id: 'local', label: '', url: '', token: '' }]
  }
}

export function saveHosts(hosts: SavedHost[]) {
  try {
    localStorage.setItem(HOSTS_KEY, JSON.stringify(hosts))
    localStorage.removeItem(OLD_URL_KEY)
  } catch { /* storage unavailable: hosts stay in memory for this page */ }
}
