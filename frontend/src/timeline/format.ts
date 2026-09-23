export function hourLabel(stamp: string, zone: string) {
  return new Intl.DateTimeFormat('ru-RU', { timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date(stamp))
}

export function dayLabel(stamp: string, zone: string) {
  return new Intl.DateTimeFormat('ru-RU', { timeZone: zone, day: 'numeric', month: 'long' }).format(new Date(stamp))
}

export function hoursLabel(value: number): string {
  const remainder = value % 100
  const unit = remainder >= 11 && remainder <= 14 ? 'часов' : value % 10 === 1 ? 'час' : value % 10 >= 2 && value % 10 <= 4 ? 'часа' : 'часов'
  return `${value} ${unit}`
}
