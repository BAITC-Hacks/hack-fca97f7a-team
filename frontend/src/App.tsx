import { useEffect, useRef, useState } from 'react'
import { ApiFailure, askQuestion, createForecast, downloadCsv, explainForecast, getSites, refreshWeather } from './api'
import type { Explanation, ForecastRequest, ForecastResult, QuestionAnswer, Site, WeatherMode } from './types'
import { ru, percent, decimal, signedPoints, localTime, fieldLabel, statusLabel, stepLabel, provenanceLabel, coordinateLabel, provenanceValue, warningLabel, traceDetail, weatherProviderLabel } from './ru'
import PowerChart from './PowerChart'
import SiteMap from './SiteMap'
import { saveBlob } from './chartExport'

const FIRST_DATE = '2026-01-31'
const LOCAL_ZONE = 'Asia/Almaty'

function originForDate(date: string): string {
  // Поддерживаемые даты 2026 года: UTC+05:00 в Asia/Almaty.
  return `${date}T18:00:00Z`
}

function nextDate(date: string): string {
  const day = new Date(`${date}T12:00:00Z`)
  day.setUTCDate(day.getUTCDate() + 1)
  return day.toISOString().slice(0, 10)
}

function errorMessage(error: unknown): string {
  if (error instanceof TypeError) return 'Не удалось связаться с сервером. Проверьте подключение и повторите попытку.'
  if (error instanceof Error) return error.message
  return ru.requestFailed
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

function AnswerContent({ answer }: { answer: QuestionAnswer }) {
  return <>
    <p className="prose">{answer.text}</p>
    {answer.tool_results?.filter(result => result.table && result.table.columns.length > 0).map((result, index) => <div className="table-scroll chat-table" key={`${result.tool}-${index}`}>
      <table><caption>{ru.calculationTable}</caption><thead><tr>{result.table!.columns.map((column, i) => <th scope="col" key={i}>{column}</th>)}</tr></thead>
        <tbody>{result.table!.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>)}
    {answer.warning && <p className="message-warning">{answer.warning}</p>}
  </>
}

export default function App() {
  const [mode, setMode] = useState<WeatherMode>('live')
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
  const [refreshing, setRefreshing] = useState(false)
  const [question, setQuestion] = useState('')
  const [conversation, setConversation] = useState<{ question: string, answer: QuestionAnswer }[]>([])
  const [pendingQuestion, setPendingQuestion] = useState('')
  const [questionError, setQuestionError] = useState('')
  const [downloadError, setDownloadError] = useState('')
  const [asking, setAsking] = useState(false)
  const requestEpoch = useRef(0)
  const questionEpoch = useRef(0)
  const forecastController = useRef<AbortController | null>(null)
  const answerController = useRef<AbortController | null>(null)
  const conversationId = useRef<string | null>(null)
  const askingNow = useRef(false)
  const lastSuccess = useRef<ForecastResult | null>(null)

  function invalidate() {
    requestEpoch.current += 1
    questionEpoch.current += 1
    forecastController.current?.abort()
    answerController.current?.abort()
    conversationId.current = null
    askingNow.current = false
    setResult(null); setPrevious(null); setExplanation(null); setConversation([]); setQuestion(''); setPendingQuestion('')
    setError(''); setExplanationError(''); setQuestionError(''); setDownloadError(''); setLoading(false); setRefreshing(false); setAsking(false)
  }

  useEffect(() => {
    const controller = new AbortController()
    setSites([]); setSiteId(''); setSiteError('')
    getSites(mode, controller.signal).then(loaded => {
      if (controller.signal.aborted) return
      setSites(loaded)
      if (loaded.length) setSiteId(loaded[0].turbine_id)
      else setSiteError(mode === 'archive' ? ru.noArchiveSites : ru.noSites)
    }).catch(err => { if (!controller.signal.aborted) setSiteError(errorMessage(err)) })
    return () => controller.abort()
  }, [mode])

  async function runForecast(next: { siteId: string, date: string, horizon: 24 | 48, mode: WeatherMode }, refresh = false) {
    invalidate()
    const epoch = requestEpoch.current
    const controller = new AbortController()
    forecastController.current = controller
    setLoading(true)
    setRefreshing(refresh)
    const input: ForecastRequest = { turbine_id: next.siteId, horizon_hours: next.horizon, mode: next.mode }
    if (next.mode !== 'live') input.origin = originForDate(next.date)
    try {
      if (refresh) {
        await refreshWeather(next.siteId, controller.signal)
        if (epoch !== requestEpoch.current) return
        setRefreshing(false)
      }
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
      if (epoch === requestEpoch.current && !controller.signal.aborted) { lastSuccess.current = null; setError(errorMessage(err)); setLoading(false); setRefreshing(false) }
    }
  }

  async function submitQuestion(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!result || !question.trim() || askingNow.current) return
    askingNow.current = true
    const controller = new AbortController()
    answerController.current = controller
    const epoch = requestEpoch.current
    const submitted = question.trim()
    setPendingQuestion(submitted); setQuestion(''); setQuestionError(''); setAsking(true)
    try {
      const response = await askQuestion(result.forecast_id, submitted, conversationId.current ?? undefined, controller.signal)
      if (epoch === requestEpoch.current && !controller.signal.aborted) {
        if (response.forecast_fingerprint !== result.fingerprint) throw new Error(ru.staleAnswer)
        if (!response.conversation_id || (conversationId.current && response.conversation_id !== conversationId.current)) throw new Error(ru.invalidServerResponse)
        conversationId.current = response.conversation_id
        setConversation(current => [...current, { question: submitted, answer: response }])
        setPendingQuestion('')
      }
    } catch (err) {
      if (epoch === requestEpoch.current && !controller.signal.aborted) {
        if (err instanceof ApiFailure && err.code === 'CONVERSATION_NOT_FOUND') {
          conversationId.current = null
          setConversation([])
          setQuestionError(ru.newConversation)
        } else setQuestionError(errorMessage(err))
        setPendingQuestion(''); setQuestion(submitted)
      }
    } finally {
      if (epoch === requestEpoch.current && !controller.signal.aborted) { askingNow.current = false; setAsking(false) }
    }
  }

  async function saveCsv(kind: 'forecast' | 'model-input') {
    if (!result) return
    const active = result
    const epoch = requestEpoch.current
    setDownloadError('')
    try {
      const blob = await downloadCsv(active.forecast_id, kind)
      if (epoch !== requestEpoch.current) return
      saveBlob(blob, kind === 'model-input' ? active.model_input.filename : `forecast-${active.turbine_id}-${active.origin.slice(0, 10)}-${active.horizon_hours}h.csv`)
    } catch (err) {
      if (epoch === requestEpoch.current) setDownloadError(errorMessage(err))
    }
  }

  const selectedSite = sites.find(s => s.turbine_id === siteId)
  const origin = originForDate(date)
  const mean = result ? result.hours.reduce((sum, row) => sum + row.power_norm, 0) / result.hours.length : 0

  return <div className="app-shell">
    <header className="page-header">
      <div><h1>{ru.pageTitle}</h1><p>{ru.pageSubtitle}</p></div>
      <span className="mode-badge"><i />{mode === 'live' ? ru.live : mode === 'fixture' ? ru.fixture : ru.archive}</span>
    </header>
    <main className="workspace">
      <aside className="setup-column" aria-label={ru.selectForecast}>
        <section className="panel setup-panel">
          <div className="section-title"><h2>{ru.selectForecast}</h2></div>
          <SiteMap sites={sites} selected={siteId} onSelect={id => { if (id !== siteId) { invalidate(); setSiteId(id) } }} />
          <label className="field"><span>{ru.turbine}</span><select aria-label={ru.turbine} value={siteId} onChange={e => { invalidate(); setSiteId(e.target.value) }} disabled={!sites.length}><option value="">{ru.chooseTurbine}</option>{sites.map(site => <option key={site.turbine_id} value={site.turbine_id}>{site.turbine_id}</option>)}</select></label>
          {selectedSite && <div className="site-meta"><span>{new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 6 }).format(selectedSite.latitude)} · {new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 6 }).format(selectedSite.longitude)}</span><small>{coordinateLabel(selectedSite.coordinate_status)}</small>{selectedSite.coordinate_source && <a href={selectedSite.coordinate_source} target="_blank" rel="noreferrer">{ru.openMap} ↗</a>}</div>}
          {siteError && <div className="error-banner" role="alert">{siteError}</div>}
          <div className="field-grid">
            {mode !== 'live' && <label className="field"><span>{ru.originDate}</span><input aria-label={ru.originDate} type="date" min={FIRST_DATE} value={date} onChange={e => { invalidate(); setDate(e.target.value) }} /></label>}
            <label className="field"><span>{ru.horizon}</span><select aria-label={ru.horizon} value={horizon} onChange={e => { invalidate(); setHorizon(Number(e.target.value) as 24 | 48) }}><option value={24}>{ru.hours24}</option><option value={48}>{ru.hours48}</option></select></label>
          </div>
          <label className="field"><span>{ru.weatherSource}</span><select aria-label={ru.weatherSource} value={mode} onChange={e => { invalidate(); setMode(e.target.value as WeatherMode) }}><option value="live">{ru.live}</option><option value="fixture">{ru.fixture}</option></select></label>
          <p className="origin-note">{mode === 'live' ? ru.liveTime : date ? localTime(origin, selectedSite?.timezone || LOCAL_ZONE) : ru.chooseDate}</p>
          <button className="primary-button" disabled={!siteId || !date || loading} onClick={() => runForecast({ siteId, date, horizon, mode })}>{loading ? (refreshing ? ru.refreshingWeather : ru.calculating) : ru.predict}</button>
          {error && <div className="error-banner" role="alert">{error}</div>}
        </section>
        <p className="scope-note">{mode === 'live' ? ru.liveNotice : ru.notice}</p>
      </aside>
      <div className="results-column">
        {!result && <section className="panel empty-state" aria-live="polite"><div className="empty-chart" aria-hidden="true"><svg viewBox="0 0 200 60"><path d="M0 50 L28 40 L55 47 L82 18 L108 28 L138 8 L166 22 L200 3" /></svg></div><h2>{loading ? (refreshing ? ru.refreshingWeather : ru.calculating) : ru.emptyTitle}</h2><p>{loading ? ru.loadingHint : ru.emptyText}</p></section>}
        {result && <>
          <section className="panel result-panel">
            <div className="result-heading"><div><h2>{ru.resultTitle}</h2><p>{result.turbine_id} · {result.horizon_hours} ч · {provenanceLabel(result.weather_provenance.provenance_status)}</p></div><div className="result-actions">{mode === 'live' && <button type="button" className="secondary-button" onClick={() => runForecast({ siteId, date, horizon, mode }, true)}>{ru.refreshWeather}</button>}<button type="button" className="secondary-button" onClick={() => saveCsv('forecast')}>{ru.downloadForecast}</button></div></div>
            <div className="weather-freshness" aria-label={ru.weatherRetrieved}><span><strong>{ru.weatherProvider}</strong> {weatherProviderLabel(result.weather_provenance.provider)}</span><span><strong>{ru.weatherRetrieved}</strong> {result.weather_provenance.retrieved_at ? localTime(result.weather_provenance.retrieved_at, result.timezone) : ru.weatherRetrievalUnknown}</span>{result.weather_provenance.weather_cache_hit === true && <span>{ru.cachedWeather}</span>}</div>
            <div className="metrics">
              <div><span>{ru.meanPower}</span><strong>{percent(mean)}</strong><small>{ru.normalized}</small></div>
              <div><span>{ru.peakPower}</span><strong>{percent(result.analysis.peak_power_norm)}</strong><small>{localTime(result.analysis.peak_at, result.timezone)}</small></div>
              <div><span>{ru.lowestPower}</span><strong>{percent(result.analysis.min_power_norm)}</strong><small>{localTime(result.analysis.min_at, result.timezone)}</small></div>
            </div>
            <PowerChart key={result.forecast_id} result={result} />
            {downloadError && <div className="error-banner" role="alert">{downloadError}</div>}
          </section>
          <section className="panel analysis-panel" aria-labelledby="analysis-heading">
            <div className="section-title"><h2 id="analysis-heading">{ru.analysisTitle}</h2><p>{ru.chatHint}</p></div>
            <div className="chat-messages" aria-live="polite" aria-relevant="additions text">
              <div className="chat-message assistant-message">
                <span className="message-author">{ru.analysisAuthor}</span>
                {explanation ? <><p className="prose">{explanation.text}</p><div className="explanation-meta">{explanation.backend === 'llm' ? `${ru.aiExplanation}${explanation.model ? ` · ${explanation.model}` : ''}` : ru.computedExplanation}</div>{explanation.warning && <p className="message-warning">{explanation.warning}</p>}</> : explanationError ? <div className="error-banner">{ru.explanationUnavailable}: {explanationError}</div> : <p className="muted loading-status" role="status">{ru.explanationLoading}</p>}
              </div>
              {conversation.map((exchange, index) => <div className="chat-exchange" key={index}>
                <div className="chat-message user-message"><span className="message-author">{ru.you}</span><p>{exchange.question}</p></div>
                <div className="chat-message assistant-message"><span className="message-author">{exchange.answer.backend === 'llm' ? ru.aiExplanation : ru.computed}</span><AnswerContent answer={exchange.answer} /></div>
              </div>)}
              {pendingQuestion && <><div className="chat-message user-message"><span className="message-author">{ru.you}</span><p>{pendingQuestion}</p></div><p className="muted loading-status" role="status">{ru.asking}</p></>}
            </div>
            <form className="question-form" onSubmit={submitQuestion}>
              <label htmlFor="forecast-question">{ru.askLabel}</label>
              <textarea id="forecast-question" value={question} onChange={e => { setQuestionError(''); setQuestion(e.target.value) }} placeholder={ru.askPlaceholder} maxLength={500} rows={2} />
              <div className="question-actions"><span>{ru.questionHint}</span><button className="primary-button" disabled={asking || !question.trim()}>{asking ? ru.asking : ru.ask}</button></div>
            </form>
            {questionError && <div className="error-banner" role="alert">{questionError}</div>}
          </section>
          <Comparison current={result} previous={previous} />
          <section className="panel detail-panel">
            <details><summary>{ru.hourlyData} <span>{result.hours.length} {ru.rows}</span></summary><div className="table-scroll"><table><thead><tr><th>{ru.localHour}</th><th>{ru.lead}</th><th>{ru.wind}</th><th>{ru.temperature}</th><th>{ru.power}</th></tr></thead><tbody>{result.hours.map(hour => <tr key={hour.valid_at}><td>{localTime(hour.valid_at, result.timezone)}</td><td>{hour.lead_hour}</td><td>{decimal(hour.wind_speed_ms)}</td><td>{decimal(hour.temperature_c)}</td><td>{percent(hour.power_norm)}</td></tr>)}</tbody></table></div></details>
            <details><summary>{ru.technicalDetails}</summary>
              <div className="model-input"><div><h3>{ru.modelInput}</h3><button type="button" className="secondary-button" onClick={() => saveCsv('model-input')}>{ru.downloadInput}</button></div><p>{result.model_input.row_count} {ru.rows} · {result.model_input.schema_version}</p><code>{result.model_input.columns.join(', ')}</code></div>
              {result.analysis.warnings.length > 0 && <ul className="analysis-warnings">{result.analysis.warnings.map(warning => <li key={warning}>{warningLabel(warning)}</li>)}</ul>}
              <div className="provenance"><div><strong>{ru.weatherRun}</strong><span>{result.run_id}</span></div><div><strong>{ru.model}</strong><span>{result.model_id}</span></div>{result.model_provenance && <><div><strong>{ru.modelProfile}</strong><span>{result.model_provenance.profile === 'open_meteo_ecmwf_ifs_10m' ? ru.profileEcmwf : ru.profileMeasured}</span></div><div><strong>{ru.trainingWeather}</strong><span>{result.model_provenance.training_weather_kind === 'retrospective_stitched_forecast' ? ru.retrospectiveTrainingWeather : ru.notSpecified}</span></div><div><strong>{ru.forecastAccuracy}</strong><span>{result.model_provenance.forecast_accuracy_verified ? ru.yes : ru.notVerified}</span></div></>}<div><strong>{ru.trainingCutoff}</strong><span>{localTime(result.train_last_interval_start, result.timezone)}</span></div><div><strong>{ru.cached}</strong><span>{result.cache_hit ? ru.yes : ru.no}</span></div>{Object.entries(result.weather_provenance).map(([key, value]) => <div key={key}><strong>{fieldLabel(key)}</strong><span>{provenanceValue(key, value === null || value === undefined ? ru.notSpecified : String(value), result.timezone)}</span></div>)}</div>
              <ol className="trace">{result.trace.map((step, i) => <li key={`${step.step}-${i}`}><span className={step.status === 'ok' || step.status === 'cached' ? 'trace-ok' : ''}>{statusLabel(step.status)}</span><strong>{stepLabel(step.step)}</strong><small>{traceDetail(step.step, step.detail)}</small></li>)}</ol>
            </details>
          </section>
          {mode !== 'live' && <button className="advance-button" onClick={() => { const advanced = nextDate(date); setDate(advanced); runForecast({ siteId, date: advanced, horizon, mode }) }}>{ru.advance} →</button>}
        </>}
      </div>
    </main>
    <footer>{ru.footer} · <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Погода: Open-Meteo (CC BY 4.0)</a></footer>
  </div>
}
