import { ru } from './ru'

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// All chart styling is inside the SVG, so exports have no CSS or network dependency.
export async function exportChart(svg: SVGSVGElement, filename: string, format: 'svg' | 'png'): Promise<Blob> {
  const clone = svg.cloneNode(true) as SVGSVGElement
  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  const source = new XMLSerializer().serializeToString(clone)
  const vector = new Blob([source], { type: 'image/svg+xml;charset=utf-8' })
  if (format === 'svg') {
    saveBlob(vector, `${filename}.svg`)
    return vector
  }
  const url = URL.createObjectURL(vector)
  try {
    const image = new Image()
    await new Promise<void>((resolve, reject) => {
      image.onload = () => resolve()
      image.onerror = () => reject(new Error(ru.chartExportError))
      image.src = url
    })
    const canvas = document.createElement('canvas')
    canvas.width = svg.viewBox.baseVal.width * 2
    canvas.height = svg.viewBox.baseVal.height * 2
    const context = canvas.getContext('2d')
    if (!context) throw new Error(ru.chartExportError)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    const raster = await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob(blob => blob ? resolve(blob) : reject(new Error(ru.chartExportError)), 'image/png')
    })
    saveBlob(raster, `${filename}.png`)
    return raster
  } finally {
    URL.revokeObjectURL(url)
  }
}
