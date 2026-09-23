import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'

// Compile the isolated, side-effect-free math modules with the project's own TS version.
// No browser, test-only framework, forecast endpoint, or paid API call is involved.
async function loadTypeScript(relative) {
  let source = await readFile(new URL(relative, import.meta.url), 'utf8')
  source = source.replace("from 'three'", `from '${import.meta.resolve('three')}'`)
  const javascript = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } }).outputText
  return import(`data:text/javascript;base64,${Buffer.from(javascript).toString('base64')}`)
}
const { weatherForHour, windSpeedToRotorSpeed, solarPosition, WeatherInterpolator } = await loadTypeScript('./weather.ts')
const { earthPoint, surfaceFrame, ScalarSpring, sphericalDirection, EARTH_RADIUS } = await loadTypeScript('../scene/geography.ts')
const site = { turbine_id: 'T1', latitude: 43.645150, longitude: 78.535604, timezone: 'Asia/Almaty', coordinate_status: 'user_provided' }
const hour = { valid_at: '2026-09-23T07:00:00Z', lead_hour: 1, wind_speed_ms: 0, temperature_c: 0, power_norm: 0, baseline_norm: 0 }

test('adapter preserves valid zero values and provenance; never invents unavailable observations', () => {
  const weather = weatherForHour(hour, site, undefined, 'live')
  assert.equal(weather.source, 'live')
  assert.equal(weather.temperature, 0)
  assert.equal(weather.windSpeed, 0)
  for (const field of ['cloudCover', 'precipitation', 'humidity', 'visibility', 'windDirection', 'weatherCode', 'rotorRPM']) assert.equal(weather[field], null)
  assert.equal(weatherForHour(null, site), null)
  assert.equal(weatherForHour({ ...hour, wind_speed_ms: NaN, temperature_c: Infinity }, site).windSpeed, null)
  assert.equal(weatherForHour(null, site, hour.valid_at).source, 'unavailable')
})

test('solar geometry uses real coordinates/UTC: local equinox noon versus midnight', () => {
  const noon = solarPosition('2026-09-23T07:00:00Z', site.latitude, site.longitude)
  const midnight = solarPosition('2026-09-23T19:00:00Z', site.latitude, site.longitude)
  assert.ok(noon.altitude > 40 * Math.PI / 180 && noon.altitude < 50 * Math.PI / 180)
  assert.ok(midnight.altitude < -40 * Math.PI / 180)
  assert.ok(noon.azimuth > Math.PI / 2 && noon.azimuth < Math.PI * 1.5)
  assert.throws(() => solarPosition('invalid', 43, 78))
})

test('rotor curve has cut-in, bounded nonlinear response, telemetry priority, and finite safeguards', () => {
  for (const value of [undefined, null, NaN, Infinity, -4, 0, 2]) assert.equal(windSpeedToRotorSpeed(value), 0)
  const speeds = [3, 5, 8, 12, 16].map(speed => windSpeedToRotorSpeed(speed))
  assert.ok(speeds.every((speed, i) => i === 0 || speed > speeds[i - 1]))
  assert.equal(windSpeedToRotorSpeed(100), windSpeedToRotorSpeed(16))
  assert.equal(windSpeedToRotorSpeed(12, 0), 0)
  assert.ok(Math.abs(windSpeedToRotorSpeed(0, 6) - Math.PI / 5) < 1e-12)
  assert.notEqual(speeds[2] - speeds[1], speeds[3] - speeds[2])
})

test('weather interpolation preserves rotor inertia and takes the short azimuth path', () => {
  const interpolation = new WeatherInterpolator()
  const weather = weatherForHour({ ...hour, wind_speed_ms: 14 }, site)
  interpolation.currentVisualState.sunAzimuth = 359 * Math.PI / 180
  interpolation.setTarget({ ...weather, sunPosition: { altitude: 0.4, azimuth: Math.PI / 180 } })
  interpolation.update(1 / 60)
  assert.ok(interpolation.currentVisualState.rotorSpeed > 0)
  assert.ok(interpolation.currentVisualState.rotorSpeed < windSpeedToRotorSpeed(14) * 0.05)
  assert.ok(interpolation.currentVisualState.sunAzimuth > 359 * Math.PI / 180)
  assert.equal(interpolation.currentVisualState.cloudCover, 0)
  const before = interpolation.currentVisualState.rotorSpeed
  interpolation.setTarget(null)
  interpolation.update(1 / 60)
  assert.ok(interpolation.currentVisualState.rotorSpeed > 0 && interpolation.currentVisualState.rotorSpeed < before)
})

test('registered points use a consistent tangent frame and retain the real T1/T2 separation', () => {
  const frame = surfaceFrame(site)
  assert.ok(Math.abs(frame.origin.length() - EARTH_RADIUS) < 1e-8)
  assert.ok(Math.abs(frame.east.dot(frame.up)) < 1e-10)
  assert.ok(frame.east.clone().cross(frame.up).distanceTo(frame.south) < 1e-10)
  const t2 = earthPoint(43.643198, 78.538828)
  const metres = t2.distanceTo(frame.origin) * 1000
  assert.ok(metres > 300 && metres < 360)
  const prime = earthPoint(0, 0)
  assert.equal(prime.x, EARTH_RADIUS)
  assert.ok(Math.abs(earthPoint(0, 90).z + EARTH_RADIUS) < 1e-8)
})

test('camera spring reverses from its presentation position and velocity without a jump', () => {
  const spring = new ScalarSpring(0, 1, 2.5)
  for (let i = 0; i < 30; i++) spring.step(1 / 60)
  const presentation = spring.value, velocity = spring.velocity
  spring.target = 0
  assert.equal(spring.value, presentation)
  assert.equal(spring.velocity, velocity)
  spring.step(1 / 60)
  assert.ok(Math.abs(spring.value - presentation) < 0.025)
  for (let i = 0; i < 360; i++) spring.step(1 / 60)
  assert.ok(Math.abs(spring.value) < 0.00001)
})

test('camera great-circle path arrives above the registered turbine and does not mutate endpoints', () => {
  const from = earthPoint(24, 44, 1), to = earthPoint(site.latitude, site.longitude, 1)
  const original = from.clone(), output = from.clone()
  sphericalDirection(from, to, 0, output)
  assert.ok(output.distanceTo(from) < 1e-10)
  sphericalDirection(from, to, 1, output)
  assert.ok(output.distanceTo(to) < 1e-10)
  assert.ok(from.distanceTo(original) < 1e-10)
  sphericalDirection(from, to, 0.5, output)
  assert.ok(Math.abs(output.length() - 1) < 1e-10)
  assert.ok(output.distanceTo(from) > 0.05 && output.distanceTo(to) > 0.05)
  sphericalDirection(from, from.clone().negate(), 0.5, output)
  assert.ok(Number.isFinite(output.x) && Math.abs(output.length() - 1) < 1e-10)
})
