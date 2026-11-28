/** The last frame of a video as a PNG, taken in the browser (the next clip can then start from where this one ended). */
export async function lastFrame(video: Blob): Promise<Blob> {
  const url = URL.createObjectURL(video)
  try {
    const element = document.createElement('video')
    element.muted = true
    element.preload = 'auto'
    element.src = url
    await new Promise<void>((resolve, reject) => {
      element.onloadedmetadata = () => resolve()
      element.onerror = () => reject(new Error('The clip could not be read.'))
    })
    // Seeking to the very end shows nothing in some browsers: stop a frame short.
    const target = Math.max(0, (Number.isFinite(element.duration) ? element.duration : 0) - 0.05)
    await new Promise<void>((resolve, reject) => {
      element.onseeked = () => resolve()
      element.onerror = () => reject(new Error('The last frame could not be read.'))
      element.currentTime = target
    })
    const canvas = document.createElement('canvas')
    canvas.width = element.videoWidth
    canvas.height = element.videoHeight
    const context = canvas.getContext('2d')
    if (!context || !canvas.width) throw new Error('The last frame could not be read.')
    context.drawImage(element, 0, 0, canvas.width, canvas.height)
    return await new Promise<Blob>((resolve, reject) => canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('The last frame could not be saved.')), 'image/png'))
  } finally {
    URL.revokeObjectURL(url)
  }
}
