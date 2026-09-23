import { useEffect, useRef, useState } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip } from 'react-leaflet'
import { askQuestion, createForecast, downloadUrl, explainForecast, getSites } from './api'
import type { Explanation, ForecastHour, ForecastRequest, ForecastResult, Site, WeatherMode } from './types'

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

function localTime(stamp: string): string {
  return new Intl.DateTimeFormat('en-GB', { timeZone: LOCAL_ZONE, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(stamp))
}

function pct(value: number): string { return `${(value * 100).toFixed(1)}%` }

function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return 'The request did not complete.'
}

function PowerChart({ hours }: { hours: ForecastHour[] }) {
  const width = 940, height = 265, left = 42, right = 12, top = 12, bottom = 31
  const x = (i: number) => left + i * (width - left - right) / Math.max(1, hours.length - 1)
  const y = (v: number) => top + (1 - v) * (height - top - bottom)
  const line = (key: 'power_norm' | 'baseline_norm') => hours.map((h, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(h[key]).toFixed(1)}`).join(' ')
  return <div className="chart-wrap" role="img" aria-label="Hourly normalized power forecast and persistence baseline">
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {[0, .25, .5, .75, 1].map(v => <g key={v}><line className="grid-line" x1={left} x2={width - right} y1={y(v)} y2={y(v)} /><text className="axis-label" x={left - 9} y={y(v) + 4} textAnchor="end">{Math.round(v * 100)}</text></g>)}
      <path className="baseline-line" d={line('baseline_norm')} />
      <path className="power-line" d={line('power_norm')} />
      {[0, Math.floor((hours.length - 1) / 2), hours.length - 1].map(i => <text key={i} className="axis-label" x={x(i)} y={height - 5} textAnchor={i === 0 ? 'start' : i === hours.length - 1 ? 'end' : 'middle'}>{localTime(hours[i].valid_at)}</text>)}
    </svg>
  </div>
}

function SiteMap({ sites, selected, onSelect }: { sites: Site[], selected: string, onSelect: (id: string) => void }) {
  const center: [number, number] = sites.length ? [sites.reduce((sum, s) => sum + s.latitude, 0) / sites.length, sites.reduce((sum, s) => sum + s.longitude, 0) / sites.length] : [0, 0]
  return <div className="map-frame">
    <MapContainer center={center} zoom={12} scrollWheelZoom={false} className="site-map" key={sites.map(s => s.turbine_id).join('-')}>
      <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {sites.map(site => <CircleMarker key={site.turbine_id} center={[site.latitude, site.longitude]} radius={selected === site.turbine_id ? 13 : 11} pathOptions={{ color: selected === site.turbine_id ? '#184f45' : '#fff', fillColor: selected === site.turbine_id ? '#b4e86a' : '#266f62', fillOpacity: 1, weight: 3 }} eventHandlers={{ click: () => onSelect(site.turbine_id) }}>
        <Tooltip direction="top" offset={[0, -14]}>{site.turbine_id} · {site.coordinate_status} coordinates</Tooltip>
        <Popup>{site.turbine_id} · {site.coordinate_status} coordinates</Popup>
      </CircleMarker>)}
    </MapContainer>
    <span className="map-badge">FICTIONAL COORDINATES</span>
  </div>
}

function Comparison({ current, previous }: { current: ForecastResult, previous: ForecastResult | null }) {
  if (!previous || previous.turbine_id !== current.turbine_id || previous.fingerprint === current.fingerprint) return null
  const prior = new Map(previous.hours.map(row => [row.valid_at, row]))
  const overlap = current.hours.filter(row => prior.has(row.valid_at))
  if (!overlap.length) return null
  const mean = overlap.reduce((sum, row) => sum + Math.abs(row.power_norm - prior.get(row.valid_at)!.power_norm), 0) / overlap.length
  const changed = overlap.filter(row => Math.abs(row.power_norm - prior.get(row.valid_at)!.power_norm) > 1e-12).length
  return <section className="panel comparison"><div className="section-title"><span className="eyebrow">RUN COMPARISON</span><h3>What changed?</h3></div>
    <p>{changed} of {overlap.length} overlapping hours changed. Mean absolute change: <strong>{pct(mean)}</strong> normalized power.</p>
    <details><summary>Inspect overlapping hours</summary><div className="table-scroll"><table><thead><tr><th>Local hour</th><th>Previous</th><th>Current</th><th>Change</th></tr></thead><tbody>{overlap.map(row => <tr key={row.valid_at}><td>{localTime(row.valid_at)}</td><td>{pct(prior.get(row.valid_at)!.power_norm)}</td><td>{pct(row.power_norm)}</td><td>{((row.power_norm - prior.get(row.valid_at)!.power_norm) * 100).toFixed(1)} pp</td></tr>)}</tbody></table></div></details>
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
    setError(''); setExplanationError(''); setQuestionError(''); setLoading(false); setAsking(false)
  }

  useEffect(() => {
    const controller = new AbortController()
    setSites([]); setSiteId(''); setSiteError('')
    getSites(mode, controller.signal).then(loaded => {
      setSites(loaded)
      if (loaded.length) setSiteId(loaded[0].turbine_id)
      else setSiteError(mode === 'archive' ? 'Verified turbine coordinates are not configured for archive mode.' : 'No registered turbines are available.')
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
      if (forecast.status !== 'ok' || !forecast.forecast_id || !forecast.model_input || !forecast.hours?.length) throw new Error('Forecast response is incomplete.')
      setPrevious(lastSuccess.current?.turbine_id === forecast.turbine_id ? lastSuccess.current : null)
      lastSuccess.current = forecast
      setResult(forecast)
      setLoading(false)
      try {
        const prose = await explainForecast(forecast.forecast_id, controller.signal)
        if (epoch === requestEpoch.current) {
          if (prose.forecast_fingerprint !== forecast.fingerprint) throw new Error('Explanation does not match this forecast.')
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
        if (response.forecast_fingerprint !== result.fingerprint) throw new Error('Answer does not match this forecast.')
        setAnswer(response)
      }
    } catch (err) {
      if (epoch === requestEpoch.current && !controller.signal.aborted) setQuestionError(errorMessage(err))
    } finally { if (epoch === requestEpoch.current && !controller.signal.aborted) setAsking(false) }
  }

  const selectedSite = sites.find(s => s.turbine_id === siteId)
  const origin = originForDate(date)
  const mean = result ? result.hours.reduce((sum, row) => sum + row.power_norm, 0) / result.hours.length : 0

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">◒</span><span>AEOLUS <small>LAB</small></span></div><div className="topbar-right"><span className="topbar-line" /><span>HISTORICAL REPLAY</span><span className="topbar-dot" /> LOCAL DEMO</div></header>
    <main>
      <div className="hero"><div><span className="eyebrow hero-kicker">WIND INTELLIGENCE / 01</span><h1>Power, <em>predicted.</em></h1><p>Explore hourly generation forecasts from measured turbine history and weather features. Advance the origin to see how the outlook shifts.</p></div><div className="hero-side"><span className="hero-orbit">✳</span><span>HOURLY<br />FORECAST<br />ENGINE</span></div></div>
      <div className="notice"><span className="notice-icon">i</span><span>Demo weather and map coordinates are fictional. Turbine measurements and fitted regressors are real. All power values are normalized to [0, 1], not MW or MWh.</span></div>
      <div className="workspace"><section className="panel setup-panel"><div className="section-title"><span className="eyebrow">01 / CONFIGURE</span><h2>Select your forecast</h2><p>Choose a registered turbine and a replay origin.</p></div>
        <div className="field-label">REGISTERED TURBINE</div>
        <SiteMap sites={sites} selected={siteId} onSelect={id => { if (id !== siteId) { invalidate(); setSiteId(id) } }} />
        <div className="field-note">Marker locations are fictional fixtures. Map clicks only select registered turbines.</div>
        <label className="field"><span>Turbine</span><select aria-label="Turbine" value={siteId} onChange={e => { invalidate(); setSiteId(e.target.value) }} disabled={!sites.length}><option value="">Select turbine</option>{sites.map(site => <option key={site.turbine_id} value={site.turbine_id}>{site.turbine_id} · {site.coordinate_status} location</option>)}</select></label>
        {siteError && <div className="error-banner">{siteError}</div>}
        <div className="field-grid"><label className="field"><span>Origin date</span><input aria-label="Origin date" type="date" min={FIRST_DATE} value={date} onChange={e => { invalidate(); setDate(e.target.value) }} /></label><label className="field"><span>Horizon</span><select aria-label="Horizon" value={horizon} onChange={e => { invalidate(); setHorizon(Number(e.target.value) as 24 | 48) }}><option value={24}>24 hours</option><option value={48}>48 hours</option></select></label></div>
        <label className="field"><span>Weather source</span><select aria-label="Weather source" value={mode} onChange={e => { invalidate(); setMode(e.target.value as WeatherMode) }}><option value="fixture">Synthetic fixture</option><option value="archive">Verified archive</option></select></label>
        <div className="origin-note">Forecast issued at 23:00 in {selectedSite?.timezone || LOCAL_ZONE} · {origin} UTC</div>
        <button className="primary-button" disabled={!siteId || !date || loading} onClick={() => runForecast({ siteId, date, horizon, mode })}>{loading ? 'Calculating forecast…' : 'Predict generation'} <span>↗</span></button>
        {error && <div className="error-banner" role="alert">{error}</div>}
      </section>
      <section className="results-column"><div className="pipeline"><span>WEATHER</span><b>→</b><span>CSV FEATURES</span><b>→</b><span>POWER MODEL</span><b>→</b><span>EXPLANATION</span></div>
        {!result && <div className="panel empty-state"><div className="empty-glyph">∿</div><span className="eyebrow">AWAITING FORECAST</span><h2>The next 48 hours, in view.</h2><p>Select a turbine and predict generation to inspect the hourly power curve, the exact model input CSV, and the analysis.</p></div>}
        {result && <><section className="panel result-panel"><div className="result-heading"><div><span className="eyebrow">02 / FORECAST RESULT</span><h2>{result.turbine_id} generation outlook</h2><p>{localTime(result.origin)} local origin · {result.horizon_hours} hourly predictions · {result.weather_provenance.provenance_status} weather</p></div><span className="status-pill">● READY</span></div>
          <div className="metrics"><div><span>MEAN POWER</span><strong>{pct(mean)}</strong><small>normalized output</small></div><div><span>PEAK POWER</span><strong>{pct(result.analysis.peak_power_norm)}</strong><small>{localTime(result.analysis.peak_at)} local</small></div><div><span>LOWEST POWER</span><strong>{pct(result.analysis.min_power_norm)}</strong><small>{localTime(result.analysis.min_at)} local</small></div></div>
          <div className="chart-header"><h3>Hourly power curve</h3><div className="legend"><span><i className="legend-forecast" /> Forecast</span><span><i className="legend-baseline" /> Persistence baseline</span></div></div><PowerChart hours={result.hours} />
          <div className="actions"><a href={downloadUrl(result.forecast_id, 'forecast')} download>↓ Download forecast CSV</a><a href={downloadUrl(result.forecast_id, 'model-input')} download>↓ Inspect model input CSV</a></div>
          <div className="model-input"><span className="eyebrow">MODEL INPUT / {result.model_input.schema_version}</span><div><strong>{result.model_input.filename}</strong><span>{result.model_input.row_count} rows · {result.model_input.columns.join(', ')}</span></div><code>{result.model_input.sha256}</code></div>
        </section>
        <section className="panel analysis-panel"><div className="section-title"><span className="eyebrow">03 / ANALYSIS</span><h3>What the forecast says</h3></div>{explanation ? <><p className="prose">{explanation.text}</p><div className="explanation-meta">{explanation.backend === 'llm' ? `AI explanation${explanation.model ? ` · ${explanation.model}` : ''}` : 'Computed template explanation'}</div>{explanation.warning && <div className="warning-banner">{explanation.warning}</div>}</> : explanationError ? <div className="warning-banner">Explanation unavailable: {explanationError}</div> : <p className="muted">Preparing explanation…</p>}
          {result.analysis.warnings.length > 0 && <div className="analysis-warnings">{result.analysis.warnings.map(warning => <span key={warning}>• {warning}</span>)}</div>}
          <form className="question-form" onSubmit={submitQuestion}><label htmlFor="forecast-question">Ask about this forecast</label><div><input id="forecast-question" value={question} onChange={e => setQuestion(e.target.value)} placeholder="What explains the peak hour?" maxLength={500} /><button disabled={asking || !question.trim()}>{asking ? 'Asking…' : 'Ask ↗'}</button></div></form>
          {answer && <div className="answer"><span className="eyebrow">ANSWER · {answer.backend === 'llm' ? 'AI' : 'COMPUTED TEMPLATE'}</span><p>{answer.text}</p>{answer.warning && <div className="warning-banner">{answer.warning}</div>}</div>}{questionError && <div className="error-banner">{questionError}</div>}
        </section>
        <Comparison current={result} previous={previous} />
        <section className="panel detail-panel"><details><summary>Hourly data <span>{result.hours.length} rows</span></summary><div className="table-scroll"><table><thead><tr><th>Local hour</th><th>Lead</th><th>Wind m/s</th><th>Temp °C</th><th>Power</th><th>Baseline</th></tr></thead><tbody>{result.hours.map(hour => <tr key={hour.valid_at}><td>{localTime(hour.valid_at)}</td><td>{hour.lead_hour}</td><td>{hour.wind_speed_ms.toFixed(1)}</td><td>{hour.temperature_c.toFixed(1)}</td><td>{pct(hour.power_norm)}</td><td>{pct(hour.baseline_norm)}</td></tr>)}</tbody></table></div></details><details><summary>Provenance &amp; executed steps <span>{result.trace.length} steps</span></summary><div className="provenance"><div><strong>Weather run</strong><span>{result.run_id}</span></div><div><strong>Model</strong><span>{result.model_id}</span></div><div><strong>Training cutoff</strong><span>{result.train_last_interval_start}</span></div><div><strong>Cached result</strong><span>{result.cache_hit ? 'Yes' : 'No'}</span></div>{Object.entries(result.weather_provenance).map(([key, value]) => <div key={key}><strong>{key.replaceAll('_', ' ')}</strong><span>{String(value)}</span></div>)}</div><ol className="trace">{result.trace.map((step, i) => <li key={`${step.step}-${i}`}><span className={step.status === 'ok' || step.status === 'cached' ? 'trace-ok' : ''}>{step.status}</span><strong>{step.step.replaceAll('_', ' ')}</strong><small>{step.detail}</small></li>)}</ol></details></section>
        <button className="advance-button" onClick={() => { const advanced = nextDate(date); setDate(advanced); runForecast({ siteId, date: advanced, horizon, mode }) }}>Advance one day &amp; recalculate <span>→</span></button>
        </>}
      </section></div>
    </main><footer><span>AEOLUS LAB / HISTORICAL REPLAY</span><span>MEASURED TURBINES · SYNTHETIC WEATHER · NORMALIZED POWER</span></footer>
  </div>
}
