import type { CSSProperties } from 'react'

type Name = 'arrow' | 'back' | 'close' | 'globe' | 'play' | 'pause' | 'settings' | 'chart' | 'chat' | 'wind' | 'temperature' | 'download' | 'send' | 'check' | 'chevron' | 'sun' | 'info' | 'refresh'

const paths: Record<Name, React.ReactNode> = {
  arrow: <><path d="M5 12h14M13 6l6 6-6 6" /></>,
  back: <><path d="M19 12H5m6 6-6-6 6-6" /></>,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  globe: <><circle cx="12" cy="12" r="8.5" /><ellipse cx="12" cy="12" rx="4" ry="8.5" /><path d="M3.5 12h17M5 7.5h14M5 16.5h14" /></>,
  play: <path d="m8 5 11 7-11 7Z" />,
  pause: <><path d="M8 5v14M16 5v14" strokeWidth="3" /></>,
  settings: <><path d="M4 7h9m4 0h3M4 17h3m4 0h9" /><circle cx="15" cy="7" r="2" /><circle cx="9" cy="17" r="2" /></>,
  chart: <><path d="M4 4v16h16M7 14l4-5 4 3 5-7" /></>,
  chat: <><path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H8l-4 2v-5.5A7.5 7.5 0 0 1 4 7.5 7.5 7.5 0 0 1 20 11.5Z" /><path d="M8 10h8M8 14h5" /></>,
  wind: <><path d="M3 8h12a3 3 0 1 0-3-3M3 12h16a3 3 0 1 1-3 3M3 16h6a2 2 0 1 1-2 2" /></>,
  temperature: <><path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0Z" /><path d="M12 8v9" /></>,
  download: <><path d="M12 3v12m-5-5 5 5 5-5M4 16v4h16v-4" /></>,
  send: <><path d="m4 11 16-7-7 16-2-7-7-2Z" /><path d="m11 13 9-9" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  chevron: <path d="m8 4 8 8-8 8" />,
  sun: <><circle cx="12" cy="12" r="4" /><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6m0-11v1" /></>,
  refresh: <><path d="M20 5v5h-5M4 19v-5h5" /><path d="M5.4 8a7 7 0 0 1 11.5-3L20 10M4 14l3.1 5A7 7 0 0 0 18.6 16" /></>,
}

export default function Icon({ name, size = 20, style }: { name: Name, size?: number, style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" style={style}>{paths[name]}</svg>
}

export function BrandMark() {
  return <svg viewBox="0 0 32 32" width="30" height="30" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="1.2"><path d="M16 16C6 13 4 6 8 4c4-2 9 3 8 12Zm0 0c8-7 15-6 15-1 0 4-7 7-15 1Zm0 0c2 10-3 16-7 13-3-3-1-10 7-13Z" /></svg>
}
