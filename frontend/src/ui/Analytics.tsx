import type { ForecastResult, Site } from '../types'
import { coordinateLabel, decimal, fieldLabel, localTime, percent, provenanceValue, signedPoints, statusLabel, stepLabel, traceDetail, warningLabel } from '../ru'
import PowerChart from '../PowerChart'
import Icon from './Icon'
import { hoursLabel } from '../timeline/format'

export type AnalyticsTab = 'forecast' | 'table' | 'provenance'

function Comparison({ current, previous }: { current: ForecastResult, previous: ForecastResult | null }) {
  if (!previous || previous.turbine_id !== current.turbine_id || previous.mode !== current.mode || previous.fingerprint === current.fingerprint) return null
  const prior = new Map(previous.hours.map(row => [row.valid_at, row]))
  const overlap = current.hours.filter(row => prior.has(row.valid_at))
  if (!overlap.length) return null
  const mean = overlap.reduce((sum, row) => sum + Math.abs(row.power_norm - prior.get(row.valid_at)!.power_norm), 0) / overlap.length
  return <section className="comparison"><h3>Сравнение запусков</h3><p>{overlap.length} общих часов. Среднее абсолютное изменение — <strong>{percent(mean)}</strong> нормализованной мощности.</p><details><summary>Посмотреть совпадающие часы</summary><div className="table-scroll"><table><thead><tr><th>Местный час</th><th>Предыдущий запуск</th><th>Новый запуск</th><th>Изменение</th></tr></thead><tbody>{overlap.map(row => <tr key={row.valid_at}><td>{localTime(row.valid_at, current.timezone)}</td><td>{percent(prior.get(row.valid_at)!.power_norm)}</td><td>{percent(row.power_norm)}</td><td>{signedPoints(row.power_norm - prior.get(row.valid_at)!.power_norm)}</td></tr>)}</tbody></table></div></details></section>
}

const provenanceNames: Record<string, string> = { grid_latitude: 'Широта погодной сетки', grid_longitude: 'Долгота погодной сетки', latitude: 'Широта', longitude: 'Долгота', wind_height_m: 'Высота ветра, м', temperature_height_m: 'Высота температуры, м', weather_model: 'Погодная модель', forecast_sha256: 'Контрольная сумма прогноза', archive_evidence: 'Подтверждение архива' }

