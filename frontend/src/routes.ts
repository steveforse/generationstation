import { useEffect, useState } from 'react'

export type Route =
  | { page: 'overview' }
  | { page: 'connections' }
  | { page: 'service'; hostId: string; modelId: string }
  | { page: 'profiles'; hostId: string }

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  if (parts[0] === 'connections') return { page: 'connections' }
  if (parts[0] === 'hosts' && parts[1] && parts[2] === 'services' && parts[3]) return { page: 'service', hostId: parts[1], modelId: parts[3] }
  if (parts[0] === 'hosts' && parts[1] && parts[2] === 'profiles') return { page: 'profiles', hostId: parts[1] }
  return { page: 'overview' }
}

export function href(route: Route) {
  switch (route.page) {
    case 'connections': return '#/connections'
    case 'service': return `#/hosts/${encodeURIComponent(route.hostId)}/services/${encodeURIComponent(route.modelId)}`
    case 'profiles': return `#/hosts/${encodeURIComponent(route.hostId)}/profiles`
    default: return '#/overview'
  }
}

export function useRoute() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash))
  useEffect(() => {
    const onChange = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', onChange)
    return () => window.removeEventListener('hashchange', onChange)
  }, [])
  return route
}
