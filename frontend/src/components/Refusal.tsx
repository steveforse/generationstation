import { AlertCircle } from 'lucide-react'
import { formatBytes } from '../api'
import type { Gpu, Refusal } from '../types'

export function RefusalDetails({ refusal, gpus }: { refusal: Refusal; gpus?: Gpu[] }) {
  const resourceName = (resource: string) => {
    if (resource === 'ram') return 'System RAM'
    const gpu = resource.startsWith('gpu:') ? gpus?.find((item) => item.id === resource.slice(4)) : undefined
    return gpu ? gpu.name : resource
  }
  return <div className="refusal-details" role="alert"><div><AlertCircle size={15} /><strong>{refusal.code}</strong><span>{refusal.message}</span></div>{refusal.resources?.map((resource, index) => <div className="refusal-resource" key={`${resource.resource}-${index}`}><strong>{resourceName(resource.resource)}</strong><span>Required {formatBytes(resource.required_bytes)}</span><span>Available {formatBytes(resource.available_bytes)}</span>{resource.headroom_bytes !== undefined && <span>Headroom {formatBytes(resource.headroom_bytes)}</span>}</div>)}</div>
}