export default function Analytics({ result, previous, site, index, tab, onTab, onTime, onDownload, downloadError, onAdvance }: { result: ForecastResult, previous: ForecastResult | null, site: Site | null, index: number, tab: AnalyticsTab, onTab: (tab: AnalyticsTab) => void, onTime: (index: number) => void, onDownload: (kind: 'forecast' | 'model-input') => void, downloadError: string, onAdvance?: () => void }) {
  const mean = result.hours.reduce((sum, hour) => sum + hour.power_norm, 0) / result.hours.length
  return <div className="analytics-content">
    <div className="analytics-tabs" role="tablist" aria-label="Раздел анализа">{([['forecast', 'Прогноз'], ['table', 'По часам'], ['provenance', 'Источники и метод']] as const).map(([value, title]) => <button id={`tab-${value}`} key={value} role="tab" aria-selected={tab === value} aria-controls={`tabpanel-${value}`} onClick={() => onTab(value)}>{title}</button>)}</div>
    <div role="tabpanel" id={`tabpanel-${tab}`} aria-labelledby={`tab-${tab}`}>
      {tab === 'forecast' && <>
        <div className="analysis-stats"><div><span>Средняя мощность</span><strong>{percent(mean)}</strong></div><button onClick={() => onTime(result.hours.findIndex(hour => hour.valid_at === result.analysis.peak_at))}><span>Максимум <Icon name="arrow" size={14} /></span><strong>{percent(result.analysis.peak_power_norm)}</strong><small>{localTime(result.analysis.peak_at, result.timezone)}</small></button><button onClick={() => onTime(result.hours.findIndex(hour => hour.valid_at === result.analysis.min_at))}><span>Минимум <Icon name="arrow" size={14} /></span><strong>{percent(result.analysis.min_power_norm)}</strong><small>{localTime(result.analysis.min_at, result.timezone)}</small></button></div>
        <p className="data-note">Все значения — нормализованная мощность [0, 1], показанная в процентах. Это не МВт и не доля паспортной мощности.</p>
        <PowerChart result={result} selectedIndex={index} onSelectIndex={onTime} />
        <div className="download-row"><button className="secondary-button" onClick={() => onDownload('forecast')}><Icon name="download" size={16} />Скачать прогноз CSV</button><button className="text-button" onClick={() => onDownload('model-input')}>Входной CSV модели <Icon name="arrow" size={15} /></button></div>
        <Comparison current={result} previous={previous} />
        {onAdvance && <button className="advance-button" onClick={onAdvance}>Следующий день и новый прогноз <Icon name="arrow" /></button>}
      </>}
      {tab === 'table' && <><div className="table-heading"><p>{hoursLabel(result.hours.length)} · {result.timezone}</p><button className="text-button" onClick={() => onDownload('forecast')}><Icon name="download" size={15} />CSV</button></div><p className="data-note">Нажмите на время, чтобы открыть этот час в сцене. Показатели — прогноз, не телеметрия SCADA.</p><div className="table-scroll"><table><thead><tr><th>Местный час</th><th>Шаг, ч</th><th>Ветер, м/с</th><th>Температура, °C</th><th>Мощность, %</th></tr></thead><tbody>{result.hours.map((hour, i) => <tr key={hour.valid_at} className={i === index ? 'selected-row' : ''}><td><button className="table-time" onClick={() => onTime(i)} aria-pressed={i === index}>{localTime(hour.valid_at, result.timezone).replace(` (${result.timezone})`, '')}</button></td><td>{hour.lead_hour}</td><td>{decimal(hour.wind_speed_ms)}</td><td>{decimal(hour.temperature_c)}</td><td>{percent(hour.power_norm)}</td></tr>)}</tbody></table></div></>}
      {tab === 'provenance' && <>
        <div className="source-notice"><Icon name="info" /><p>{result.mode === 'live' ? 'Настоящий прогноз Open-Meteo. Ветер на высоте 10 м используется как приближение: соответствие высоте датчика или ротора не подтверждено.' : result.mode === 'fixture' ? 'Демонстрационная погода. Синтетические значения ветра и температуры позволяют воспроизвести всю цепочку расчёта.' : 'Исторический прогноз с проверкой времени доступности и происхождения. Архив не подменяется фактической погодой.'}</p></div>
        <h3>Что известно о сцене</h3><p className="data-note">Ветер и температура приходят из выбранного прогноза. Положение Солнца вычисляется по времени и координатам. Рельеф и вид турбины иллюстративные. Облачность, направление ветра, осадки, влажность, видимость и реальные обороты ротора не передаются API; они не выдаются за измерения. Вращение — ограниченная визуальная модель по скорости ветра.</p>
        {site && <div className="coordinate-source"><strong>{coordinateLabel(site.coordinate_status)}</strong><p>{site.latitude.toFixed(6)}° с. ш. · {site.longitude.toFixed(6)}° в. д.</p>{site.coordinate_source && <a href={site.coordinate_source} target="_blank" rel="noreferrer">Источник координат: Google Maps ↗</a>}</div>}
        <div className="model-input"><div><h3>Точный вход модели</h3><button className="secondary-button" onClick={() => onDownload('model-input')}><Icon name="download" size={16} />Скачать входной CSV</button></div><p>{result.model_input.row_count} строк · {result.model_input.schema_version}</p><code>{result.model_input.columns.join(', ')}</code><p className="file-hash">SHA-256: {result.model_input.sha256}</p></div>
        <h3>Ограничения</h3><ul className="analysis-warnings">{result.analysis.warnings.map(warning => <li key={warning}>{warningLabel(warning)}</li>)}<li>Значений, ограниченных диапазоном [0, 1]: {result.analysis.clipped_count}.</li><li>Операционный статус турбин, SCADA и калиброванный диапазон неопределённости недоступны.</li></ul>
        <details className="provenance-details"><summary>Метаданные и происхождение</summary><dl className="provenance"><div><dt>Запуск погоды</dt><dd>{result.run_id}</dd></div><div><dt>Модель</dt><dd>{result.model_id}</dd></div><div><dt>Последний интервал обучения</dt><dd>{localTime(result.train_last_interval_start, result.timezone)}</dd></div><div><dt>Результат из кеша</dt><dd>{result.cache_hit ? 'Да' : 'Нет'}</dd></div>{Object.entries(result.weather_provenance).map(([key, value]) => <div key={key}><dt>{provenanceNames[key] || fieldLabel(key)}</dt><dd>{value == null ? 'Неизвестно' : value === 'live_http_retrieval' ? 'Получение текущего прогноза по HTTP' : provenanceValue(key, String(value), result.timezone)}</dd></div>)}</dl></details>
        <details className="provenance-details"><summary>Фактически выполненные этапы · {result.trace.length}</summary><ol className="trace">{result.trace.map((step, i) => <li key={`${step.step}-${i}`}><span>{statusLabel(step.status)}</span><div><strong>{stepLabel(step.step)}</strong><small>{traceDetail(step.step, step.detail)}</small></div></li>)}</ol></details>
      </>}
    </div>
    {downloadError && <div className="error-banner" role="alert">{downloadError}</div>}
  </div>
}
