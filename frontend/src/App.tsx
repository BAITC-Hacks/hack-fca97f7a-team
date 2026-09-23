import { useEffect, useRef, useState } from 'react'
import { CircleMarker, MapContainer, Popup, TileLayer, Tooltip } from 'react-leaflet'
import { askQuestion, createForecast, downloadUrl, explainForecast, getSites } from './api'
import type { Explanation, ForecastHour, ForecastRequest, ForecastResult, Site, WeatherMode } from './types'

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

function localTime(stamp: string): string {
  return new Intl.DateTimeFormat('ru-RU', { timeZone: LOCAL_ZONE, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(stamp))
}

const decimal = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
function pct(value: number): string { return `${decimal.format(value * 100)}%` }

const provenanceLabels: Record<string, string> = {
  run_id: 'Запуск погоды', provider: 'Поставщик погоды', source_url: 'Источник',
  initialized_at: 'Время выпуска', available_at: 'Время доступности',
  fetched_at: 'Время получения', availability_basis: 'Основание доступности',
  provenance_status: 'Статус происхождения', raw_sha256: 'Контрольная сумма ответа',
  forecast_sha256: 'Контрольная сумма прогноза', interpolation: 'Интерполяция',
  wind_height_m: 'Высота ветра, м', wind_height_status: 'Статус высоты ветра',
  grid_latitude: 'Широта сетки', grid_longitude: 'Долгота сетки',
}
const stepLabels: Record<string, string> = {
  validate_request: 'Проверка запроса', resolve_site: 'Выбор турбины', fetch_weather: 'Получение погоды',
  validate_weather: 'Проверка погоды', prepare_features: 'Подготовка признаков',
  write_model_input_csv: 'Создание входного CSV', load_model: 'Загрузка модели',
  predict_power: 'Расчёт мощности', analyze_result: 'Анализ результата', error: 'Ошибка',
}
const stepDetails: Record<string, string> = {
  'registered request shape and UTC origin': 'Проверены параметры запроса и время UTC',
  'organizer-supplied coordinates': 'Координаты предоставлены организаторами',
  'fixture coordinates': 'Условные координаты',
  'origin elapsed during retrieval': 'Начало прогноза наступило во время получения погоды',
  'weather received': 'Прогноз погоды получен',
  'availability, provenance and complete hourly coverage': 'Проверены доступность, происхождение и полнота почасовых данных',
  'same validated content': 'Ранее проверенный набор данных',
  'peak, minimum and clipping computed': 'Рассчитаны максимум, минимум и ограничения диапазона',
}
function stepDetail(detail: string): string {
  if (detail in stepDetails) return stepDetails[detail]
  if (/^\d+ finite wind and temperature pairs$/.test(detail)) return `${detail.split(' ')[0]} конечных пар значений ветра и температуры`
  if (/^\d+ normalized hourly predictions$/.test(detail)) return `${detail.split(' ')[0]} почасовых прогнозов нормализованной мощности`
  if (/^\d+ rows · /.test(detail)) return detail.replace(' rows · ', ' строк · ')
  if (/^transport attempt \d+: /.test(detail)) return detail.replace('transport attempt ', 'Попытка обращения к погодному сервису №')
  return detail // Неизвестный диагностический идентификатор сохраняется без изменения.
}
function stepStatus(status: string): string {
  return ({ ok: 'ГОТОВО', cached: 'ИЗ КЕША', retry: 'ПОВТОР', error: 'ОШИБКА' } as Record<string, string>)[status] ?? status
}
function provenanceValue(key: string, value: string | number | null): string {
  if (value === null) return 'Не указано'
  if (typeof value === 'number') return decimal.format(value)
  const labels: Record<string, string> = {
    live: 'текущий прогноз', fixture: 'демонстрационный', verified: 'проверено',
    response_received: 'по времени получения ответа', none: 'нет',
  }
  return ['provenance_status', 'availability_basis', 'interpolation'].includes(key) ? labels[value] ?? value : value
}

function errorMessage(error: unknown): string {
  if (error instanceof TypeError) return 'Не удалось связаться с сервером. Проверьте подключение и повторите попытку.'
  if (error instanceof Error) return error.message
  return 'Не удалось выполнить запрос. Повторите попытку.'
}

function PowerChart({ hours }: { hours: ForecastHour[] }) {
  const width = 940, height = 265, left = 42, right = 12, top = 12, bottom = 31
  const x = (i: number) => left + i * (width - left - right) / Math.max(1, hours.length - 1)
  const y = (v: number) => top + (1 - v) * (height - top - bottom)
  const line = (key: 'power_norm' | 'baseline_norm') => hours.map((h, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(h[key]).toFixed(1)}`).join(' ')
  return <div className="chart-wrap" role="img" aria-label="Почасовой прогноз нормализованной мощности и базовая модель">
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {[0, .25, .5, .75, 1].map(v => <g key={v}><line className="grid-line" x1={left} x2={width - right} y1={y(v)} y2={y(v)} /><text className="axis-label" x={left - 9} y={y(v) + 4} textAnchor="end">{Math.round(v * 100)}</text></g>)}
      <path className="baseline-line" d={line('baseline_norm')} />
      <path className="power-line" d={line('power_norm')} />
      {[0, Math.floor((hours.length - 1) / 2), hours.length - 1].map(i => <text key={i} className="axis-label" x={x(i)} y={height - 5} textAnchor={i === 0 ? 'start' : i === hours.length - 1 ? 'end' : 'middle'}>{localTime(hours[i].valid_at)}</text>)}
    </svg>
  </div>
}

function coordinateLabel(status: string): string {
  return status === 'organizer-supplied' ? 'Координаты предоставлены организаторами' : 'Условные координаты'
}

function SiteMap({ sites, selected, onSelect }: { sites: Site[], selected: string, onSelect: (id: string) => void }) {
  const center: [number, number] = sites.length ? [sites.reduce((sum, s) => sum + s.latitude, 0) / sites.length, sites.reduce((sum, s) => sum + s.longitude, 0) / sites.length] : [0, 0]
  const selectedSite = sites.find(s => s.turbine_id === selected)
  return <div className="map-frame">
    <MapContainer center={center} zoom={12} scrollWheelZoom={false} className="site-map" key={sites.map(s => `${s.turbine_id}-${s.latitude}-${s.longitude}`).join('-')}>
      <TileLayer attribution='&copy; участники <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      {sites.map(site => <CircleMarker key={site.turbine_id} center={[site.latitude, site.longitude]} radius={selected === site.turbine_id ? 13 : 11} pathOptions={{ color: selected === site.turbine_id ? '#184f45' : '#fff', fillColor: selected === site.turbine_id ? '#b4e86a' : '#266f62', fillOpacity: 1, weight: 3 }} eventHandlers={{ click: () => onSelect(site.turbine_id) }}>
        <Tooltip direction="top" offset={[0, -14]}>{site.turbine_id} · {coordinateLabel(site.coordinate_status)}</Tooltip>
        <Popup>{site.turbine_id} · {coordinateLabel(site.coordinate_status)}</Popup>
      </CircleMarker>)}
    </MapContainer>
    <span className="map-badge">{selectedSite ? coordinateLabel(selectedSite.coordinate_status) : 'Загрузка координат…'}</span>
  </div>
}

function Comparison({ current, previous }: { current: ForecastResult, previous: ForecastResult | null }) {
  if (!previous || previous.turbine_id !== current.turbine_id || previous.fingerprint === current.fingerprint) return null
  const prior = new Map(previous.hours.map(row => [row.valid_at, row]))
  const overlap = current.hours.filter(row => prior.has(row.valid_at))
  if (!overlap.length) return null
  const mean = overlap.reduce((sum, row) => sum + Math.abs(row.power_norm - prior.get(row.valid_at)!.power_norm), 0) / overlap.length
  const changed = overlap.filter(row => Math.abs(row.power_norm - prior.get(row.valid_at)!.power_norm) > 1e-12).length
  return <section className="panel comparison"><div className="section-title"><span className="eyebrow">СРАВНЕНИЕ ЗАПУСКОВ</span><h3>Что изменилось?</h3></div>
    <p>Изменилось {changed} из {overlap.length} общих часов. Среднее абсолютное изменение нормализованной мощности: <strong>{pct(mean)}</strong>.</p>
    <details><summary>Показать общие часы</summary><div className="table-scroll"><table><thead><tr><th>Местное время</th><th>Ранее</th><th>Сейчас</th><th>Разница</th></tr></thead><tbody>{overlap.map(row => <tr key={row.valid_at}><td>{localTime(row.valid_at)}</td><td>{pct(prior.get(row.valid_at)!.power_norm)}</td><td>{pct(row.power_norm)}</td><td>{decimal.format((row.power_norm - prior.get(row.valid_at)!.power_norm) * 100)} п. п.</td></tr>)}</tbody></table></div></details>
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
  const questionEpoch = useRef(0)
  const forecastController = useRef<AbortController | null>(null)
  const answerController = useRef<AbortController | null>(null)
  const lastSuccess = useRef<ForecastResult | null>(null)

  function invalidate() {
    requestEpoch.current += 1
    questionEpoch.current += 1
    forecastController.current?.abort()
    answerController.current?.abort()
    setResult(null); setPrevious(null); setExplanation(null); setAnswer(null); setQuestion('')
    setError(''); setExplanationError(''); setQuestionError(''); setLoading(false); setAsking(false)
  }

  useEffect(() => {
    const controller = new AbortController()
    setSites([]); setSiteId(''); setSiteError('')
    getSites(mode, controller.signal).then(loaded => {
      setSites(loaded)
      if (loaded.length) setSiteId(loaded[0].turbine_id)
      else setSiteError('Нет зарегистрированных турбин для выбранного режима.')
    }).catch(err => { if (!controller.signal.aborted) setSiteError(errorMessage(err)) })
    return () => controller.abort()
  }, [mode])

  async function runForecast(next: { siteId: string, date: string, horizon: 24 | 48, mode: WeatherMode }) {
    invalidate()
    const epoch = requestEpoch.current
    const controller = new AbortController()
    forecastController.current = controller
    setLoading(true)
    const input: ForecastRequest = { turbine_id: next.siteId, horizon_hours: next.horizon, mode: next.mode }
    if (next.mode !== 'live') input.origin = originForDate(next.date)
    try {
      const forecast = await createForecast(input, controller.signal)
      if (epoch !== requestEpoch.current) return
      if (forecast.status !== 'ok' || !forecast.forecast_id || !forecast.model_input || !forecast.hours?.length) throw new Error('Ответ прогноза неполный.')
      setPrevious(lastSuccess.current?.turbine_id === forecast.turbine_id && lastSuccess.current.mode === forecast.mode ? lastSuccess.current : null)
      lastSuccess.current = forecast
      setResult(forecast)
      setLoading(false)
      try {
        const prose = await explainForecast(forecast.forecast_id, controller.signal)
        if (epoch === requestEpoch.current) {
          if (prose.forecast_fingerprint !== forecast.fingerprint) throw new Error('Объяснение не соответствует этому прогнозу.')
          setExplanation(prose)
        }
      } catch (err) {
        if (epoch === requestEpoch.current && !controller.signal.aborted) setExplanationError(errorMessage(err))
      }
    } catch (err) {
      if (epoch === requestEpoch.current && !controller.signal.aborted) { lastSuccess.current = null; setError(errorMessage(err)); setLoading(false) }
    }
  }

  async function submitQuestion(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!result || !question.trim()) return
    answerController.current?.abort()
    const controller = new AbortController()
    answerController.current = controller
    const epoch = requestEpoch.current
    const answerEpoch = ++questionEpoch.current
    setAnswer(null); setQuestionError(''); setAsking(true)
    try {
      const response = await askQuestion(result.forecast_id, question.trim(), controller.signal)
      if (epoch === requestEpoch.current && answerEpoch === questionEpoch.current && !controller.signal.aborted) {
        if (response.forecast_fingerprint !== result.fingerprint) throw new Error('Ответ не соответствует этому прогнозу.')
        setAnswer(response)
      }
    } catch (err) {
      if (epoch === requestEpoch.current && answerEpoch === questionEpoch.current && !controller.signal.aborted) setQuestionError(errorMessage(err))
    } finally { if (epoch === requestEpoch.current && answerEpoch === questionEpoch.current && !controller.signal.aborted) setAsking(false) }
  }

  const selectedSite = sites.find(s => s.turbine_id === siteId)
  const origin = originForDate(date)
  const mean = result ? result.hours.reduce((sum, row) => sum + row.power_norm, 0) / result.hours.length : 0

  return <div className="app-shell">
    <header className="topbar"><div className="brand"><span className="brand-mark">◒</span><span>AEOLUS <small>LAB</small></span></div><div className="topbar-right"><span className="topbar-line" /><span>{mode === 'live' ? 'ПРОГНОЗ НА БУДУЩЕЕ' : 'ИСТОРИЧЕСКИЙ СЦЕНАРИЙ'}</span><span className="topbar-dot" /> ЛОКАЛЬНОЕ ДЕМО</div></header>
    <main>
      <div className="hero"><div><span className="eyebrow hero-kicker">ПРОГНОЗ ЭНЕРГИИ ВЕТРА / 01</span><h1>Мощность <em>в прогнозе.</em></h1><p>{mode === 'live' ? 'Реальная прогнозная погода Open-Meteo проходит через входной CSV и модель турбины. Это прогноз, а не измеренная погода.' : 'Изучайте почасовые прогнозы по истории турбин и выбранному источнику погоды.'}</p></div><div className="hero-side"><span className="hero-orbit">✳</span><span>ПОЧАСОВОЙ<br />ПРОГНОЗ</span></div></div>
      <div className="notice"><span className="notice-icon">i</span><span>{mode === 'fixture' ? 'Демонстрационная погода и условные координаты.' : mode === 'live' ? 'Текущий прогноз погоды Open-Meteo, не измерения и не подтверждённый исторический архив. Координаты предоставлены организаторами.' : 'Архивная погода допускается только при подтверждении доступности на историческую дату. Координаты предоставлены организаторами.'} Модели обучены на измерениях турбин. Мощность нормализована [0, 1], не МВт или МВт·ч.</span></div>
      <div className="workspace"><section className="panel setup-panel"><div className="section-title"><span className="eyebrow">01 / НАСТРОЙКА</span><h2>Выберите прогноз</h2><p>{mode === 'live' ? 'Выберите турбину и горизонт текущего прогноза.' : 'Выберите турбину и дату исторического сценария.'}</p></div>
        <div className="field-label">ЗАРЕГИСТРИРОВАННАЯ ТУРБИНА</div>
        <SiteMap sites={sites} selected={siteId} onSelect={id => { if (id !== siteId) { invalidate(); setSiteId(id) } }} />
        <div className="field-note">{selectedSite ? `${coordinateLabel(selectedSite.coordinate_status)}. Маркеры выбирают только зарегистрированные турбины; совпадение с инженерным расположением не подтверждено.` : 'Маркеры доступны после загрузки зарегистрированных турбин.'}</div>
        <label className="field"><span>Турбина</span><select aria-label="Турбина" value={siteId} onChange={e => { invalidate(); setSiteId(e.target.value) }} disabled={!sites.length}><option value="">Выберите турбину</option>{sites.map(site => <option key={site.turbine_id} value={site.turbine_id}>{site.turbine_id} · {coordinateLabel(site.coordinate_status)}</option>)}</select></label>
        {siteError && <div className="error-banner" role="alert">{siteError}</div>}
        <label className="field"><span>Источник погоды</span><select aria-label="Источник погоды" value={mode} onChange={e => { invalidate(); lastSuccess.current = null; setSites([]); setSiteId(''); setSiteError(''); setMode(e.target.value as WeatherMode) }}><option value="fixture">Демонстрационная погода (заглушка)</option><option value="live">Реальный прогноз Open-Meteo (сейчас)</option><option value="archive">Проверенный исторический архив</option></select></label>
        <div className="field-grid">{mode !== 'live' && <label className="field"><span>Дата исторического прогноза</span><input aria-label="Дата исторического прогноза" type="date" min={FIRST_DATE} value={date} onChange={e => { invalidate(); setDate(e.target.value) }} /></label>}<label className="field"><span>Горизонт</span><select aria-label="Горизонт" value={horizon} onChange={e => { invalidate(); setHorizon(Number(e.target.value) as 24 | 48) }}><option value={24}>24 часа</option><option value={48}>48 часов</option></select></label></div>
        <div className="origin-note">{mode === 'live' ? 'Начало прогноза назначит сервер: следующий полный час UTC после получения запроса.' : `Начало исторического прогноза: 23:00 (${selectedSite?.timezone || LOCAL_ZONE}) · ${origin} UTC`}</div>
        <button className="primary-button" disabled={!siteId || (mode !== 'live' && !date) || loading} onClick={() => runForecast({ siteId, date, horizon, mode })}>{loading ? 'Формируем прогноз…' : 'Сформировать прогноз'} <span>↗</span></button>
        {error && <div className="error-banner" role="alert">{error}</div>}
      </section>
      <section className="results-column"><div className="pipeline"><span>ПОГОДА</span><b>→</b><span>CSV</span><b>→</b><span>МОДЕЛЬ</span><b>→</b><span>ОБЪЯСНЕНИЕ</span></div>
        {!result && <div className="panel empty-state"><div className="empty-glyph">∿</div><span className="eyebrow">ОЖИДАНИЕ ПРОГНОЗА</span><h2>Почасовая мощность турбины</h2><p>Выберите турбину и сформируйте прогноз, чтобы увидеть график, погоду, входной CSV модели и объяснение.</p></div>}
        {result && <><section className="panel result-panel"><div className="result-heading"><div><span className="eyebrow">02 / РЕЗУЛЬТАТ ПРОГНОЗА</span><h2>Прогноз турбины {result.turbine_id}</h2><p>Начало: {localTime(result.origin)} ({result.timezone}) · {result.horizon_hours} ч · {result.mode === 'live' ? 'реальный прогноз погоды Open-Meteo' : result.mode === 'fixture' ? 'демонстрационная погода' : 'проверенный исторический прогноз'}</p></div><span className="status-pill">● ГОТОВО</span></div>
          {result.mode === 'live' && <div className="live-weather-note"><strong>Реальная прогнозная погода Open-Meteo</strong> · доступна на момент: {result.weather_provenance.available_at ? `${localTime(result.weather_provenance.available_at)} (${result.timezone})` : 'время не указано'} · ветер на высоте 10 м — прокси для неизвестной высоты датчика турбины, не измеренная погода. Почасовые прогнозные ветер и температура показаны в таблице ниже. Данные погоды: <a href="https://open-meteo.com/" target="_blank" rel="noopener noreferrer">Open-Meteo, CC BY 4.0 ↗</a>.</div>}
          <div className="metrics"><div><span>СРЕДНЯЯ МОЩНОСТЬ</span><strong>{pct(mean)}</strong><small>нормализованная мощность</small></div><div><span>МАКСИМУМ</span><strong>{pct(result.analysis.peak_power_norm)}</strong><small>{localTime(result.analysis.peak_at)} местное время</small></div><div><span>МИНИМУМ</span><strong>{pct(result.analysis.min_power_norm)}</strong><small>{localTime(result.analysis.min_at)} местное время</small></div></div>
          <div className="chart-header"><h3>Почасовой прогноз мощности</h3><div className="legend"><span><i className="legend-forecast" /> Прогноз</span><span><i className="legend-baseline" /> Базовая модель</span></div></div><PowerChart hours={result.hours} />
          <div className="actions"><a href={downloadUrl(result.forecast_id, 'forecast')} download>↓ Скачать прогноз CSV</a><a href={downloadUrl(result.forecast_id, 'model-input')} download>↓ Скачать входной CSV модели</a></div>
          <div className="model-input"><span className="eyebrow">ВХОДНОЙ CSV МОДЕЛИ / {result.model_input.schema_version}</span><div><strong>{result.model_input.filename}</strong><span>{result.model_input.row_count} строк · {result.model_input.columns.join(', ')}</span></div><code>{result.model_input.sha256}</code></div>
        </section>
        <section className="panel analysis-panel"><div className="section-title"><span className="eyebrow">03 / АНАЛИЗ</span><h3>Что показывает прогноз</h3></div>{explanation ? <><p className="prose">{explanation.text}</p><div className="explanation-meta">{explanation.backend === 'llm' ? `Объяснение ИИ${explanation.model ? ` · ${explanation.model}` : ''}` : 'Расчётное объяснение — ИИ недоступен'}</div>{explanation.warning && <div className="warning-banner">{explanation.warning}</div>}</> : explanationError ? <div className="warning-banner" role="alert">Объяснение недоступно: {explanationError}</div> : <p className="muted">Готовим объяснение…</p>}
          {result.analysis.warnings.length > 0 && <div className="analysis-warnings">{result.analysis.warnings.map(warning => <span key={warning}>• {warning}</span>)}</div>}
          <form className="question-form" onSubmit={submitQuestion}><label htmlFor="forecast-question">Задать вопрос по этому прогнозу</label><div><input id="forecast-question" value={question} onChange={e => { questionEpoch.current += 1; answerController.current?.abort(); setQuestion(e.target.value); setAnswer(null); setQuestionError(''); setAsking(false) }} placeholder="В какие шесть часов средняя мощность максимальна?" maxLength={500} /><button disabled={asking || !question.trim()}>{asking ? 'Ищем ответ…' : 'Задать вопрос ↗'}</button></div></form>
          {answer && <div className="answer"><span className="eyebrow">ОТВЕТ · {answer.backend === 'llm' ? 'ИИ' : 'РАСЧЁТНЫЙ ОТВЕТ'}</span><p>{answer.text}</p>{answer.warning && <div className="warning-banner">{answer.warning}</div>}</div>}{questionError && <div className="error-banner" role="alert">{questionError}</div>}
        </section>
        <Comparison current={result} previous={previous} />
        <section className="panel detail-panel"><details open={result.mode === 'live' ? true : undefined}><summary>Почасовые данные <span>{result.hours.length} строк</span></summary><div className="table-scroll"><table><thead><tr><th>Местное время</th><th>Час</th><th>Прогноз ветра, м/с</th><th>Прогноз температуры, °C</th><th>Мощность</th><th>Базовая модель</th></tr></thead><tbody>{result.hours.map(hour => <tr key={hour.valid_at}><td>{localTime(hour.valid_at)}</td><td>{hour.lead_hour}</td><td>{decimal.format(hour.wind_speed_ms)}</td><td>{decimal.format(hour.temperature_c)}</td><td>{pct(hour.power_norm)}</td><td>{pct(hour.baseline_norm)}</td></tr>)}</tbody></table></div></details><details><summary>Происхождение данных и этапы расчёта <span>{result.trace.length} этапов</span></summary><div className="provenance"><div><strong>Запуск погоды</strong><span>{result.run_id}</span></div><div><strong>Модель</strong><span>{result.model_id}</span></div><div><strong>Конец периода обучения</strong><span>{result.train_last_interval_start} UTC</span></div><div><strong>Ответ из кеша</strong><span>{result.cache_hit ? 'Да' : 'Нет'}</span></div>{Object.entries(result.weather_provenance).map(([key, value]) => <div key={key}><strong>{provenanceLabels[key] ?? key}</strong><span>{provenanceValue(key, value)}</span></div>)}</div><ol className="trace">{result.trace.map((step, i) => <li key={`${step.step}-${i}`}><span className={step.status === 'ok' || step.status === 'cached' ? 'trace-ok' : ''}>{stepStatus(step.status)}</span><strong>{stepLabels[step.step] ?? step.step}</strong><small>{stepDetail(step.detail)}</small></li>)}</ol></details></section>
        {mode !== 'live' && <button className="advance-button" onClick={() => { const advanced = nextDate(date); setDate(advanced); runForecast({ siteId, date: advanced, horizon, mode }) }}>Перейти на день вперёд и пересчитать <span>→</span></button>}
        </>}
      </section></div>
    </main><footer><span>AEOLUS LAB / {mode === 'live' ? 'ТЕКУЩИЙ ПРОГНОЗ' : 'ИСТОРИЧЕСКИЙ СЦЕНАРИЙ'}</span><span>ИЗМЕРЕНИЯ ТУРБИН · {mode === 'fixture' ? 'ДЕМОНСТРАЦИОННАЯ ПОГОДА' : mode === 'live' ? 'ПРОГНОЗ OPEN-METEO' : 'ПРОВЕРЕННЫЙ АРХИВ'} · НОРМАЛИЗОВАННАЯ МОЩНОСТЬ</span></footer>
  </div>
}
