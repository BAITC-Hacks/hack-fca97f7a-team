/** Drawing budget driven by forecast wind, never an estimate of gusts or bearing. */
export function windVisualProfile(wind: number | null | undefined, reduced = false, quality = 'high') {
  const speed = Number.isFinite(wind) ? Math.max(0, Math.min(22, wind!)) : 0
  const t = Math.max(0, Math.min(1, (speed - 2) / 10))
  const strength = t * t * (3 - 2 * t)
  const moving = !reduced && quality !== 'low' && speed > 2
  return {
    speed,
    strength: reduced ? 0 : strength,
    ribbons: moving ? Math.min(quality === 'medium' ? 16 : 24, Math.round(5 + strength * 19)) : 0,
    particles: moving ? Math.min(quality === 'medium' ? 104 : 192, Math.round(32 + strength * 160)) : 0,
    length: 0.038 + strength * 0.145,
    width: 0.00055 + strength * 0.001,
    opacity: moving ? 0.20 + strength * 0.40 : 0,
  }
}
