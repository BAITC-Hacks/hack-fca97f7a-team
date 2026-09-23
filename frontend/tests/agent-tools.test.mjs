import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'

// Use the project's TypeScript compiler; no Node-specific TS build is required.
const compiled = new Map()
async function moduleUrl(relative, base = import.meta.url) {
  const url = new URL(relative, base).href
  if (compiled.has(url)) return compiled.get(url)
  let source = ts.transpileModule(await readFile(new URL(url), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
  }).outputText
  for (const match of [...source.matchAll(/from ['"]([^'"]+)['"]/g)]) {
    const dependency = match[1].startsWith('.') ? await moduleUrl(match[1], url) : import.meta.resolve(match[1])
    source = source.replace(match[0], `from '${dependency}'`)
  }
  const output = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
  compiled.set(url, output)
  return output
}
const { parseUICommand, selectForecastHour, tomorrowDate, localDate, explainSelectedHour, biggestDrop } = await import(await moduleUrl('../src/assistant/agentTools.ts'))

function forecast(origin = '2026-01-31T18:00:00Z', count = 48) {
  return { origin, timezone: 'Asia/Almaty', turbine_id: 'T2', hours: Array.from({ length: count }, (_, i) => ({
    valid_at: new Date(Date.parse(origin) + (i + 1) * 3600000).toISOString(), lead_hour: i + 1,
    wind_speed_ms: 6 + i * .1, temperature_c: -2, power_norm: .6,
  })) }
}

test('A cross-turbine minimum command retains both turbine and tomorrow scope', () => {
  assert.deepEqual(parseUICommand('Покажи турбину 2 завтра, когда мощность минимальна'), { turbineId: 'T2', intent: 'minimum', tomorrow: true })
  assert.deepEqual(parseUICommand('Show me Turbine 2 tomorrow when production is lowest'), { turbineId: 'T2', intent: 'minimum', tomorrow: true })
  assert.equal(parseUICommand('Покажи турбину 3').turbineId, 'T3', 'unknown IDs are passed to the registered-site guard instead of silently selecting T1')
})

test('Period statistics and follow-ups reach the stored-result backend instead of single-hour navigation', () => {
  for (const question of [
    'В какие шесть часов средняя мощность максимальна?',
    'Найди лучшие 4 часа подряд',
    'Покажи максимальную среднюю мощность за 4 часа',
    'Покажи лучшие четыре часа подряд',
    'Почему снизилось здесь?',
    'Какой ветер там?',
    'Сравни этот период со следующими четырьмя часами',
    'Насколько точен прогноз?',
    'Объясни график',
    'Удали все данные и измени модель',
  ]) assert.equal(parseUICommand(question).intent, 'question', question)
})

test('Explicit navigation retains local single-hour and panel controls', () => {
  assert.equal(parseUICommand('Покажи минимум').intent, 'minimum')
  assert.equal(parseUICommand('Перейди к максимуму').intent, 'maximum')
  assert.equal(parseUICommand('Покажи самое сильное падение').intent, 'ramp')
  assert.equal(parseUICommand('Открой график').intent, 'analytics')
  assert.equal(parseUICommand('Открой таблицу').intent, 'analytics')
  assert.equal(parseUICommand('Вернись к Земле').intent, 'earth')
  assert.equal(parseUICommand('Покажи турбину 1').intent, 'navigate')
  assert.equal(parseUICommand('Покажи завтра').intent, 'tomorrow')
})

test('Tomorrow is measured from the forecast origin in the turbine timezone, never the device clock or selected hour', () => {
  const result = forecast()
  result.hours[4].power_norm = .15
  result.hours[27].power_norm = .02
  assert.equal(localDate(result.origin, result.timezone), '2026-01-31')
  assert.equal(tomorrowDate(result), '2026-02-01')
  assert.equal(selectForecastHour(result, 'minimum', true), 4)
  assert.equal(selectForecastHour(result, 'minimum', false), 27)
  assert.equal(selectForecastHour(result, 'tomorrow', true), 0)
})

test('Incomplete tomorrow coverage cannot fabricate a time or fallback to a different day', () => {
  const sameDayOnly = forecast('2026-01-31T00:00:00Z', 6)
  assert.equal(selectForecastHour(sameDayOnly, 'minimum', true), null)
  assert.equal(selectForecastHour(sameDayOnly, 'ramp', true), null)
})

test('Ramps use adjacent actual forecast rows; a flat forecast does not raise a proactive warning', () => {
  const result = forecast()
  assert.equal(biggestDrop(result), null)
  result.hours[10].power_norm = .2
  result.hours[11].power_norm = .18
  assert.equal(selectForecastHour(result, 'ramp'), 10)
  assert.equal(biggestDrop(result).index, 10)
  assert.ok(Math.abs(biggestDrop(result).delta + .4) < 1e-10)
})

test('Here uses the selected forecast row and its preceding hour, with normalized units and explicit causal limits', () => {
  const result = forecast()
  result.hours[7].power_norm = .314
  result.hours[7].wind_speed_ms = 4.2
  const text = explainSelectedHour(result, 7)
  assert.match(text, /07:00/)
  assert.match(text, /31,4/)
  assert.match(text, /4,2 м\/с/)
  assert.match(text, /не доказывают причину/)
  assert.doesNotMatch(text, /МВт/)
})

const { daylightHour } = await import(await moduleUrl('../src/timeline/daylight.ts'))
const site = { turbine_id: 'T2', latitude: 43.643198, longitude: 78.538828, timezone: 'Asia/Almaty' }

test('Daylight shortcut chooses an existing near-noon forecast row on the selected local day', () => {
  const result = forecast()
  const selected = daylightHour(result, site, 0)
  assert.ok(selected >= 11 && selected <= 14)
  assert.equal(localDate(result.hours[selected].valid_at, result.timezone), '2026-02-01')
  assert.equal(daylightHour(result, site, selected), null, 'a daylight row needs no override or shortcut')
})

test('No daylight shortcut is invented when the available period contains only night', () => {
  assert.equal(daylightHour(forecast('2026-01-31T18:00:00Z', 3), site, 0), null)
})
