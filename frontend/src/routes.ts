import { useEffect, useState } from 'react'

export type Route =
  | { page: 'overview' }
  | { page: 'connections' }
  | { page: 'service'; hostId: string; modelId: string }
  | { page: 'models'; hostId: string }
  | { page: 'decide'; hostId: string }
  | { page: 'speech'; hostId: string }
  | { page: 'images'; hostId: string }
  | { page: 'chat'; hostId: string; conversationId?: string }
  | { page: 'logs'; hostId: string; name?: string }
  | { page: 'settings'; hostId: string }

export function parseRoute(hash: string): Route {
  const parts = hash.replace(/^#\/?/, '').split('/').filter(Boolean).map(decodeURIComponent)
  if (parts[0] === 'connections') return { page: 'connections' }
  if (parts[0] === 'hosts' && parts[1] && parts[2] === 'services' && parts[3]) return { page: 'service', hostId: parts[1], modelId: parts[3] }
  if (parts[0] === 'hosts' && parts[1] && parts[2] === 'models') return { page: 'models', hostId: parts[1] }
  if (parts[0] === 'hosts' && parts[1] && parts[2] === 'decide') return { page: 'decide', hostId: parts[1] }
  if (parts[0] === 'hosts' && parts[1] && parts[2] === 'images') return { page: 'images', hostId: parts[1] }
  if (parts[0] === 'hosts' && parts[1] && parts[2] === 'speech') return { page: 'speech', hostId: parts[1] }
  if (parts[0] === 'hosts' && parts[1] && parts[2] === 'settings') return { page: 'settings', hostId: parts[1] }
  if (parts[0] === 'hosts' && parts[1] && parts[2] === 'logs') return { page: 'logs', hostId: parts[1], name: parts[3] || undefined }
  if (parts[0] === 'hosts' && parts[1] && parts[2] === 'chat') return { page: 'chat', hostId: parts[1], conversationId: parts[3] || undefined }
  return { page: 'overview' }
}

export function href(route: Route) {
  switch (route.page) {
    case 'connections': return '#/connections'
    case 'service': return `#/hosts/${encodeURIComponent(route.hostId)}/services/${encodeURIComponent(route.modelId)}`
    case 'decide': return `#/hosts/${encodeURIComponent(route.hostId)}/decide`
    case 'images': return `#/hosts/${encodeURIComponent(route.hostId)}/images`
    case 'speech': return `#/hosts/${encodeURIComponent(route.hostId)}/speech`
    case 'models': return `#/hosts/${encodeURIComponent(route.hostId)}/models`
    case 'settings': return `#/hosts/${encodeURIComponent(route.hostId)}/settings`
    case 'logs': return `#/hosts/${encodeURIComponent(route.hostId)}/logs${route.name ? `/${encodeURIComponent(route.name)}` : ''}`
    case 'chat': return `#/hosts/${encodeURIComponent(route.hostId)}/chat${route.conversationId ? `/${encodeURIComponent(route.conversationId)}` : ''}`
    default: return '#/overview'
  }
}

/** Where a model's own page is: decision models share the Decide page, speech models the Speech page, picture models the Images page, any other has a page of its own. */
export function modelRoute(hostId: string, modelId: string, runtimes?: { id: string; workload: string }[] | null): Route {
  const workload = runtimes?.find((runtime) => runtime.id === modelId)?.workload
  return workload === 'decision' ? { page: 'decide', hostId } : workload === 'speech' ? { page: 'speech', hostId } : workload === 'image' ? { page: 'images', hostId } : { page: 'service', hostId, modelId }
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
