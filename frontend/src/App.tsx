import { useEffect, useRef, useState } from 'react'
import { ApiFailure, askQuestion, createForecast, createReplayForecast, downloadCsv, explainForecast, getForecast, getSites, refreshWeather } from './api'
import type { Explanation, ForecastRequest, ForecastResult, QuestionAnswer, Site } from './types'
import { ru, percent, decimal, signedPoints, localTime, fieldLabel, statusLabel, stepLabel, provenanceLabel, coordinateLabel, provenanceValue, warningLabel, traceDetail, weatherProviderLabel } from './ru'
import PowerChart from './PowerChart'
import SiteMap from './SiteMap'
import AssistantText from './AssistantText'
import { saveBlob } from './chartExport'

function errorMessage(error: unknown): string {
  if (error instanceof TypeError) return 'Не удалось связаться с сервером. Проверьте подключение и повторите попытку.'
  if (error instanceof Error) return error.message
  return ru.requestFailed
}

const savedForecastKey = 'wind-demo:last-forecast-id'

function shiftDate(value: string, days: number): string {
  return new Date(Date.parse(`${value}T00:00:00Z`) + days * 86400000).toISOString().slice(0, 10)
}

function forecastDate(result: ForecastResult): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone: result.timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date(result.hours[0].valid_at))
  return ['year', 'month', 'day'].map(key => parts.find(part => part.type === key)!.value).join('-')
}

function savedForecastId(): string | null {
  try {
    const id = localStorage.getItem(savedForecastKey) || localStorage.getItem('wind-demo:last-live-forecast-id')
    return id && /^[0-9a-f]{64}$/.test(id) ? id : null
  } catch { return null }
}

