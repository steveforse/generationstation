import { Clapperboard, Image, MessageSquare, Music, Server } from 'lucide-react'

/** The icon for a model by what it makes, from the host's `workload` (text, music, image, video). */
export function WorkloadIcon({ workload, size = 16 }: { workload: string; size?: number }) {
  switch (workload) {
    case 'text': return <MessageSquare size={size} aria-hidden="true" />
    case 'music': return <Music size={size} aria-hidden="true" />
    case 'image': return <Image size={size} aria-hidden="true" />
    case 'video': return <Clapperboard size={size} aria-hidden="true" />
    default: return <Server size={size} aria-hidden="true" />
  }
}
