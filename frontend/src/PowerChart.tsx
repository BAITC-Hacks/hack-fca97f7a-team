import { useEffect, useRef, useState } from 'react'
import type { Ref } from 'react'
import type { ForecastResult } from './types'
import { exportChart } from './chartExport'
import { ru, localTime, percent } from './ru'

function ChartGraphic({ result, width, svgRef, exported = false }: { result: ForecastResult, width: number, svgRef?: Ref<SVGSVGElement>, exported?: boolean }) {
  const hours = result.hours
  const compact = width < 600
  const height = compact ? 310 : 420
  const left = compact ? 36 : 58, right = compact ? 12 : 28, top = compact ? 92 : 106, bottom = compact ? 88 : 86
  const x = (i: number) => left + i * (width - left - right) / Math.max(1, hours.length - 1)
  const y = (value: number) => top + (1 - value) * (height - top - bottom)
  const line = (key: 'power_norm') => hours.map((h, i) => `${i ? 'L' : 'M'}${x(i).toFixed(2)},${y(h[key]).toFixed(2)}`).join(' ')
  const labels = Array.from(new Set(compact ? [0, Math.round((hours.length - 1) / 2), hours.length - 1] : [0, Math.round((hours.length - 1) / 4), Math.round((hours.length - 1) / 2), Math.round(3 * (hours.length - 1) / 4), hours.length - 1]))
  const dateFormat = new Intl.DateTimeFormat('ru-RU', { timeZone: result.timezone, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
  const id = exported ? 'export-chart' : 'power-chart'
  return <svg ref={svgRef} width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby={`${id}-title ${id}-description`} fontFamily="Arial, sans-serif">
    <title id={`${id}-title`}>{ru.chartAria}</title>
    <desc id={`${id}-description`}>{result.turbine_id}, {result.horizon_hours} ч. {ru.normalized}. {result.timezone}.</desc>
    <rect width={width} height={height} fill="#ffffff" />
    <text x={left} y={28} fill="#182b27" fontSize={compact ? 16 : 20} fontWeight={600}>{ru.forecast} · {result.turbine_id} · {result.horizon_hours} ч</text>
    <text x={left} y={49} fill="#687772" fontSize={compact ? 10 : 12}>{ru.originDate}: {compact ? dateFormat.format(new Date(result.origin)) : localTime(result.origin, result.timezone)}</text>
    {compact && <text x={left} y={64} fill="#687772" fontSize={10}>{result.timezone}</text>}
    <text x={left} y={80} fill="#687772" fontSize={compact ? 10 : 12}>{ru.chartAxis}</text>
    {[0, .25, .5, .75, 1].map(v => <g key={v}>
      <line x1={left} x2={width - right} y1={y(v)} y2={y(v)} stroke="#e9eeeb" strokeWidth={1} />
      <text x={left - 10} y={y(v) + 4} fill="#6a7772" fontSize={compact ? 10 : 12} textAnchor="end">{v * 100}</text>
    </g>)}
    <path d={`${line('power_norm')} L${x(hours.length - 1)},${y(0)} L${x(0)},${y(0)} Z`} fill="#edf5f0" />
    <path d={line('power_norm')} fill="none" stroke="#267054" strokeWidth={compact ? 2 : 3} strokeLinecap="round" strokeLinejoin="round" />
    {hours.map((hour, i) => <circle key={hour.valid_at} cx={x(i)} cy={y(hour.power_norm)} r={5} fill="transparent"><title>{localTime(hour.valid_at, result.timezone)}: {percent(hour.power_norm)}</title></circle>)}
    {labels.map(i => <text key={i} x={x(i)} y={height - bottom + 24} fill="#6a7772" fontSize={compact ? 9 : 12} textAnchor={i === 0 ? 'start' : i === hours.length - 1 ? 'end' : 'middle'}>{dateFormat.format(new Date(hours[i].valid_at))}</text>)}
    <line x1={left} x2={left + 18} y1={height - 30} y2={height - 30} stroke="#267054" strokeWidth={3} />
    <text x={left + 25} y={height - 26} fill="#475a51" fontSize={compact ? 10 : 12}>{ru.forecast}</text>
    <text x={compact ? left : width - right} y={compact ? height - 7 : height - 26} fill="#687772" fontSize={compact ? 9 : 12} textAnchor={compact ? 'start' : 'end'}>{result.mode === 'live' ? ru.live : result.weather_provenance.provenance_status === 'fixture' ? ru.fixture : ru.archive}</text>
  </svg>
}

export default function PowerChart({ result }: { result: ForecastResult }) {
  const exportRef = useRef<SVGSVGElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(800)
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const container = containerRef.current
    if (!container) return
    const observer = new ResizeObserver(entries => setWidth(Math.max(260, Math.floor(entries[0].contentRect.width))))
    observer.observe(container)
    return () => observer.disconnect()
  }, [])

  async function download(format: 'png' | 'svg') {
    if (!exportRef.current) return
    setExporting(true); setError('')
    try {
      await exportChart(exportRef.current, `forecast-${result.turbine_id}-${result.origin.slice(0, 10)}-${result.horizon_hours}h`, format)
    } catch {
      setError(ru.chartExportError)
    } finally { setExporting(false) }
  }

  return <div className="forecast-chart">
    <div className="chart-wrap" ref={containerRef}><ChartGraphic result={result} width={width} /></div>
    <div hidden aria-hidden="true"><ChartGraphic result={result} width={1100} svgRef={exportRef} exported /></div>
    <div className="chart-downloads"><span>{ru.downloadChart}</span><button type="button" className="text-button" disabled={exporting} onClick={() => download('png')}>{ru.downloadPng}</button><button type="button" className="text-button" disabled={exporting} onClick={() => download('svg')}>{ru.downloadSvg}</button></div>
    {error && <div className="error-banner" role="alert">{error}</div>}
  </div>
}
