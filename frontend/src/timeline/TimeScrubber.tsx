import type { ForecastResult } from '../types'
import { percent } from '../ru'
import Icon from '../ui/Icon'
import { dayLabel, hourLabel, hoursLabel } from './format'
export { dayLabel, hourLabel } from './format'

export default function TimeScrubber({ result, index, playing, onChange, onPlay, onAnalytics, daylightIndex }: { result: ForecastResult, index: number, playing: boolean, onChange: (index: number) => void, onPlay: () => void, onAnalytics: () => void, daylightIndex: number | null }) {
  const hours = result.hours
  const selected = hours[index]
  const x = (i: number) => i * 1000 / Math.max(1, hours.length - 1)
  const path = hours.map((hour, i) => `${i ? 'L' : 'M'}${x(i)},${45 - hour.power_norm * 38}`).join(' ')
  const cursor = index / Math.max(1, hours.length - 1) * 100
  const labels = Array.from(new Set([0, Math.round((hours.length - 1) / 4), Math.round((hours.length - 1) / 2), Math.round((hours.length - 1) * .75), hours.length - 1]))
  return <section className="time-dock" aria-label="Время прогноза">
    <div className="time-dock-header"><div className="timeline-caption"><span className="eyebrow">Прогноз · {hoursLabel(result.horizon_hours)}</span><strong>{dayLabel(selected.valid_at, result.timezone)} <span>{hourLabel(selected.valid_at, result.timezone)}</span></strong></div>
      <div className="timeline-actions">{daylightIndex !== null && <button className="text-button daylight-preset" onClick={() => onChange(daylightIndex)} aria-label="Показать доступный дневной час прогноза" title="Перейти к дневному часу в этом прогнозе"><Icon name="sun" size={13} /><span>День</span></button>}<button className="text-button time-jump" onClick={() => onChange(Math.min(hours.length - 1, index + 6))}>+6 ч</button><button className="text-button time-jump" onClick={() => onChange(Math.min(hours.length - 1, index + 24))}>+24 ч</button><button className={`play-button ${playing ? 'is-playing' : ''}`} onClick={onPlay} aria-label={playing ? 'Остановить ход времени' : 'Воспроизвести прогноз во времени'} aria-pressed={playing}><Icon name={playing ? 'pause' : 'play'} size={15} /></button><button className="icon-button timeline-chart-link" onClick={onAnalytics} aria-label="Открыть график прогноза"><Icon name="chart" /></button></div>
    </div>
    <div className="scrubber-track">
      <svg viewBox="0 0 1000 50" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="timeline-fill" x1="0" x2="0" y1="0" y2="1"><stop stopColor="#dbba80" stopOpacity=".20" /><stop offset="1" stopColor="#dbba80" stopOpacity="0" /></linearGradient></defs><path d={`${path} L1000,50 L0,50 Z`} fill="url(#timeline-fill)" /><path d={path} fill="none" stroke="#d4b784" strokeWidth="1.7" vectorEffect="non-scaling-stroke" /></svg>
      <span className="scrubber-cursor" style={{ left: `${cursor}%` }} aria-hidden="true"><span /></span>
      <input type="range" min={0} max={hours.length - 1} step={1} value={index} onChange={event => onChange(Number(event.target.value))} aria-label="Выбранный час прогноза" aria-valuetext={`${dayLabel(selected.valid_at, result.timezone)}, ${hourLabel(selected.valid_at, result.timezone)}, мощность ${percent(selected.power_norm)}`} />
    </div>
    <div className="timeline-labels" aria-hidden="true">{labels.map((i, n) => <span key={i} className={n === 1 || n === 3 ? 'minor-time-label' : ''}>{hourLabel(hours[i].valid_at, result.timezone)}<small>{dayLabel(hours[i].valid_at, result.timezone)}</small></span>)}</div>
    <span className="timeline-zone">{result.timezone} · почасовой прогноз, не измерения</span>
  </section>
}
