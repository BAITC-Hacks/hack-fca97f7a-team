import { CircleMarker, MapContainer, TileLayer, Tooltip, ZoomControl } from 'react-leaflet'
import { useState } from 'react'
import type { Site } from './types'
import { ru } from './ru'

export default function SiteMap({ sites, selected, onSelect }: { sites: Site[], selected: string, onSelect: (id: string) => void }) {
  const [tilesUnavailable, setTilesUnavailable] = useState(false)
  if (!sites.length) return <div className="map-frame map-placeholder">{ru.mapLoading}</div>
  const bounds = sites.map(site => [site.latitude, site.longitude] as [number, number])
  return <div className="map-frame" aria-label={ru.mapLabel}>
    <MapContainer bounds={bounds} boundsOptions={{ padding: [48, 48], maxZoom: 16 }} scrollWheelZoom={false} zoomControl={false} className="site-map" key={JSON.stringify(bounds)}>
      <ZoomControl position="bottomright" zoomInTitle={ru.zoomIn} zoomOutTitle={ru.zoomOut} />
      <TileLayer attribution='&copy; участники <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" eventHandlers={{ tileerror: () => setTilesUnavailable(true), tileload: () => setTilesUnavailable(false) }} />
      {sites.map(site => <CircleMarker key={site.turbine_id} center={[site.latitude, site.longitude]} radius={selected === site.turbine_id ? 10 : 7} pathOptions={{ color: '#ffffff', fillColor: selected === site.turbine_id ? '#267054' : '#75877e', fillOpacity: 1, weight: 3 }} eventHandlers={{ click: () => onSelect(site.turbine_id) }}>
        <Tooltip permanent direction="top" offset={[0, -12]}>{site.turbine_id}</Tooltip>
      </CircleMarker>)}
    </MapContainer>
    {tilesUnavailable && <span className="map-status" role="status">{ru.tilesUnavailable}</span>}
  </div>
}
