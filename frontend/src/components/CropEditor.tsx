import { useEffect, useRef, useState } from 'react'

/** "x,y,w,h" fractions of the picture. */
export type Box = { x: number; y: number; w: number; h: number }

export function parseBox(value: string): Box | null {
  const parts = value.split(',').map(Number)
  if (parts.length !== 4 || parts.some((part) => !Number.isFinite(part))) return null
  const [x, y, w, h] = parts
  return { x, y, w, h }
}

export const formatBox = (box: Box) => [box.x, box.y, box.w, box.h].map((part) => part.toFixed(4)).join(',')

/** The largest box of `aspect` (width / height of the clip) that fits a picture, scaled by `zoom`, centred on (cx, cy). */
function fitBox(pictureAspect: number, aspect: number, zoom: number, cx = 0.5, cy = 0.5): Box {
  const full = pictureAspect > aspect ? { w: aspect / pictureAspect, h: 1 } : { w: 1, h: pictureAspect / aspect }
  const w = full.w * zoom
  const h = full.h * zoom
  return { w, h, x: Math.min(Math.max(cx - w / 2, 0), 1 - w), y: Math.min(Math.max(cy - h / 2, 0), 1 - h) }
}

/**
 * Choose which part of a picture becomes the frame when the clip's shape differs from the picture's:
 * a box in the clip's proportions over the picture. Drag it (mouse or finger), move it with the arrow
 * keys, and make it smaller with the zoom slider to crop tighter. An empty value means centred, full size.
 */
export function CropEditor({ src, label, aspect, value, onChange }: {
  src: string; label: string; aspect: number; value: string; onChange: (value: string) => void
}) {
  const frame = useRef<HTMLDivElement>(null)
  const [pictureAspect, setPictureAspect] = useState<number | null>(null)
  const drag = useRef<{ x: number; y: number; box: Box } | null>(null)
  const parsed = parseBox(value)
  const zoomOf = (box: Box, pa: number) => box.w / fitBox(pa, aspect, 1).w
  // A saved box only counts if it still has the clip's proportions (the shape may have changed since).
  const box = pictureAspect && parsed && Math.abs((parsed.w * pictureAspect) / parsed.h - aspect) < 0.02 ? parsed
    : pictureAspect ? fitBox(pictureAspect, aspect, 1) : null
  useEffect(() => {
    if (pictureAspect && parsed && box !== parsed) onChange('')
    // Clear a box made for another shape.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aspect, pictureAspect])
  const move = (next: Box) => onChange(formatBox({ ...next, x: Math.min(Math.max(next.x, 0), 1 - next.w), y: Math.min(Math.max(next.y, 0), 1 - next.h) }))
  const zoom = box && pictureAspect ? zoomOf(box, pictureAspect) : 1
  return <div className="crop-editor">
    <div className="crop-frame" ref={frame} style={pictureAspect ? { aspectRatio: String(pictureAspect), width: `min(100%, ${Math.round(280 * pictureAspect)}px)` } : undefined}>
      <img src={src} alt="" draggable={false} onLoad={(event) => setPictureAspect(event.currentTarget.naturalWidth / event.currentTarget.naturalHeight)} />
      {box && <div className="crop-box" role="slider" tabIndex={0} aria-label={`Framing for ${label}: drag, or use the arrow keys`}
        aria-valuetext={`${Math.round(box.x * 100)}% from the left, ${Math.round(box.y * 100)}% from the top, ${Math.round(zoom * 100)}% size`}
        style={{ left: `${box.x * 100}%`, top: `${box.y * 100}%`, width: `${box.w * 100}%`, height: `${box.h * 100}%` }}
        onPointerDown={(event) => { event.currentTarget.setPointerCapture(event.pointerId); drag.current = { x: event.clientX, y: event.clientY, box } }}
        onPointerMove={(event) => {
          const start = drag.current
          const rect = frame.current?.getBoundingClientRect()
          if (!start || !rect) return
          move({ ...start.box, x: start.box.x + (event.clientX - start.x) / rect.width, y: start.box.y + (event.clientY - start.y) / rect.height })
        }}
        onPointerUp={() => { drag.current = null }} onPointerCancel={() => { drag.current = null }}
        onKeyDown={(event) => {
          const step = event.shiftKey ? 0.1 : 0.02
          const delta = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key]
          if (!delta) return
          event.preventDefault()
          move({ ...box, x: box.x + delta[0], y: box.y + delta[1] })
        }} />}
    </div>
    {box && pictureAspect && <label className="crop-zoom">
      <span>Zoom</span>
      <input type="range" min={30} max={100} value={Math.round(zoom * 100)} aria-label={`Framing size for ${label}`}
        onChange={(event) => onChange(formatBox(fitBox(pictureAspect, aspect, Number(event.target.value) / 100, box.x + box.w / 2, box.y + box.h / 2)))} />
      <button type="button" className="text-button" onClick={() => onChange('')}>Centre</button>
    </label>}
  </div>
}

/** The clip's proportions (width / height) for a shape such as "portrait 9:16", or null for "match picture". */
export function shapeAspect(shape: string, width?: string, height?: string): number | null {
  if (width && height && Number(width) > 0 && Number(height) > 0) return Number(width) / Number(height)
  const match = /(\d+):(\d+)/.exec(shape)
  return match ? Number(match[1]) / Number(match[2]) : null
}
