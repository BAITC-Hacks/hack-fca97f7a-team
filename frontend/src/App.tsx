import { useEffect, useRef, useState } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip } from 'react-leaflet'
import { askQuestion, createForecast, downloadCsv, explainForecast, getSites } from './api'
import type { Explanation, ForecastHour, ForecastRequest, ForecastResult, Site, WeatherMode } from './types'
import { ru, percent, decimal, signedPoints, localTime, fieldLabel, statusLabel, stepLabel, provenanceLabel, coordinateLabel, provenanceValue, warningLabel, traceDetail } from './ru'

const FIRST_DATE = '2026-01-31'
const LOCAL_ZONE = 'Asia/Almaty'

function originForDate(date: string): string {
  // The supported 2026 replay dates are UTC+05:00 in Asia/Almaty.
  return `${date}T18:00:00Z`
}

function nextDate(date: string): string {
  const day = new Date(`${date}T12:00:00Z`)
  day.setUTCDate(day.getUTCDate() + 1)
  return day.toISOString().slice(0, 10)
}

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return ru.requestFailed
}

function PowerChart({ hours, zone }: { hours: ForecastHour[], zone: string }) {
  const width = 940, height = 265, left = 42, right = 12, top = 12, bottom = 31
  const x = (i: number) => left + i * (width - left - right) / Math.max(1, hours.length - 1)
  const y = (v: number) => top + (1 - v) * (height - top - bottom)
  const line = (key: 'power_norm' | 'baseline_norm') => hours.map((h, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(h[key]).toFixed(1)}`).join(' ')
  return <div className="chart-wrap" role="img" aria-label={ru.chartAria}>
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {[0, .25, .5, .75, 1].map(v => <g key={v}><line className="grid-line" x1={left} x2={width - right} y1={y(v)} y2={y(v)} /><text className="axis-label" x={left - 9} y={y(v) + 4} textAnchor="end">{Math.round(v * 100)}</text></g>)}
      <path className="baseline-line" d={line('baseline_norm')} />
      <path className="power-line" d={line('power_norm')} />
      {[0, Math.floor((hours.length - 1) / 2), hours.length - 1].map(i => <text key={i} className="axis-label" x={x(i)} y={height - 5} textAnchor={i === 0 ? 'start' : i === hours.length - 1 ? 'end' : 'middle'}>{localTime(hours[i].valid_at, zone)}</text>)}
    </svg>
  </div>
}

function SiteMap({ sites, selected, onSelect }: { sites: Site[], selected: string, onSelect: (id: string) => void }) {
  const center: [number, number] = sites.length ? [sites.reduce((sum, s) => sum + s.latitude, 0) / sites.length, sites.reduce((sum, s) => sum + s.longitude, 0) / sites.length] : [0, 0]
  return <div className="map-frame">
    <MapContainer center={center} zoom={12} scrollWheelZoom={false} className="site-map" key={sites.map(s => s.turbine_id).join('-')}>
      <TileLayer attribution='&copy; участники <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {sites.map(site => <CircleMarker key={site.turbine_id} center={[site.latitude, site.longitude]} radius={selected === site.turbine_id ? 13 : 11} pathOptions={{ color: selected === site.turbine_id ? '#184f45' : '#fff', fillColor: selected === site.turbine_id ? '#b4e86a' : '#266f62', fillOpacity: 1, weight: 3 }} eventHandlers={{ click: () => onSelect(site.turbine_id) }}>
        <Tooltip direction="top" offset={[0, -14]}>{site.turbine_id} · {coordinateLabel(site.coordinate_status)}</Tooltip>
        <Popup>{site.turbine_id} · {coordinateLabel(site.coordinate_status)}</Popup>
      </CircleMarker>)}
    </MapContainer>
    <span className="map-badge">{ru.coordinates}</span>
  </div>
}

function Comparison({ current, previous }: { current: ForecastResult, previous: ForecastResult | null }) {
  if (!previous || previous.turbine_id !== current.turbine_id || previous.fingerprint === current.fingerprint) return null
  const prior = new Map(previous.hours.map(row => [row.valid_at, row]))
  const overlap = current.hours.filter(row => prior.has(row.valid_at))
  if (!overlap.length) return null
  const mean = overlap.reduce((sum, row) => sum + Math.abs(row.power_norm - prior.get(row.valid_at)!.power_norm), 0) / overlap.length
  const changed = overlap.filter(row => Math.abs(row.power_norm - prior.get(row.valid_at)!.power_norm) > 1e-12).length
  return <section className="panel comparison"><div className="section-title"><span className="eyebrow">{ru.comparison}</span><h3>{ru.whatChanged}</h3></div>
    <p>{changed} из {overlap.length} {ru.overlapping} <strong>{percent(mean)}</strong> {ru.units}.</p>
    <details><summary>{ru.inspectOverlap}</summary><div className="table-scroll"><table><thead><tr><th>{ru.localHour}</th><th>{ru.previous}</th><th>{ru.current}</th><th>{ru.change}</th></tr></thead><tbody>{overlap.map(row => <tr key={row.valid_at}><td>{localTime(row.valid_at, current.timezone)}</td><td>{percent(prior.get(row.valid_at)!.power_norm)}</td><td>{percent(row.power_norm)}</td><td>{signedPoints(row.power_norm - prior.get(row.valid_at)!.power_norm)}</td></tr>)}</tbody></table></div></details>
  </section>
}

export default function App() {
  const [mode, setMode] = useState<WeatherMode>('fixture')
  const [sites, setSites] = useState<Site[]>([])
  const [siteId, setSiteId] = useState('')
  const [date, setDate] = useState(FIRST_DATE)
  const [horizon, setHorizon] = useState<24 | 48>(48)
  const [siteError, setSiteError] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<ForecastResult | null>(null)
  const [previous, setPrevious] = useState<ForecastResult | null>(null)
  const [explanation, setExplanation] = useState<Explanation | null>(null)
  const [explanationError, setExplanationError] = useState('')
  const [loading, setLoading] = useState(false)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Explanation | null>(null)
  const [questionError, setQuestionError] = useState('')
  const [downloadError, setDownloadError] = useState('')
  const [asking, setAsking] = useState(false)
  const requestEpoch = useRef(0)
  const forecastController = useRef<AbortController | null>(null)
  const answerController = useRef<AbortController | null>(null)
  const lastSuccess = useRef<ForecastResult | null>(null)

  function invalidate() {
    requestEpoch.current += 1
    forecastController.current?.abort()
    answerController.current?.abort()
    setResult(null); setPrevious(null); setExplanation(null); setAnswer(null)
    setError(''); setExplanationError(''); setQuestionError(''); setDownloadError(''); setLoading(false); setAsking(false)
  }

  useEffect(() => {
    const controller = new AbortController()
    setSites([]); setSiteId(''); setSiteError('')
    getSites(mode, controller.signal).then(loaded => {
      setSites(loaded)
      if (loaded.length) setSiteId(loaded[0].turbine_id)
      else setSiteError(mode === 'archive' ? ru.noArchiveSites : ru.noSites)
    }).catch(err => { if (!controller.signal.aborted) setSiteError(errorMessage(err)) })
    return () => controller.abort()
  }, [mode])

  async function runForecast(next: { siteId: string, date: string, horizon: 24 | 48, mode: WeatherMode }) {
    invalidate()
    const epoch = requestEpoch.current
    const controller = new AbortController()
    forecastController.current = controller
    setLoading(true)
    const input: ForecastRequest = { turbine_id: next.siteId, origin: originForDate(next.date), horizon_hours: next.horizon, mode: next.mode }
    try {
      const forecast = await createForecast(input, controller.signal)
      if (epoch !== requestEpoch.current) return
      if (forecast.status !== 'ok' || !forecast.forecast_id || !forecast.model_input || !forecast.hours?.length) throw new Error(ru.incompleteForecast)
      setPrevious(lastSuccess.current?.turbine_id === forecast.turbine_id ? lastSuccess.current : null)
      lastSuccess.current = forecast
      setResult(forecast)
      setLoading(false)
      try {
        const prose = await explainForecast(forecast.forecast_id, controller.signal)
        if (epoch === requestEpoch.current) {
          if (prose.forecast_fingerprint !== forecast.fingerprint) throw new Error(ru.staleExplanation)
          setExplanation(prose)
        }
      } catch (err) {
        if (epoch === requestEpoch.current && !controller.signal.aborted) setExplanationError(errorMessage(err))
      }
    } catch (err) {
      if (epoch === requestEpoch.current && !controller.signal.aborted) { setError(errorMessage(err)); setLoading(false) }
    }
  }

  async function submitQuestion(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!result || !question.trim()) return
    answerController.current?.abort()
    const controller = new AbortController()
    answerController.current = controller
    const epoch = requestEpoch.current
    setAnswer(null); setQuestionError(''); setAsking(true)
    try {
      const response = await askQuestion(result.forecast_id, question.trim(), controller.signal)
      if (epoch === requestEpoch.current && !controller.signal.aborted) {
        if (response.forecast_fingerprint !== result.fingerprint) throw new Error(ru.staleAnswer)
        setAnswer(response)
      }
    } catch (err) {
      if (epoch === requestEpoch.current && !controller.signal.aborted) setQuestionError(errorMessage(err))
    } finally { if (epoch === requestEpoch.current && !controller.signal.aborted) setAsking(false) }
  }

  async function saveCsv(kind: 'forecast' | 'model-input') {
    if (!result) return
    const active = result
    const epoch = requestEpoch.current
    setDownloadError('')
    try {
      const blob = await downloadCsv(active.forecast_id, kind)
      if (epoch !== requestEpoch.current) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = kind === 'model-input' ? active.model_input.filename : `forecast-${active.turbine_id}-${active.origin.slice(0, 10)}.csv`
      link.click()
      setTimeout(() => URL.revokeObjectURL(url), 0)
    } catch (err) {
      if (epoch === requestEpoch.current) setDownloadError(errorMessage(err))
    }
  }

  const selectedSite = sites.find(s => s.turbine_id === siteId)
  const origin = originForDate(date)
  const mean = result ? result.hours.reduce((sum, row) => sum + row.power_norm, 0) / result.hours.length : 0

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">◒</span><span>{ru.brand} <small>{ru.brandLab}</small></span></div><div className="topbar-right"><span className="topbar-line" /><span>{ru.replay}</span><span className="topbar-dot" /> {ru.demo}</div></header>
    <main>
      <div className="hero"><div><span className="eyebrow hero-kicker">{ru.kicker}</span><h1>{ru.heroStart} <em>{ru.heroEnd}</em></h1><p>{ru.heroText}</p></div><div className="hero-side"><span className="hero-orbit">✳</span><span>{ru.heroSide}</span></div></div>
      <div className="notice"><span className="notice-icon">i</span><span>{ru.notice}</span></div>
      <div className="workspace"><section className="panel setup-panel"><div className="section-title"><span className="eyebrow">{ru.configure}</span><h2>{ru.selectForecast}</h2><p>{ru.selectHint}</p></div>
        <div className="field-label">{ru.registeredTurbine}</div>
        <SiteMap sites={sites} selected={siteId} onSelect={id => { if (id !== siteId) { invalidate(); setSiteId(id) } }} />
        <div className="field-note">{ru.mapHint}</div>
        <label className="field"><span>{ru.turbine}</span><select aria-label={ru.turbine} value={siteId} onChange={e => { invalidate(); setSiteId(e.target.value) }} disabled={!sites.length}><option value="">{ru.chooseTurbine}</option>{sites.map(site => <option key={site.turbine_id} value={site.turbine_id}>{site.turbine_id} · {coordinateLabel(site.coordinate_status)}</option>)}</select></label>
        {siteError && <div className="error-banner">{siteError}</div>}
        <div className="field-grid"><label className="field"><span>{ru.originDate}</span><input aria-label={ru.originDate} type="date" min={FIRST_DATE} value={date} onChange={e => { invalidate(); setDate(e.target.value) }} /></label><label className="field"><span>{ru.horizon}</span><select aria-label={ru.horizon} value={horizon} onChange={e => { invalidate(); setHorizon(Number(e.target.value) as 24 | 48) }}><option value={24}>{ru.hours24}</option><option value={48}>{ru.hours48}</option></select></label></div>
        <label className="field"><span>{ru.weatherSource}</span><select aria-label={ru.weatherSource} value={mode} onChange={e => { invalidate(); setMode(e.target.value as WeatherMode) }}><option value="fixture">{ru.fixture}</option><option value="archive">{ru.archive}</option></select></label>
        <div className="origin-note">{ru.originAt}: {localTime(origin, selectedSite?.timezone || LOCAL_ZONE)} · {localTime(origin, 'UTC')}</div>
        <button className="primary-button" disabled={!siteId || !date || loading} onClick={() => runForecast({ siteId, date, horizon, mode })}>{loading ? ru.calculating : ru.predict} <span>↗</span></button>
        {error && <div className="error-banner" role="alert">{error}</div>}
      </section>
      <section className="results-column"><div className="pipeline"><span>{ru.pipelineWeather}</span><b>→</b><span>{ru.pipelineCsv}</span><b>→</b><span>{ru.pipelineModel}</span><b>→</b><span>{ru.pipelineExplanation}</span></div>
        {!result && <div className="panel empty-state"><div className="empty-glyph">∿</div><span className="eyebrow">{ru.awaiting}</span><h2>{ru.emptyTitle}</h2><p>{ru.emptyText}</p></div>}
        {result && <><section className="panel result-panel"><div className="result-heading"><div><span className="eyebrow">{ru.result}</span><h2>{ru.forecast}: {result.turbine_id}</h2><p>{localTime(result.origin, result.timezone)} · {result.horizon_hours} ч · {provenanceLabel(result.weather_provenance.provenance_status)}</p></div><span className="status-pill">{ru.ready}</span></div>
          <div className="metrics"><div><span>{ru.meanPower}</span><strong>{percent(mean)}</strong><small>{ru.normalized}</small></div><div><span>{ru.peakPower}</span><strong>{percent(result.analysis.peak_power_norm)}</strong><small>{localTime(result.analysis.peak_at, result.timezone)}</small></div><div><span>{ru.lowestPower}</span><strong>{percent(result.analysis.min_power_norm)}</strong><small>{localTime(result.analysis.min_at, result.timezone)}</small></div></div>
          <div className="chart-header"><h3>{ru.chart}</h3><div className="legend"><span><i className="legend-forecast" /> {ru.forecast}</span><span><i className="legend-baseline" /> {ru.baseline}</span></div></div><PowerChart hours={result.hours} zone={result.timezone} />
          <div className="actions"><button type="button" onClick={() => saveCsv('forecast')}>{ru.downloadForecast}</button><button type="button" onClick={() => saveCsv('model-input')}>{ru.downloadInput}</button></div>{downloadError && <div className="error-banner" role="alert">{downloadError}</div>}
          <div className="model-input"><span className="eyebrow">{ru.modelInput} / {result.model_input.schema_version}</span><div><strong>{result.model_input.filename}</strong><span>{result.model_input.row_count} {ru.rows} · {result.model_input.columns.join(', ')}</span></div><code>{result.model_input.sha256}</code></div>
        </section>
        <section className="panel analysis-panel"><div className="section-title"><span className="eyebrow">{ru.analysis}</span><h3>{ru.analysisTitle}</h3></div>{explanation ? <><p className="prose">{explanation.text}</p><div className="explanation-meta">{explanation.backend === 'llm' ? `${ru.aiExplanation}${explanation.model ? ` · ${explanation.model}` : ''}` : ru.computedExplanation}</div>{explanation.warning && <div className="warning-banner">{explanation.warning}</div>}</> : explanationError ? <div className="warning-banner">{ru.explanationUnavailable}: {explanationError}</div> : <p className="muted">{ru.explanationLoading}</p>}
          {result.analysis.warnings.length > 0 && <div className="analysis-warnings">{result.analysis.warnings.map(warning => <span key={warning}>• {warningLabel(warning)}</span>)}</div>}
          <form className="question-form" onSubmit={submitQuestion}><label htmlFor="forecast-question">{ru.askLabel}</label><div><input id="forecast-question" value={question} onChange={e => { answerController.current?.abort(); setAsking(false); setAnswer(null); setQuestionError(''); setQuestion(e.target.value) }} placeholder={ru.askPlaceholder} maxLength={500} /><button disabled={asking || !question.trim()}>{asking ? ru.asking : ru.ask}</button></div></form>
          {answer && <div className="answer"><span className="eyebrow">{ru.answer} · {answer.backend === 'llm' ? ru.ai : ru.computed}</span><p>{answer.text}</p>{answer.warning && <div className="warning-banner">{answer.warning}</div>}</div>}{questionError && <div className="error-banner">{questionError}</div>}
        </section>
        <Comparison current={result} previous={previous} />
        <section className="panel detail-panel"><details><summary>{ru.hourlyData} <span>{result.hours.length} {ru.rows}</span></summary><div className="table-scroll"><table><thead><tr><th>{ru.localHour}</th><th>{ru.lead}</th><th>{ru.wind}</th><th>{ru.temperature}</th><th>{ru.power}</th><th>{ru.baseline}</th></tr></thead><tbody>{result.hours.map(hour => <tr key={hour.valid_at}><td>{localTime(hour.valid_at, result.timezone)}</td><td>{hour.lead_hour}</td><td>{decimal(hour.wind_speed_ms)}</td><td>{decimal(hour.temperature_c)}</td><td>{percent(hour.power_norm)}</td><td>{percent(hour.baseline_norm)}</td></tr>)}</tbody></table></div></details><details><summary>{ru.provenance} <span>{result.trace.length} {ru.steps}</span></summary><div className="provenance"><div><strong>{ru.weatherRun}</strong><span>{result.run_id}</span></div><div><strong>{ru.model}</strong><span>{result.model_id}</span></div><div><strong>{ru.trainingCutoff}</strong><span>{localTime(result.train_last_interval_start, result.timezone)}</span></div><div><strong>{ru.cached}</strong><span>{result.cache_hit ? ru.yes : ru.no}</span></div>{Object.entries(result.weather_provenance).map(([key, value]) => <div key={key}><strong>{fieldLabel(key)}</strong><span>{provenanceValue(key, String(value), result.timezone)}</span></div>)}</div><ol className="trace">{result.trace.map((step, i) => <li key={`${step.step}-${i}`}><span className={step.status === 'ok' || step.status === 'cached' ? 'trace-ok' : ''}>{statusLabel(step.status)}</span><strong>{stepLabel(step.step)}</strong><small>{traceDetail(step.step, step.detail)}</small></li>)}</ol></details></section>
        <button className="advance-button" onClick={() => { const advanced = nextDate(date); setDate(advanced); runForecast({ siteId, date: advanced, horizon, mode }) }}>{ru.advance} <span>→</span></button>
        </>}
      </section></div>
    </main><footer><span>{ru.brand} {ru.brandLab} / {ru.replay}</span><span>{ru.footer}</span></footer>
  </div>
}
