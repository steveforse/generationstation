import { Clapperboard, Image, MessageCircleMore, MessageSquare, Music, Server } from 'lucide-react'

/** The icon for a model by what it makes, from the host's `workload` (text, music, image, video, speech). */
export function WorkloadIcon({ workload, size = 20 }: { workload: string; size?: number }) {
  switch (workload) {
    case 'text': return <MessageSquare size={size} aria-hidden="true" />
    case 'music': return <Music size={size} aria-hidden="true" />
    case 'image': return <Image size={size} aria-hidden="true" />
    case 'video': return <Clapperboard size={size} aria-hidden="true" />
    case 'speech': return <MessageCircleMore size={size} aria-hidden="true" />
    default: return <Server size={size} aria-hidden="true" />
  }
}

/** Sidebar, Overview and Models page group by what a model makes, in this order (text models, which chat, first);
 * anything else goes under "Other", last. */
export const WORKLOAD_GROUPS: ReadonlyArray<readonly [string, string]> = [['text', 'Text'], ['speech', 'Speech'], ['image', 'Pictures'], ['video', 'Video'], ['music', 'Music']]

/** Items grouped by workload in WORKLOAD_GROUPS order, keeping their order within a group; empty groups are left out. */
export function groupByWorkload<T>(items: T[], workloadOf: (item: T) => string) {
  const known = new Set(WORKLOAD_GROUPS.map(([key]) => key))
  const groups = WORKLOAD_GROUPS.map(([key, label]) => ({ key, label, items: items.filter((item) => workloadOf(item) === key) }))
  groups.push({ key: 'other', label: 'Other', items: items.filter((item) => !known.has(workloadOf(item))) })
  return groups.filter((group) => group.items.length > 0)
}
