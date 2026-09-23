import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import { askQuestion, createForecast, downloadCsv, explainForecast, getSites } from './api'
import type { Explanation, ForecastRequest, ForecastResult, Site, WeatherMode } from './types'
import { decimal, localTime, ru, signedPoints } from './ru'
import { saveBlob } from './chartExport'
import { weatherForHour } from './experience/weather'
import Icon, { BrandMark } from './ui/Icon'
import Sheet from './ui/Sheet'
import Analytics from './ui/Analytics'
import type { AnalyticsTab } from './ui/Analytics'
import TimeScrubber, { dayLabel, hourLabel } from './timeline/TimeScrubber'
import { hoursLabel } from './timeline/format'
import { daylightHour } from './timeline/daylight'
import Assistant from './assistant/Assistant'
import type { AgentPhase, AssistantMessage } from './assistant/Assistant'
import { biggestDrop, explainSelectedHour, localDate, parseUICommand, seekDescription, selectForecastHour, tomorrowDate } from './assistant/agentTools'

const WorldScene = lazy(() => import('./scene/WorldScene'))
const FIRST_DATE = '2026-01-31'
const LAST_DATE = '2026-02-01'
type View = 'earth' | 'turbine'
type Quality = 'auto' | 'high' | 'medium' | 'low'
type ForecastOptions = { siteId: string, date: string, horizon: 24 | 48, mode: WeatherMode }
const modeNames: Record<WeatherMode, string> = { live: 'Прогноз Open-Meteo', fixture: 'Демонстрационная погода', archive: 'Проверенный архив' }
const originForDate = (date: string) => `${date}T18:00:00Z`
const errorMessage = (error: unknown) => error instanceof Error ? error.message : ru.requestFailed

function validForecast(forecast: ForecastResult, input: ForecastRequest): boolean {
  return Boolean(forecast) && forecast.status === 'ok' && Boolean(forecast.forecast_id && forecast.fingerprint && forecast.model_input)
    && forecast.turbine_id === input.turbine_id && forecast.mode === input.mode && forecast.horizon_hours === input.horizon_hours
    && (input.mode === 'live' || forecast.origin === input.origin) && Array.isArray(forecast.hours) && forecast.hours.length === input.horizon_hours
    && forecast.hours.every((hour, index) => hour.lead_hour === index + 1 && Date.parse(hour.valid_at) === Date.parse(forecast.origin) + (index + 1) * 3600000 && [hour.wind_speed_ms, hour.temperature_c, hour.power_norm].every(Number.isFinite) && hour.power_norm >= 0 && hour.power_norm <= 1)
}

