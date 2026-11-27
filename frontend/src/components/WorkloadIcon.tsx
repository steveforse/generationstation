import { Clapperboard, Image, MessageSquare, Music, Scale, Server, Volume2 } from 'lucide-react'

/** The icon for a model by what it makes, from the host's `workload` (text, decision, music, image, video, speech). */
export function WorkloadIcon({ workload, size = 20 }: { workload: string; size?: number }) {
  switch (workload) {
    case 'text': return <MessageSquare size={size} aria-hidden="true" />
    case 'decision': return <Scale size={size} aria-hidden="true" />
    case 'music': return <Music size={size} aria-hidden="true" />
    case 'image': return <Image size={size} aria-hidden="true" />
    case 'video': return <Clapperboard size={size} aria-hidden="true" />
    case 'speech': return <Volume2 size={size} aria-hidden="true" />
    default: return <Server size={size} aria-hidden="true" />
  }
}

/** Sidebar, Overview and Models page group by what a model makes, in this order (text models, which chat, first);
 * anything else goes under "Other", last. */
export const WORKLOAD_GROUPS: ReadonlyArray<readonly [string, string]> = [['text', 'Text'], ['decision', 'Decide'], ['speech', 'Speech'], ['image', 'Images'], ['video', 'Video'], ['music', 'Music']]

/** Items grouped by workload in WORKLOAD_GROUPS order, keeping their order within a group; empty groups are left out. */
export function groupByWorkload<T>(items: T[], workloadOf: (item: T) => string, nameOf?: (item: T) => string) {
  const known = new Set(WORKLOAD_GROUPS.map(([key]) => key))
  // With a name, each group is alphabetical (case and accents ignored); without one, the catalog's order.
  const ordered = (list: T[]) => nameOf ? [...list].sort((a, b) => nameOf(a).localeCompare(nameOf(b), undefined, { sensitivity: 'base' })) : list
  const groups = WORKLOAD_GROUPS.map(([key, label]) => ({ key, label, items: ordered(items.filter((item) => workloadOf(item) === key)) }))
  groups.push({ key: 'other', label: 'Other', items: ordered(items.filter((item) => !known.has(workloadOf(item)))) })
  return groups.filter((group) => group.items.length > 0)
}