function rememberForecast(id: string | null) {
  try {
    if (id) localStorage.setItem(savedForecastKey, id)
    else { localStorage.removeItem(savedForecastKey); localStorage.removeItem('wind-demo:last-live-forecast-id') }
  } catch { /* Browser storage can be disabled; current results still work. */ }
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
  return <AssistantText answer={answer}>
    {answer.selection && <p className="answer-selection"><strong>{ru.selectedPeriod}</strong> {localTime(answer.selection.start, 'Asia/Almaty')} — {localTime(answer.selection.end, 'Asia/Almaty')}</p>}
    {answer.tool_results?.filter(result => result.table && result.table.columns.length > 0).map((result, index) => <div className="table-scroll chat-table" key={`${result.tool}-${index}`}>
      <table><caption>{ru.calculationTable}</caption><thead><tr>{result.table!.columns.map((column, i) => <th scope="col" key={i}>{column}</th>)}</tr></thead>
        <tbody>{result.table!.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody>
      </table>
    </div>)}
  </AssistantText>
}

export default function App() {
  const [mode, setMode] = useState<'replay' | 'live'>('replay')
  const [weatherSource, setWeatherSource] = useState<'verified' | 'provider-documented'>('verified')
  const [date, setDate] = useState('2026-02-01')
  const [sites, setSites] = useState<Site[]>([])
  const [siteId, setSiteId] = useState('')
  const [horizon, setHorizon] = useState<24 | 48>(48)
  const [siteError, setSiteError] = useState('')
  const [error, setError] = useState('')
  const [result, setResult] = useState<ForecastResult | null>(null)
  const [previous, setPrevious] = useState<ForecastResult | null>(null)
  const [explanation, setExplanation] = useState<Explanation | null>(null)
  const [explanationError, setExplanationError] = useState('')
  const [explanationPending, setExplanationPending] = useState(false)
  const [restored, setRestored] = useState(false)
  const [loading, setLoading] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [question, setQuestion] = useState('')
  const [conversation, setConversation] = useState<{ question: string, answer: QuestionAnswer }[]>([])
  const [pendingQuestion, setPendingQuestion] = useState('')
  const [questionError, setQuestionError] = useState('')
  const [downloadError, setDownloadError] = useState('')
  const [asking, setAsking] = useState(false)
  const requestEpoch = useRef(0)
  const forecastController = useRef<AbortController | null>(null)
  const answerController = useRef<AbortController | null>(null)
  const conversationId = useRef<string | null>(null)
  const askingNow = useRef(false)
  const lastSuccess = useRef<ForecastResult | null>(null)

  function invalidate() {
    requestEpoch.current += 1
    forecastController.current?.abort()
    answerController.current?.abort()
    conversationId.current = null
    askingNow.current = false
    setResult(null); setPrevious(null); setExplanation(null); setConversation([]); setQuestion(''); setPendingQuestion('')
    setError(''); setExplanationError(''); setQuestionError(''); setDownloadError(''); setLoading(false); setRestoring(false); setRefreshing(false); setAsking(false); setExplanationPending(false); setRestored(false)
  }

  useEffect(() => {
    const controller = new AbortController()
    const epoch = requestEpoch.current
    forecastController.current = controller
    setSites([]); setSiteId(''); setSiteError('')
    getSites(controller.signal).then(async loaded => {
      if (controller.signal.aborted || epoch !== requestEpoch.current) return
      setSites(loaded)
      if (loaded.length) setSiteId(loaded[0].turbine_id)
      else setSiteError(ru.noSites)
      const id = savedForecastId()
      if (!id || !loaded.length) return
      setLoading(true)
      setRestoring(true)
      try {
        const forecast = await getForecast(id, controller.signal)
        if (controller.signal.aborted || epoch !== requestEpoch.current) return
        if (forecast.status !== 'ok' || forecast.forecast_id !== id || !['live', 'archive'].includes(forecast.mode) || !loaded.some(site => site.turbine_id === forecast.turbine_id) || !forecast.hours?.length || !forecast.model_input) {
          rememberForecast(null)
          throw new Error(ru.savedForecastUnavailable)
        }
        setSiteId(forecast.turbine_id)
        setHorizon(forecast.horizon_hours)
        setMode(forecast.mode === 'archive' ? 'replay' : 'live')
        if (forecast.mode === 'archive') {
          setDate(forecastDate(forecast))
          setWeatherSource(forecast.weather_provenance.provenance_status === 'verified' ? 'verified' : 'provider-documented')
        }
        lastSuccess.current = forecast
        setResult(forecast)
        setRestored(true)
      } catch (err) {
        if (controller.signal.aborted || epoch !== requestEpoch.current) return
        if (err instanceof ApiFailure && err.code === 'NOT_FOUND') rememberForecast(null)
        setError(err instanceof ApiFailure && err.code === 'NOT_FOUND' ? ru.savedForecastUnavailable : ru.savedForecastLoadFailed)
      } finally {
        if (!controller.signal.aborted && epoch === requestEpoch.current) { setLoading(false); setRestoring(false) }
      }
    }).catch(err => { if (!controller.signal.aborted) setSiteError(errorMessage(err)) })
    return () => controller.abort()
  }, [])

  async function loadExplanation(forecast: ForecastResult, controller: AbortController, epoch: number) {
    setExplanationPending(true)
    setExplanationError('')
    try {
      const prose = await explainForecast(forecast.forecast_id, controller.signal)
      if (epoch === requestEpoch.current && !controller.signal.aborted) {
        if (prose.forecast_fingerprint !== forecast.fingerprint) throw new Error(ru.staleExplanation)
        setExplanation(prose)
      }
    } catch (err) {
      if (epoch === requestEpoch.current && !controller.signal.aborted) setExplanationError(errorMessage(err))
    } finally {
      if (epoch === requestEpoch.current && !controller.signal.aborted) setExplanationPending(false)
    }
  }

  async function runForecast(next: { siteId: string, horizon: 24 | 48 }, refresh = false) {
    invalidate()
    const epoch = requestEpoch.current
    const controller = new AbortController()
    forecastController.current = controller
    setLoading(true)
    setRefreshing(refresh)
    const input: ForecastRequest = { turbine_id: next.siteId, origin: new Date().toISOString(), horizon_hours: next.horizon, mode: 'live' }
    try {
      if (refresh && mode === 'live') {
        await refreshWeather(next.siteId, controller.signal)
        if (epoch !== requestEpoch.current) return
        setRefreshing(false)
      }
      const forecast = mode === 'replay'
        ? await createReplayForecast({ turbine_id: next.siteId, forecast_date: date, horizon_hours: next.horizon, weather_source: weatherSource }, controller.signal)
        : await createForecast(input, controller.signal)
      if (epoch !== requestEpoch.current) return
      if (forecast.status !== 'ok' || !forecast.forecast_id || !forecast.model_input || !forecast.hours?.length) throw new Error(ru.incompleteForecast)
      setPrevious(lastSuccess.current?.turbine_id === forecast.turbine_id && lastSuccess.current?.mode === forecast.mode ? lastSuccess.current : null)
      lastSuccess.current = forecast
      setResult(forecast)
      rememberForecast(forecast.forecast_id)
      setLoading(false)
      await loadExplanation(forecast, controller, epoch)
    } catch (err) {
      if (epoch === requestEpoch.current && !controller.signal.aborted) { lastSuccess.current = null; setError(err instanceof ApiFailure && err.code === 'WEATHER_UNAVAILABLE' && mode === 'replay' ? (weatherSource === 'verified' ? 'Операционный архив ECMWF для этой даты пока не подготовлен или не прошёл проверку времени публикации. Загрузите архив на сервере и повторите расчёт.' : 'Архивный выпуск для этой даты отсутствует или не прошёл проверку. Проверьте февральский комплект погоды на сервере.') : errorMessage(err)); setLoading(false); setRefreshing(false) }
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
  const mean = result ? result.hours.reduce((sum, row) => sum + row.power_norm, 0) / result.hours.length : 0

  return <div className="app-shell">
    <header className="page-header">
      <div><h1>{ru.pageTitle}</h1><p>{ru.pageSubtitle}</p></div>
      <span className="mode-badge"><i />{mode === 'replay' ? 'Февраль 2026 · исторический прогноз' : ru.live}</span>
    </header>
    <main className="workspace">
      <aside className="setup-column" aria-label={ru.selectForecast}>
        <section className="panel setup-panel">
          <div className="section-title"><h2>{ru.selectForecast}</h2></div>
          <label className="field scenario-field"><span>Сценарий</span><select aria-label="Сценарий" value={mode} onChange={e => { invalidate(); setMode(e.target.value as 'replay' | 'live') }}><option value="replay">Февраль 2026 · задание жюри</option><option value="live">Текущий прогноз</option></select></label>
          <SiteMap sites={sites} selected={siteId} onSelect={id => { if (id !== siteId) { invalidate(); setSiteId(id) } }} />
          <label className="field"><span>{ru.turbine}</span><select aria-label={ru.turbine} value={siteId} onChange={e => { invalidate(); setSiteId(e.target.value) }} disabled={!sites.length}><option value="">{ru.chooseTurbine}</option>{sites.map(site => <option key={site.turbine_id} value={site.turbine_id}>{site.turbine_id}</option>)}</select></label>
          {selectedSite && <div className="site-meta"><span>{new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 6 }).format(selectedSite.latitude)} · {new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 6 }).format(selectedSite.longitude)}</span><small>{coordinateLabel(selectedSite.coordinate_status)}</small>{selectedSite.coordinate_source && <a href={selectedSite.coordinate_source} target="_blank" rel="noreferrer">{ru.openMap} ↗</a>}</div>}
          {siteError && <div className="error-banner" role="alert">{siteError}</div>}
          <label className="field"><span>{ru.horizon}</span><select aria-label={ru.horizon} value={horizon} onChange={e => { invalidate(); setHorizon(Number(e.target.value) as 24 | 48) }}><option value={24}>{ru.hours24}</option><option value={48}>{ru.hours48}</option></select></label>
          {mode === 'replay' && <div className="replay-controls">
            <label className="field"><span>Подтверждение архивной погоды</span><select aria-label="Подтверждение архивной погоды" value={weatherSource} onChange={e => { invalidate(); setWeatherSource(e.target.value as 'verified' | 'provider-documented') }}><option value="verified">ECMWF: операционный архив</option><option value="provider-documented">Архив с допущением о доступности</option></select></label>
            <p className="origin-note">{weatherSource === 'verified' ? 'Операционные выпуски ECMWF из публичного архива. Время публикации архивной копии проверяется по метаданным объекта и должно быть не позже момента расчёта.' : 'Условный вариант: архив поставщика с предполагаемой задержкой публикации 24 часа. Он не подтверждает полное соответствие требованию жюри.'}</p>
            <label className="field"><span>Первый день прогноза</span><select aria-label="Первый день прогноза" value={date} onChange={e => { invalidate(); setDate(e.target.value) }}>{Array.from({ length: 28 }, (_, i) => { const value = `2026-02-${String(i + 1).padStart(2, '0')}`; return <option key={value} value={value}>{i + 1} февраля 2026</option> })}</select></label>
            <div className="replay-navigation"><button type="button" className="secondary-button" disabled={date === '2026-02-01'} onClick={() => { invalidate(); setDate(shiftDate(date, -1)) }}>← День</button><button type="button" className="secondary-button" disabled={date === '2026-02-28'} onClick={() => { invalidate(); setDate(shiftDate(date, 1)) }}>День →</button></div>
          </div>}
          <p className="origin-note">{mode === 'replay' ? `Расчёт на ${shiftDate(date, -1).split('-').reverse().join('.')} в 23:00 (UTC+5). Прогноз начинается в 00:00 выбранного дня. После смены дня нажмите «Рассчитать прогноз».` : ru.liveTime}</p>
          <button className="primary-button" disabled={!siteId || loading} onClick={() => runForecast({ siteId, horizon })}>{loading ? (restoring ? ru.openingSavedForecast : refreshing ? ru.refreshingWeather : ru.calculating) : ru.predict}</button>
          {error && <div className="error-banner" role="alert">{error}</div>}
        </section>
        <p className="scope-note">{mode === 'replay' ? '28 ежедневных запусков: с 31 января по 27 февраля, с покрытием 1–28 февраля. Используются архивные выпуски прогноза ECMWF IFS, а не фактическая погода. Горизонт 48 часов в конце периода захватывает март. Фактической мощности за февраль в переданных данных нет.' : ru.liveNotice}</p>
      </aside>
      <div className="results-column">
        {mode === 'replay' && <section className="panel replay-downloads"><h2>Комплект за весь февраль</h2><p>Обе турбины, ежедневные запуски. В отчёте указаны покрытие и происхождение погоды. Если подтверждённый комплект ещё не сформирован, сервер сообщит об этом.</p><div><a href="/api/replay/february/download?kind=forecast" download>Все прогнозы · CSV</a><a href="/api/replay/february/download?kind=daily" download>Первые 24 часа · CSV</a><a href="/api/replay/february/download?kind=report" download>Отчёт · JSON</a></div></section>}
        {!result && <section className="panel empty-state" aria-live="polite"><div className="empty-chart" aria-hidden="true"><svg viewBox="0 0 200 60"><path d="M0 50 L28 40 L55 47 L82 18 L108 28 L138 8 L166 22 L200 3" /></svg></div><h2>{loading ? (restoring ? ru.openingSavedForecast : refreshing ? ru.refreshingWeather : ru.calculating) : ru.emptyTitle}</h2><p>{loading ? (restoring ? ru.savedForecastNotice : ru.loadingHint) : mode === 'replay' ? 'Выберите турбину, день февраля и горизонт. Расчёт использует архивный прогноз погоды, сформированный до выбранного момента.' : ru.emptyText}</p></section>}
        {result && <>
          <section className="panel result-panel">
            <div className="result-heading"><div><h2>{ru.resultTitle}</h2><p>{result.turbine_id} · {result.horizon_hours} ч · {provenanceLabel(result.weather_provenance.provenance_status)}</p></div><div className="result-actions"><>{result.mode === 'live' && <button type="button" className="secondary-button" onClick={() => runForecast({ siteId, horizon }, true)}>{ru.refreshWeather}</button>}</><button type="button" className="secondary-button" onClick={() => saveCsv('forecast')}>{ru.downloadForecast}</button></div></div>
            {restored && <p className="origin-note" role="status"><strong>{ru.savedForecast}.</strong> {ru.savedForecastNotice}</p>}
            <div className="weather-freshness" aria-label={ru.weatherRetrieved}><span><strong>{ru.weatherProvider}</strong> {weatherProviderLabel(result.weather_provenance.provider)}</span><span><strong>{ru.weatherRetrieved}</strong> {result.weather_provenance.retrieved_at ? localTime(result.weather_provenance.retrieved_at, result.timezone) : ru.weatherRetrievalUnknown}</span>{result.weather_provenance.weather_cache_hit === true && <span>{ru.cachedWeather}</span>}</div>
            {result.mode === 'archive' && <div className="replay-evidence">
              <h3>Исторический запуск</h3>
              <dl><div><dt>Момент расчёта мощности</dt><dd>{localTime(result.origin, result.timezone)}</dd></div><div><dt>Инициализация прогноза погоды</dt><dd>{typeof result.weather_provenance.initialized_at === 'string' ? localTime(result.weather_provenance.initialized_at, result.timezone) : ru.notSpecified}</dd></div><div><dt>{result.weather_provenance.provenance_status === 'verified' ? 'Публикация архивной копии' : 'Предполагаемая доступность выпуска'}</dt><dd>{result.weather_provenance.provenance_status === 'verified' && typeof result.weather_provenance.available_at === 'string' ? localTime(result.weather_provenance.available_at, result.timezone) : typeof result.weather_provenance.assumed_available_by === 'string' ? localTime(result.weather_provenance.assumed_available_by, result.timezone) : ru.notSpecified}</dd></div></dl>
              {result.weather_provenance.provenance_status !== 'verified' && <p className="warning-banner">Архивный прогноз по данным поставщика. Доступность выпуска в прошлом принята по правилу задержки 24 часа; фактическое время публикации не подтверждено. Это условное воспроизведение, а не подтверждённый журнал доступности.</p>}
              {result.weather_provenance.provenance_status === 'verified' && <p>Метка публикации архивной копии — верхняя граница доступности: выпуск существовал к этому моменту. Точная дата первой публикации может быть раньше.</p>}
              {(result.weather_provenance.interpolation && result.weather_provenance.interpolation !== 'none') && <p>Почасовые входы модели получены интерполяцией исходного прогноза. Метод: {provenanceLabel(String(result.weather_provenance.interpolation))}.</p>}
              <p>Модель заморожена до тестового периода. Фактическая мощность за февраль отсутствует — оценка точности не рассчитывается.</p>
            </div>}
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
                {explanation ? <><AssistantText answer={explanation} />{explanation.model && <div className="explanation-meta">{explanation.model}</div>}</> : explanationPending ? <p className="muted loading-status" role="status">{ru.explanationLoading}</p> : restored ? <><p className="muted">{ru.savedExplanationHint}</p><button type="button" className="secondary-button" onClick={() => { const controller = new AbortController(); forecastController.current = controller; void loadExplanation(result, controller, requestEpoch.current) }}>{ru.loadExplanation}</button>{explanationError && <div className="error-banner">{ru.explanationUnavailable}: {explanationError}</div>}</> : explanationError ? <div className="error-banner">{ru.explanationUnavailable}: {explanationError}</div> : <p className="muted loading-status" role="status">{ru.explanationLoading}</p>}
              </div>
              {conversation.map((exchange, index) => <div className="chat-exchange" key={index}>
                <div className="chat-message user-message"><span className="message-author">{ru.you}</span><p>{exchange.question}</p></div>
                <div className="chat-message assistant-message"><span className="message-author">{ru.analysisAuthor}</span><AnswerContent answer={exchange.answer} /></div>
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
        </>}
      </div>
    </main>
    <footer>{ru.footer} · <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Погода: Open-Meteo (CC BY 4.0)</a></footer>
  </div>
}