export default function App() {
  const [mode, setMode] = useState<WeatherMode>('live')
  const [sites, setSites] = useState<Site[]>([])
  const [siteId, setSiteId] = useState('')
  const [date, setDate] = useState(FIRST_DATE)
  const [horizon, setHorizon] = useState<24 | 48>(48)
  const [view, setView] = useState<View>('earth')
  const [quality, setQuality] = useState<Quality>('auto')
  const [siteError, setSiteError] = useState('')
  const [siteRetry, setSiteRetry] = useState(0)
  const [error, setError] = useState('')
  const [result, setResult] = useState<ForecastResult | null>(null)
  const [previous, setPrevious] = useState<ForecastResult | null>(null)
  const [explanation, setExplanation] = useState<Explanation | null>(null)
  const [explanationError, setExplanationError] = useState('')
  const [loading, setLoading] = useState(false)
  const [explaining, setExplaining] = useState(false)
  const [index, setIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [playEndIndex, setPlayEndIndex] = useState<number | null>(null)
  const [sheet, setSheet] = useState<'settings' | 'analytics' | null>(null)
  const [analyticsTab, setAnalyticsTab] = useState<AnalyticsTab>('forecast')
  const [assistantOpen, setAssistantOpen] = useState(false)
  const [mobile, setMobile] = useState(() => window.matchMedia('(max-width: 600px)').matches)
  const [messages, setMessages] = useState<AssistantMessage[]>([])
  const [pendingQuestion, setPendingQuestion] = useState('')
  const [questionError, setQuestionError] = useState('')
  const [downloadError, setDownloadError] = useState('')
  const [asking, setAsking] = useState(false)
  const [actionNotice, setActionNotice] = useState('')
  const requestEpoch = useRef(0)
  const actionEpoch = useRef(0)
  const forecastController = useRef<AbortController | null>(null)
  const answerController = useRef<AbortController | null>(null)
  const lastSuccess = useRef<ForecastResult | null>(null)
  const messageId = useRef(0)
  const introPlayed = useRef(false)
  const reducedMotion = useReducedMotion() || false
  const enterIntro = !introPlayed.current && !reducedMotion
  const selectedSite = sites.find(site => site.turbine_id === siteId) || null
  const selectedHour = result?.hours[index] || null
  const weather = useMemo(() => selectedSite && selectedHour && result ? weatherForHour(selectedHour, selectedSite, undefined, result.mode) : null, [selectedSite, selectedHour, result])
  const insight = useMemo(() => result ? biggestDrop(result) : null, [result])
  const daylightIndex = useMemo(() => result && selectedSite ? daylightHour(result, selectedSite, index) : null, [result, selectedSite, index])

  function invalidate() {
    requestEpoch.current += 1
    forecastController.current?.abort()
    answerController.current?.abort()
    setResult(null); setPrevious(null); setExplanation(null); setMessages([]); setPendingQuestion('')
    setError(''); setExplanationError(''); setQuestionError(''); setDownloadError(''); setLoading(false); setAsking(false); setExplaining(false)
    setPlaying(false); setPlayEndIndex(null); setIndex(0); setActionNotice('')
  }
  function cancelAction() {
    actionEpoch.current += 1
    answerController.current?.abort()
    setPendingQuestion(''); setAsking(false); setPlaying(false); setPlayEndIndex(null); setActionNotice('')
  }
  function updateInputs(change: () => void) { cancelAction(); invalidate(); change() }

  useEffect(() => {
    const controller = new AbortController()
    setSiteError('')
    getSites(mode, controller.signal).then(loaded => {
      if (controller.signal.aborted) return
      setSites(loaded)
      setSiteId(current => loaded.some(site => site.turbine_id === current) ? current : loaded[0]?.turbine_id || '')
      if (!loaded.length) setSiteError(ru.noSites)
    }).catch(err => { if (!controller.signal.aborted) { setSites([]); setSiteError(errorMessage(err)) } })
    return () => controller.abort()
  }, [mode, siteRetry])

  useEffect(() => () => { requestEpoch.current += 1; actionEpoch.current += 1; forecastController.current?.abort(); answerController.current?.abort() }, [])
  useEffect(() => { introPlayed.current = true }, [])

  useEffect(() => {
    const media = window.matchMedia('(max-width: 600px)')
    const update = () => setMobile(media.matches)
    media.addEventListener('change', update)
    return () => media.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    if (!playing || !result) return
    const timer = window.setInterval(() => setIndex(current => {
      if (current >= (playEndIndex ?? result.hours.length - 1)) { setPlaying(false); return current }
      return current + 1
    }), reducedMotion ? 1800 : 850)
    return () => window.clearInterval(timer)
  }, [playing, result, reducedMotion, playEndIndex])

  useEffect(() => {
    function key(event: KeyboardEvent) {
      if (event.defaultPrevented) return
      if (event.key === 'Escape' && !sheet && !assistantOpen) { cancelAction(); setView('earth') }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [sheet, assistantOpen])

  async function runForecast(next: ForecastOptions): Promise<ForecastResult | null> {
    if (!next.siteId) return null
    invalidate()
    const epoch = requestEpoch.current
    const controller = new AbortController()
    forecastController.current = controller
    setLoading(true)
    const input: ForecastRequest = { turbine_id: next.siteId, origin: next.mode === 'live' ? new Date().toISOString() : originForDate(next.date), horizon_hours: next.horizon, mode: next.mode }
    try {
      const forecast = await createForecast(input, controller.signal)
      if (epoch !== requestEpoch.current || controller.signal.aborted) return null
      if (!validForecast(forecast, input)) throw new Error(ru.incompleteForecast)
      setPrevious(lastSuccess.current?.turbine_id === forecast.turbine_id && lastSuccess.current.mode === forecast.mode ? lastSuccess.current : null)
      lastSuccess.current = forecast
      setResult(forecast); setLoading(false); setExplaining(true)
      // Numeric output is committed first. Prose runs independently and is bound to the same ID.
      void explainForecast(forecast.forecast_id, controller.signal).then(prose => {
        if (epoch !== requestEpoch.current || controller.signal.aborted) return
        if (prose.forecast_fingerprint !== forecast.fingerprint) throw new Error(ru.staleExplanation)
        setExplanation(prose)
      }).catch(err => {
        if (epoch === requestEpoch.current && !controller.signal.aborted) setExplanationError(errorMessage(err))
      }).finally(() => { if (epoch === requestEpoch.current && !controller.signal.aborted) setExplaining(false) })
      return forecast
    } catch (err) {
      if (epoch === requestEpoch.current && !controller.signal.aborted) { setError(errorMessage(err)); setLoading(false) }
      return null
    }
  }

  function selectSite(id: string) {
    cancelAction(); setSheet(null); setView('turbine')
    if (id !== siteId || !result) { setSiteId(id); void runForecast({ siteId: id, date, horizon, mode }) }
  }
  function goEarth() { cancelAction(); setView('earth'); setSheet(null) }
  function seek(next: number) { if (!result) return; cancelAction(); setIndex(Math.max(0, Math.min(result.hours.length - 1, next))) }
  function openAnalytics(tab: AnalyticsTab = 'forecast') { setAnalyticsTab(tab); setAssistantOpen(false); setSheet('analytics'); setPlaying(false) }
  function localReply(question: string, text: string) { setMessages(current => [...current, { id: ++messageId.current, question, text, backend: 'local' }]); setPendingQuestion(''); setAsking(false) }

  async function commandAssistant(question: string) {
    const command = parseUICommand(question)
    cancelAction()
    const token = actionEpoch.current
    setQuestionError('')
    if (command.intent === 'earth') { setView('earth'); setAssistantOpen(false); localReply(question, 'Вернулись к Земле. Прогноз и выбранный час сохранены.'); return }
    if (command.intent === 'limitations' || /что доступно|что умеешь|доступные|возможности/i.test(question)) {
      localReply(question, 'Доступны две зарегистрированные турбины, 24 или 48 часов, ветер, температура и нормализованная мощность. Я могу выбрать турбину, час минимума, максимума или наибольшего снижения, открыть график и вернуть Землю. Навигация выполняется локальными командами; объяснение запрашивается по сохранённому прогнозу. SCADA, состояние оборудования и калиброванная неопределённость недоступны.'); return
    }
    let active = result
    const targetId = command.turbineId || siteId || sites[0]?.turbine_id
    if (!targetId || !sites.length) { setQuestionError('Сначала дождитесь загрузки реестра турбин.'); return }
    if (!sites.some(site => site.turbine_id === targetId)) { setQuestionError(`Турбины ${targetId} нет в реестре. Выберите T1 или T2.`); return }
    if (!active || active.turbine_id !== targetId) {
      setSiteId(targetId); setView('turbine')
      const request = runForecast({ siteId: targetId, date, horizon, mode })
      setPendingQuestion(question)
      active = await request
      if (token !== actionEpoch.current) return
      setPendingQuestion('')
      if (!active) { setQuestionError('Прогноз не получен. Проверьте источник погоды и повторите запрос.'); return }
    }
    if (token !== actionEpoch.current) return
    if (command.intent === 'analytics') { localReply(question, 'Открыт график активного прогноза. Выберите час, чтобы переместить временную шкалу.'); openAnalytics(/таблиц/i.test(question) ? 'table' : 'forecast'); return }
    if (['minimum', 'maximum', 'ramp', 'tomorrow', 'navigate'].includes(command.intent)) {
      const target = selectForecastHour(active, command.intent, command.tomorrow || command.intent === 'tomorrow')
      if (target === null) { localReply(question, `В этом горизонте нет нужных часов. «Завтра» означает день после даты выпуска: ${tomorrowDate(active)}. Выберите 48 часов или другой доступный запуск.`); return }
      if (command.intent === 'ramp' && target > 0 && active.hours[target].power_norm >= active.hours[target - 1].power_norm) {
        localReply(question, 'В выбранном периоде нет почасового снижения мощности. Текущий час сохранён.')
        return
      }
      setIndex(target); setView('turbine')
      const response = seekDescription(active, target, command.intent)
      localReply(question, response)
      setActionNotice(response)
      setAssistantOpen(false)
      if (command.intent === 'tomorrow') {
        const day = tomorrowDate(active)
        setPlayEndIndex(active.hours.reduce((last, hour, hourIndex) => localDate(hour.valid_at, active!.timezone) === day ? hourIndex : last, target))
        setPlaying(true)
      }
      return
    }
    if (command.intent === 'here') {
      localReply(question, explainSelectedHour(active, active === result ? index : 0))
      return
    }
    answerController.current?.abort()
    const controller = new AbortController()
    answerController.current = controller
    const epoch = requestEpoch.current
    const currentHour = active.hours[active === result ? index : 0]
    setPendingQuestion(question); setAsking(true)
    try {
      const contextualQuestion = `${question}\nКонтекст интерфейса: турбина ${active.turbine_id}; выбранный час ${currentHour.valid_at}; часовой пояс ${active.timezone}. Используй только сохранённый прогноз; не считай показания измерениями.`
      const answer = await askQuestion(active.forecast_id, contextualQuestion, controller.signal)
      if (epoch !== requestEpoch.current || token !== actionEpoch.current || controller.signal.aborted) return
      if (answer.forecast_fingerprint !== active.fingerprint) throw new Error(ru.staleAnswer)
      setMessages(current => [...current, { id: ++messageId.current, question, text: answer.text, backend: answer.backend, warning: answer.warning }]); setPendingQuestion('')
    } catch (err) {
      if (epoch === requestEpoch.current && token === actionEpoch.current && !controller.signal.aborted) { setQuestionError(errorMessage(err)); setPendingQuestion('') }
    } finally { if (epoch === requestEpoch.current && token === actionEpoch.current && !controller.signal.aborted) setAsking(false) }
  }

  async function saveCsv(kind: 'forecast' | 'model-input') {
    if (!result) return
    const active = result, epoch = requestEpoch.current
    setDownloadError('')
    try {
      const blob = await downloadCsv(active.forecast_id, kind)
      if (epoch !== requestEpoch.current) return
      saveBlob(blob, kind === 'model-input' ? active.model_input.filename : `forecast-${active.turbine_id}-${active.origin.slice(0, 10)}-${active.horizon_hours}h.csv`)
    } catch (err) { if (epoch === requestEpoch.current) setDownloadError(errorMessage(err)) }
  }

  const phase: AgentPhase = error || questionError ? 'warning' : loading ? 'forecast' : asking ? 'answering' : explaining ? 'analyzing' : result ? 'ready' : 'idle'
  const assistantContext = `${view === 'earth' ? 'Обзор Земли' : siteId ? `Турбина ${siteId}` : 'Выбор турбины'}${selectedHour && result ? ` · ${dayLabel(selectedHour.valid_at, result.timezone)}, ${hourLabel(selectedHour.valid_at, result.timezone)}` : ''}`
  const showSceneData = view === 'turbine' && selectedSite

  return <div className={`experience ${view === 'earth' ? 'earth-view' : 'turbine-view'} ${sheet ? 'has-sheet' : ''}`}>
    <main className="world-stage" aria-label="Исследование ветра и прогноза мощности" inert={sheet !== null || (assistantOpen && mobile)}>
      <Suspense fallback={<div className="scene-loading" role="status"><span />Земля появляется…</div>}><WorldScene sites={sites} selectedSite={selectedSite} view={view} weather={weather} onSelect={selectSite} quality={quality} reducedMotion={reducedMotion} onViewChange={next => next === 'earth' ? goEarth() : setView(next)} /></Suspense>
      <div className="world-vignette" aria-hidden="true" />
      <motion.header className="app-header" initial={enterIntro ? { opacity: 0, y: -8 } : false} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', stiffness: 270, damping: 33 }}><button className="brand" onClick={goEarth} aria-label="Samal — вернуться к Земле"><BrandMark /><span>samal<span className="brand-period">.</span></span></button><span className="header-caption">ЭНЕРГИЯ В ПЕРСПЕКТИВЕ</span><div className="header-controls"><button className={`source-pill source-${mode}`} aria-label={`Источник погоды: ${modeNames[mode]}. Открыть параметры прогноза`} onClick={() => { setAssistantOpen(false); setSheet('settings') }}><span className="status-dot" /><span className="source-long">{modeNames[mode]}</span><span className="source-short">{mode === 'live' ? 'Прогноз' : mode === 'fixture' ? 'Демо' : 'Архив'}</span><Icon name="chevron" size={12} /></button><button className="icon-button settings-trigger" onClick={() => { setAssistantOpen(false); setSheet('settings') }} aria-label="Настроить прогноз и качество сцены"><Icon name="settings" /></button></div></motion.header>
      {view === 'earth' ? <>
        <motion.section className="earth-intro" initial={enterIntro ? { opacity: 0, y: 13 } : false} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', stiffness: 220, damping: 31, delay: enterIntro ? .08 : 0 }}><p className="eyebrow"><span className="small-rule" />НАБЛЮДАЯ ЗА НЕВИДИМЫМ</p><h1>Увидеть<br />энергию<br /><em>ветра.</em></h1><p className="intro-copy">От движения воздуха<br />до следующего часа энергии.</p><div className="overview-meta"><span><strong>{String(sites.length).padStart(2, '0')}</strong> турбины</span><span><strong>{horizon}</strong> {horizon === 24 ? 'часа' : 'часов'} вперёд</span></div></motion.section>
        <motion.section className="turbine-registry" initial={enterIntro ? { opacity: 0, y: 9 } : false} animate={{ opacity: 1, y: 0 }} transition={{ type: 'spring', stiffness: 250, damping: 33, delay: enterIntro ? .18 : 0 }} aria-label="Зарегистрированные турбины"><div className="registry-heading"><span className="eyebrow">КАЗАХСТАН</span><span>43,64° С · 78,54° В</span></div>{sites.map(site => <button className="registry-row" key={site.turbine_id} onClick={() => selectSite(site.turbine_id)} aria-label={`Исследовать турбину ${site.turbine_id}`}><span className="registry-marker"><span /></span><span className="registry-name">Турбина {site.turbine_id}<small>{site.latitude.toFixed(4)}° · {site.longitude.toFixed(4)}°</small></span><span className="registry-state">{result?.turbine_id === site.turbine_id ? 'Прогноз готов' : 'Исследовать'}</span><Icon name="arrow" size={17} /></button>)}{!sites.length && !siteError && <p className="registry-loading" role="status">Загружаем реестр турбин…</p>}{siteError && <div className="registry-error" role="alert"><p>{siteError}</p><button className="text-button" onClick={() => setSiteRetry(value => value + 1)}>Повторить <Icon name="refresh" size={14} /></button></div>}<p className="registry-note">Координаты пользователя · статус оборудования не передаётся</p></motion.section>
        <div className="earth-instructions"><span className="drag-orbit" aria-hidden="true">↔</span><span>Вращайте Землю. Выберите турбину.</span></div>
      </> : <>
        <nav className="spatial-nav" aria-label="Навигация по сцене"><button className="back-earth" onClick={goEarth}><Icon name="back" size={17} /><span>К Земле</span></button><span className="nav-divider" />{sites.map(site => <button key={site.turbine_id} className={`turbine-tab ${siteId === site.turbine_id ? 'active' : ''}`} onClick={() => selectSite(site.turbine_id)} aria-pressed={siteId === site.turbine_id}>{site.turbine_id}</button>)}</nav>
        {showSceneData && <section className="turbine-overview" aria-label={`Прогноз турбины ${siteId}`}><p className="eyebrow">КАЗАХСТАН · КООРДИНАТЫ ПОЛЬЗОВАТЕЛЯ</p><h1>Турбина <em>{siteId.replace('T', '')}</em></h1><p className="turbine-location">{selectedSite.latitude.toFixed(6)}° с. ш. &nbsp; {selectedSite.longitude.toFixed(6)}° в. д.</p>
          {selectedHour && result ? <div className="telemetry" aria-live="off"><div className="power-reading"><span className="reading-label">Нормализованная мощность</span><strong>{decimal(selectedHour.power_norm * 100)}<span>%</span></strong><span className="reading-caption">Прогноз · шкала [0, 1], не МВт</span></div><div className="weather-readings"><div><span><Icon name="wind" size={16} />Ветер</span><strong>{decimal(selectedHour.wind_speed_ms)}<small>м/с</small></strong></div><div><span><Icon name="temperature" size={16} />Температура</span><strong>{decimal(selectedHour.temperature_c)}<small>°C</small></strong></div></div><button className="analytics-link" onClick={() => openAnalytics()}><Icon name="chart" size={18} />Исследовать прогноз<Icon name="arrow" size={16} /></button></div> : <div className="forecast-empty"><span className={loading ? 'waiting-line' : 'empty-line'} /> <p role="status">{loading ? 'Получаем погоду. Рассчитываем мощность.' : error ? 'Прогноз пока недоступен.' : 'Мир готов. Добавим прогноз.'}</p><small>{loading ? 'Результат появится после проверки CSV и модели.' : 'Выберите источник и горизонт, чтобы исследовать время.'}</small>{!loading && <button className="primary-button" onClick={() => { cancelAction(); void runForecast({ siteId, date, horizon, mode }) }}><Icon name="refresh" size={16} />{error ? 'Повторить прогноз' : 'Сформировать прогноз'}</button>}</div>}
        </section>}
        {result && selectedHour && <><div className="scene-time"><span className="eyebrow">{mode === 'fixture' ? 'ИСТОРИЧЕСКАЯ ДЕМОНСТРАЦИЯ' : mode === 'live' ? 'ПРОГНОЗ ПОГОДЫ' : 'АРХИВНЫЙ ПРОГНОЗ'}</span><strong>{hourLabel(selectedHour.valid_at, result.timezone)}</strong><span>{dayLabel(selectedHour.valid_at, result.timezone)} · {result.timezone}</span></div><TimeScrubber result={result} index={index} playing={playing} daylightIndex={daylightIndex} onChange={seek} onPlay={() => { cancelAction(); if (index >= result.hours.length - 1) setIndex(0); setPlaying(!playing) }} onAnalytics={() => openAnalytics()} /></>}
        {error && <div className="scene-error" role="alert"><Icon name="info" size={18} /><div><strong>Данные не получены</strong><p>{error}</p><button className="text-button" onClick={() => setSheet('settings')}>Изменить источник</button></div></div>}
        {result && insight && !actionNotice && <button className="forecast-insight" onClick={() => { seek(insight.index); setActionNotice(seekDescription(result, insight.index, 'ramp')) }}><span className="insight-mark">↘</span><span>Момент перемены<small>{hourLabel(result.hours[insight.index].valid_at, result.timezone)} · {signedPoints(insight.delta)} за час</small></span><Icon name="arrow" size={15} /></button>}
        {actionNotice && <div className="action-notice" role="status"><span>{actionNotice}</span><button className="icon-button" onClick={() => setActionNotice('')} aria-label="Скрыть подсказку"><Icon name="close" size={15} /></button></div>}
      </>}
      <footer className="world-footer"><span>{mode === 'fixture' ? 'СИНТЕТИЧЕСКАЯ ПОГОДА · РЕАЛЬНАЯ МОДЕЛЬ' : mode === 'live' ? 'ПОГОДА: OPEN-METEO · ВЕТЕР 10 М' : 'ПРОВЕРЯЕМЫЙ ИСТОРИЧЕСКИЙ ИСТОЧНИК'}</span>{mode === 'live' && <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">CC BY 4.0 ↗</a>}<button onClick={() => result ? openAnalytics('provenance') : setSheet('settings')}>О данных и сцене</button></footer>
    </main>
    <Assistant open={assistantOpen} onOpenChange={open => { if (open) setSheet(null); setAssistantOpen(open) }} phase={phase} context={assistantContext} explanation={explanation} explanationError={explanationError} messages={messages} pending={pendingQuestion} error={questionError} onCommand={text => void commandAssistant(text)} hasForecast={Boolean(result)} />
    <Sheet open={sheet === 'settings'} title="Ваш горизонт" subtitle="ПАРАМЕТРЫ ИССЛЕДОВАНИЯ" onClose={() => setSheet(null)} className="settings-sheet"><div className="settings-content"><p className="settings-lead">Выберите, на какой ветер смотреть.</p><label className="field"><span>Источник погоды</span><select value={mode} onChange={event => updateInputs(() => { const nextMode = event.target.value as WeatherMode; setMode(nextMode); if (nextMode === 'fixture' && date !== FIRST_DATE && date !== LAST_DATE) setDate(FIRST_DATE) })}><option value="live">Настоящий прогноз Open-Meteo</option><option value="fixture">Демонстрационная погода</option><option value="archive">Проверенный архив</option></select></label><p className="field-help">{mode === 'live' ? 'Текущий прогноз для реальных координат. Начало — следующий полный час; время выпуска определяет сервер.' : mode === 'fixture' ? 'Синтетическая погода. Два сохранённых запуска позволяют воспроизвести результат без погодного API.' : 'Требуется настроенный на сервере проверенный архив. Без подтверждения времени доступности расчёт завершится понятной ошибкой.'}</p>
      {mode !== 'live' && <label className="field"><span>Дата выпуска · 23:00 Asia/Almaty</span>{mode === 'fixture' ? <select value={date} onChange={event => updateInputs(() => setDate(event.target.value))}><option value={FIRST_DATE}>31 января 2026</option><option value={LAST_DATE}>1 февраля 2026</option></select> : <input type="date" value={date} onChange={event => updateInputs(() => setDate(event.target.value))} />}</label>}
      <div className="field"><span>Горизонт прогноза</span><div className="segment-control">{([24, 48] as const).map(value => <button key={value} className={horizon === value ? 'selected' : ''} aria-pressed={horizon === value} onClick={() => { if (value !== horizon) updateInputs(() => setHorizon(value)) }}>{value} {value === 24 ? 'часа' : 'часов'}</button>)}</div></div>
      <label className="field"><span>Турбина</span><select value={siteId} disabled={!sites.length} onChange={event => updateInputs(() => setSiteId(event.target.value))}>{sites.map(site => <option key={site.turbine_id} value={site.turbine_id}>{site.turbine_id} · {site.latitude.toFixed(4)}°, {site.longitude.toFixed(4)}°</option>)}</select></label>
      {siteError && <div className="error-banner" role="alert">{siteError}<button className="text-button" onClick={() => setSiteRetry(value => value + 1)}>Повторить загрузку турбин</button></div>}
      <button className="primary-button settings-submit" disabled={!siteId || !date || loading} onClick={() => { cancelAction(); setSheet(null); setView('turbine'); void runForecast({ siteId, date, horizon, mode }) }}>Сформировать прогноз<Icon name="arrow" size={17} /></button>
      <details className="appearance-settings"><summary>Вид сцены и доступность</summary><label className="field"><span>Качество графики</span><select value={quality} onChange={event => setQuality(event.target.value as Quality)}><option value="auto">Автоматически</option><option value="high">Высокое</option><option value="medium">Среднее</option><option value="low">Экономное</option></select></label><p className="data-note">{reducedMotion ? 'Сокращённая анимация включена настройкой устройства.' : 'Сокращённая анимация следует настройке устройства.'} Облачность и осадки API не передаёт. Рельеф и модель турбины иллюстративные; обороты показывают визуальную реакцию на прогнозный ветер.</p></details>
      <p className="data-note">Мощность нормализована. Операционный статус, реальные обороты и телеметрия SCADA недоступны. <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo · CC BY 4.0 ↗</a></p></div></Sheet>
    <Sheet open={sheet === 'analytics' && Boolean(result)} title={`Ветер и мощность · ${result?.turbine_id || ''}`} subtitle={result ? `${hoursLabel(result.horizon_hours).toLocaleUpperCase('ru')} · ${modeNames[result.mode].toLocaleUpperCase('ru')}` : ''} onClose={() => setSheet(null)} className="analytics-sheet">{result && <><p className="analysis-origin">Выпуск: {localTime(result.origin, result.timezone)}</p><Analytics result={result} previous={previous} site={selectedSite} index={index} tab={analyticsTab} onTab={setAnalyticsTab} onTime={seek} onDownload={kind => void saveCsv(kind)} downloadError={downloadError} onAdvance={mode === 'fixture' && date === FIRST_DATE ? () => { cancelAction(); setDate(LAST_DATE); void runForecast({ siteId, date: LAST_DATE, horizon, mode }); setSheet(null) } : undefined} /></>}</Sheet>
  </div>
}
