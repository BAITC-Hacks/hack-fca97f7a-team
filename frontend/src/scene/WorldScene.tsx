import { useEffect, useRef, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { Site } from '../types'
import type { NormalizedWeatherState, SceneQuality } from '../experience/types'
import { WorldRenderer } from './renderer'
import type { MarkerProjection } from './renderer'
import './scene.css'

export interface WorldSceneProps {
  sites: Site[]
  selectedSite: Site | null
  view: 'earth' | 'turbine'
  weather: NormalizedWeatherState | null
  onSelect: (id: string) => void
  quality?: SceneQuality
  reducedMotion?: boolean
  onViewChange?: (view: 'earth' | 'turbine') => void
  onReady?: () => void
}

const number = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 })

export default function WorldScene(props: WorldSceneProps) {
  const host = useRef<HTMLDivElement>(null)
  const renderer = useRef<WorldRenderer | null>(null)
  const latest = useRef(props)
  const markers = useRef(new Map<string, HTMLButtonElement>())
  const leaders = useRef(new Map<string, SVGLineElement>())
  const [failed, setFailed] = useState(false)
  const [ready, setReady] = useState(false)
  const [effectiveQuality, setEffectiveQuality] = useState('high')
  const [systemReduced, setSystemReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  const reducedMotion = props.reducedMotion ?? systemReduced
  latest.current = { ...props, reducedMotion }

  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
    const update = () => setSystemReduced(preference.matches)
    preference.addEventListener('change', update)
    return () => preference.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    if (!host.current) return
    const placeMarkers = (points: MarkerProjection[]) => {
      const visible = new Set(points.filter(point => point.visible).map(point => point.id))
      for (const [id, element] of markers.current) {
        const shown = visible.has(id)
        element.style.visibility = shown ? 'visible' : 'hidden'
        element.tabIndex = shown ? 0 : -1
        const leader = leaders.current.get(id)
        if (leader) leader.style.visibility = shown ? 'visible' : 'hidden'
      }
      for (const point of points) {
        if (!point.visible) continue
        const element = markers.current.get(point.id)
        if (element) element.style.transform = `translate3d(${point.x}px, ${point.y}px, 0)`
        const leader = leaders.current.get(point.id)
        if (leader) {
          leader.setAttribute('x1', String(point.anchorX)); leader.setAttribute('y1', String(point.anchorY))
          leader.setAttribute('x2', String(point.x)); leader.setAttribute('y2', String(point.y))
        }
      }
    }
    try {
      renderer.current = new WorldRenderer(host.current, {
        markers: placeMarkers,
        quality: setEffectiveQuality,
        fail: () => setFailed(true),
        ready: () => { setReady(true); latest.current.onReady?.() },
      })
      renderer.current.update(latest.current)
    } catch {
      setFailed(true)
      latest.current.onReady?.()
    }
    return () => { renderer.current?.dispose(); renderer.current = null }
  }, [])

  useEffect(() => { renderer.current?.update(latest.current) }, [props.sites, props.selectedSite, props.view, props.weather, props.quality, reducedMotion])

  function keyboard(event: KeyboardEvent<HTMLDivElement>) {
    if (event.target !== event.currentTarget) return
    switch (event.key) {
      case 'ArrowLeft': event.preventDefault(); renderer.current?.rotateBy(-1, 0); break
      case 'ArrowRight': event.preventDefault(); renderer.current?.rotateBy(1, 0); break
      case 'ArrowUp': event.preventDefault(); renderer.current?.rotateBy(0, -1); break
      case 'ArrowDown': event.preventDefault(); renderer.current?.rotateBy(0, 1); break
      case '+': case '=': event.preventDefault(); renderer.current?.zoomBy(-1); break
      case '-': event.preventDefault(); renderer.current?.zoomBy(1); break
      case 'Escape': props.onViewChange?.('earth'); break
    }
  }

  return <div className={`world-scene ${props.view === 'turbine' ? 'world-scene-local' : ''} ${failed ? 'world-scene-failed' : ''}`}
    data-quality={effectiveQuality} data-scene-ready={ready} data-motion={reducedMotion ? 'reduced' : 'full'}>
    <div ref={host} className="world-renderer" role="group" tabIndex={0} onKeyDown={keyboard}
      aria-label={props.view === 'earth' ? 'Интерактивная Земля. Перетаскивайте для вращения, используйте стрелки и плюс или минус для масштаба.' : 'Окружение турбины. Перетаскивайте для осмотра. Escape — вернуться к Земле.'} />
    {!failed && <div className="world-marker-layer">
      <svg className="world-marker-leaders" aria-hidden="true">{props.sites.map(site => <line key={site.turbine_id} ref={element => { if (element) leaders.current.set(site.turbine_id, element); else leaders.current.delete(site.turbine_id) }} />)}</svg>
      {props.sites.map(site => {
        const weather = site.turbine_id === props.selectedSite?.turbine_id ? props.weather : null
        return <button key={site.turbine_id} type="button" className={`world-marker ${site.turbine_id === props.selectedSite?.turbine_id ? 'world-marker-selected' : ''}`}
          ref={element => { if (element) markers.current.set(site.turbine_id, element); else markers.current.delete(site.turbine_id) }}
          aria-label={`Открыть турбину ${site.turbine_id}, ${site.latitude.toFixed(4)} градусов северной широты, ${site.longitude.toFixed(4)} градусов восточной долготы`}
          onClick={() => props.onSelect(site.turbine_id)}>
          <span className="world-marker-shape"><span className="world-marker-dot" /><strong>{site.turbine_id}</strong></span>
          <span className="world-marker-card"><b>Турбина {site.turbine_id}</b><span>{site.latitude.toFixed(4)}° N · {site.longitude.toFixed(4)}° E</span>
            {weather?.windSpeed != null ? <span>{number.format(weather.windSpeed)} м/с · {weather.temperature != null ? `${number.format(weather.temperature)} °C` : 'Температура недоступна'}</span> : <span>Выберите для загрузки прогноза</span>}
          </span>
        </button>
      })}
    </div>}
    {!failed && <div className="world-zoom" aria-label="Масштаб сцены">
      <button type="button" onClick={() => renderer.current?.zoomBy(-1)} aria-label="Приблизить">+</button>
      <span />
      <button type="button" onClick={() => renderer.current?.zoomBy(1)} aria-label="Отдалить">−</button>
    </div>}
    {failed && <div className="world-fallback" role="status">
      <div className="world-fallback-earth" aria-hidden="true" />
      <p>3D недоступно на этом устройстве.<br /><span>Выберите турбину в списке — прогноз и Samal доступны.</span></p>
    </div>}
    <div className="world-attribution">
      {props.view === 'earth' ? <a href="https://www.nasa.gov/nasa-brand-center/images-and-media/" target="_blank" rel="noreferrer">Земля · NASA<span className="world-attribution-detail"> Blue Marble</span></a> : <span>Сцена — иллюстрация<span className="world-attribution-detail"> · {props.weather ? 'солнце рассчитано по времени' : 'погода ещё не загружена'}</span></span>}
    </div>
  </div>
}
