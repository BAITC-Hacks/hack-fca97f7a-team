# Wind power forecast — React + FastAPI

Implementation backlog for three developers: [tasks.md](tasks.md). The active
React demo has a Russian user interface and Russian explanation fallback.

The active application is a React frontend with a FastAPI backend:

**Select turbine → weather tool → validated CSV → model reads CSV → predictions → OpenAI explanation.**

Both turbine models are trained from their separate real datasets. Fixture-mode weather is synthetic; all modes use user-supplied turbine coordinates.
Live mode fetches current Open-Meteo weather; historical archive eligibility remains unverified. OpenAI explanation and forecast
questions are real integrations, with an explicit computed fallback when the
key/provider is unavailable. Streamlit (`app.py`) is only the legacy prototype.

## Run the app

Requires Python **3.12+** (tested 3.14.4) and Node **22+**.

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m scripts.make_fixtures
python -m scripts.train --mode fixture
npm --prefix frontend ci
npm --prefix frontend run build
python -m uvicorn api:app --host 127.0.0.1 --port 8000
```

Open **http://localhost:8000**. FastAPI serves the built React app on the same
port; interactive API documentation is at **http://localhost:8000/docs**.

For frontend hot reload, keep FastAPI on port 8000 and run this in another terminal:

```sh
npm --prefix frontend run dev
```

Open http://localhost:5173; Vite proxies `/api` to FastAPI.

## OpenAI configuration

Copy `.env.example` to `.env` only if you do not already have a `.env`, then set:

```text
OPENAI_API_KEY=your-server-side-key
OPENAI_MODEL=gpt-5.4-mini
SUMMARY_BACKEND=llm
DATA_MODE=fixture
```

The current workspace already has the supplied key in ignored `.env` with
owner-only permissions. Environment variables take precedence over `.env`.
Never place keys in React, `VITE_` variables, Git or prompts. No NVIDIA adapter is
needed for this slice.

The backend uses the OpenAI Responses API with an 8-second timeout per call and no automatic
retries. Questions allow at most three API calls and four Python tool calls. Numeric forecasts appear first. Missing key, timeout or provider failure
returns a labeled local answer; it does not discard or change the forecast.

## Демонстрация за 2–3 минуты

1. Для воспроизводимого показа переключитесь с текущей погоды на «Демонстрационная погода», затем выберите
   турбину T1 или T2, 31 января 2026 года и горизонт 48 часов.
2. Нажмите **«Сформировать прогноз»**. Посмотрите график и почасовую таблицу.
3. Нажмите **«Скачать входной CSV модели»**: это точный файл, прочитанный моделью.
4. Прочитайте объяснение: подпись различает ответ OpenAI и расчётный вариант.
5. Спросите: «Найди лучшие четыре часа подряд», затем «А какой там ветер?»
   и «Сравни с последующими четырьмя часами». Сервер сохраняет выбранный
   период; Python рассчитывает средние значения, а чат показывает таблицу сравнения.
   Если следующих четырёх часов уже нет в горизонте, ответ сообщает об этом.
6. Нажмите **«Перейти на день вперёд и пересчитать»**, чтобы сравнить общие часы.
7. Для текущей погоды переключите «Источник погоды» на **«Реальный прогноз
   Open-Meteo (сейчас)»**, выберите T1/T2 и 24 или 48 часов, затем нажмите
   **«Сформировать прогноз»**. Дата здесь не выбирается: сервер задаёт ближайший
   будущий целый час UTC. Этот шаг требует доступности погодного API.

In **live** mode select the turbine and 24/48 hours; do not enter a date. The
server selects the next UTC hour after receipt and returns it as `origin`. A live
request needs network access and never falls back silently to fixtures. Open-Meteo
Forecast API (best match, 10 m wind) is **current** weather, not proof of any
historical as-issued run. Weather data: © Open-Meteo, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/);
the free API is for noncommercial use under Open-Meteo's terms. Attribution must
remain visible in the UI. Wind height differs from the unverified training sensor
height and power is normalized, not a capacity forecast.

1. Откройте приложение. Слева — карта с координатами пользователя и параметры, справа — прогноз, под ним — анализ и чат. Выберите T1 на карте или в списке, дату 31.01.2026 и горизонт «48 часов». Время запуска — 23:00 Asia/Almaty. Погода остаётся демонстрационной.
2. Нажмите **«Сформировать прогноз»**. Покажите график нормализованной мощности и раздел «Почасовые данные». Числовой результат появляется до объяснения.
3. Нажмите **«Скачать прогноз CSV»** в панели результата. Под графиком доступны **PNG** (2200 × 840) и **SVG** с датой, турбиной, часовым поясом и легендой. В разделе **«Данные и метод расчёта»** нажмите **«Скачать входной CSV»** — это точный файл, прочитанный моделью.
4. Покажите пометку «Объяснение ИИ» или «Расчётное объяснение — ИИ недоступен». Пройдите диалог: **«Найди лучшие четыре часа подряд» → «А какой там ветер?» → «Сравни с последующими четырьмя часами»**. Средние значения и таблицу вычисляет сервер по выбранному периоду.
5. Нажмите **«Следующий день и новый прогноз»**, затем покажите «Сравнение запусков» для совпадающих часов. Выберите T2 и повторите прогноз. При смене параметров предыдущий результат скрывается.
6. Для проверки ошибок выберите «Проверенный архив» и нажмите «Сформировать прогноз»: появится сообщение о недоступной погоде. Верните «Демонстрационная погода». При дате вне 31 января и 1 февраля приложение покажет понятную ошибку.

Сохранённая демонстрационная погода доступна только для 31 января и 1 февраля,
23:00 Asia/Almaty. Карта загружает тайлы из сети; турбину всегда можно выбрать
из списка. Режим архива заработает после подключения проверенной архивной
погоды. Повторный запуск сервера удаляет сохранённые ID прогнозов; сформируйте
прогноз заново.

Диалог хранится на сервере: последние 10 сообщений и выбранный период связаны с
ID прогноза и отдельным токеном разговора. Новый прогноз, даже с теми же параметрами,
начинает новый разговор. После вытеснения диалога чат предложит повторить вопрос.
Доступны лучшие/худшие N часов (отдельные либо подряд), средняя мощность за период,
ветер и температура по часам, сравнение периодов и поиск резких изменений мощности.
На «Когда лучше?» следует уточнение о длительности. Для МВт·ч нужна неизвестная
номинальная мощность установки. Контекст обучения берётся из метаданных модели;
совпадение падения ветра и мощности не выдаётся за доказанную физическую причину.

Проверка памяти и инструментов: 160 Python-тестов и сборка React прошли.
Диалог из трёх вопросов дополнительно пройден через API с локальной моделью T1
и синтетической погодой на 48 часов. Вызовы инструментов OpenAI проверены моками
SDK. В браузере с моками API проверены передача токена, таблицы, истечение диалога,
повторный прогноз с тем же ID и игнорирование запоздавшего ответа. Новых платных
вызовов OpenAI и запросов реальной погоды в этой проверке не было.

## The module seams

**Read [CONTRACTS.md](CONTRACTS.md) for exact HTTP routes, JSON, CSV schema,
Python signatures and instructions for replacing each component.**

| Owner | Modules | Replace/improve here |
|---|---|---|
| A — integration/weather | `api.py`, `agent.py`, `weather.py`, `contracts.py` | transport, orchestration, verified weather/site adapter |
| B — data/model | `data.py`, `model_input.py`, `model.py`, `scripts/train.py` | source ingestion, canonical CSV schema, fitting/inference, replay |
| C — UI/explanation | `frontend/`, `explanation.py` | React views, central API client/types, OpenAI prose/questions |

The CSV seam is **real inference input**, not an export fabricated afterward:

```csv
turbine_id,valid_at,wind_speed_ms,temperature_c
T2,2026-01-31T19:00:00Z,6.2,-4.0
```

`model_input.write_model_input` validates and atomically writes it to
`artifacts/model_inputs/<sha256>.csv`. `model.predict_power_csv` reads those bytes,
checks checksum/header/turbine/hour coverage, and runs inference in row order.
Forecast responses include schema version, checksum, row count and filename.
The HTTP download rechecks integrity. A trace shows CSV creation and prediction.

Predictions are stored server-side under a forecast ID; summary/question endpoints
accept that ID rather than client-authored predictions. In-memory stores retain
64 forecasts, so a server restart/eviction requires generating the forecast again.
Use one worker for this local demo. No database, queues or distributed services.

## Data and assumptions

Source CSVs and brief in `data/` remain unchanged. T1 has 142,360 records and T2
149,499. Both end January 31, 2026; February truth is absent despite filenames.

Assume ten-minute interval starts in Asia/Almaty. Drop/report ambiguous local
times and incomplete hours. Each retained hour averages six complete samples.
Zero-power observations are retained. Generated data/audits are under ignored
`data/canonical/`; models and inference CSVs are under ignored `artifacts/`.
The source hashes, clock exclusions and feature assumptions are recorded in
[DATA_MODEL_HANDOFF.md](DATA_MODEL_HANDOFF.md).

| Turbine | Complete hourly observations | Frozen training hours |
|---|---:|---:|
| T1 | 23,666 | 23,665 |
| T2 | 24,784 | 24,783 |

Training uses only completed hours at or before `2026-01-31T18:00:00Z`; its last
interval starts at 17:00 UTC. Predictions start at origin+1 hour. Models stay frozen
for the next origin; February labels/observed weather cannot enter the predictor.

Power is normalized [0,1], displayed as percentages in React—not MW/MWh. Capacity,
normalization denominator and source timestamp convention still need confirmation.
No farm total, calibrated uncertainty or accuracy claim without held-out truth.
Coordinates T1 (43.645150, 78.535604), T2 (43.643198, 78.538828)
are user-provided in all modes, not independent engineering identification. The
[Open-Meteo verification note](docs/open-meteo-verification.md) records actual
public endpoint probes, but those retrospective queries **do not prove**
as-issued availability at the historical origin. `OPEN_METEO_ARCHIVE_MANIFEST`
(optional, unset by default) must point to an operator-reviewed external capture
evidence manifest; see [CONTRACTS.md](CONTRACTS.md#weather-seam--a-owns-weatherpy)
for exact schema and fail-closed rules. No key is required by
the public endpoint. Responses must match the trusted capture's versioned canonical *full-forecast*
SHA-256 (not volatile raw JSON bytes). Exact retrieved bytes retain a separate
`raw_sha256` artifact checksum. Wind at 10 m from `ecmwf_ifs` is an explicit proxy; its mismatch against the
unknown height of training sensors requires B's review. Archive has no silent
fallback to demo fixtures. Without genuine historical evidence, retain fixture
mode for the demo and do not claim archive readiness.

## Validation

```sh
python -m pytest -q
npm --prefix frontend run build
python -m scripts.evaluate
```

The evaluation reports MAE/RMSE/R² for both turbines and 24/48-hour windows,
compared with origin-refreshed persistence. It uses future-hour *measured* wind
and temperature; see [EVALUATION_REPORT.md](EVALUATION_REPORT.md) before citing
the scores.

The Python suite and React TypeScript/Vite build cover
CSV consumption/integrity, chronology, source identities, input/output validation,
cache, HTTP/downloads, stored forecast context, summary fallback and legacy UI.
Tests clear OPENAI_API_KEY and mock SDK responses; they spend no API credits.
FastAPI TestClient needs local socket permissions in restricted environments.

One explicitly user-approved live test succeeded with `gpt-5.4-mini`: 24 generated
T2 weather rows → real CSV inference → LLM explanation, with no fallback. No raw
training CSV was sent. An earlier React browser smoke test used an empty key and
passed forecast rendering, 48-row model-input CSV download, a six-hour-window
question, next-day comparison, and the JavaScript error check (none).

The minimal Russian UI was also checked in Chromium with an empty OpenAI key:
T1/T2 × 24/48 hours, forecast/model-input CSV downloads, PNG (2200 × 840), SVG,
two-question chat history, real weather-unavailable errors and retry, input
invalidation, and a 390-pixel mobile viewport. Missing forecast IDs and delayed
explanations were simulated in the browser to check recovery and stale responses.
No JavaScript errors or paid OpenAI requests occurred.

## Remaining work

- Verify as-issued archived weather access for the user-supplied turbine coordinates.
- Implement February replay over all 28 daily origins and both turbines.
- Validate feature mismatch between measured training weather and forecast inputs.
- Confirm timezone/interval/normalization metadata; score only if truth is supplied.

The fixture scenario uses explicit synthetic weather at user-supplied locations;
live mode uses current Open-Meteo weather at those locations. The strict
historical archive remains unavailable without independent as-issued evidence.
This working demo is not a claim that the full organizer task is complete. See [AGENTS.md](AGENTS.md) for
working rules and [PLAN.md](PLAN.md) for current scope.

## Интеграция MLmodel

Обучение `python -m scripts.train --mode fixture` теперь также создаёт январскую
диагностику отдельно для T1/T2: `artifacts/training/T1_metrics.json` и
`T2_metrics.json`, плюс CSV с фактом и прогнозом. `--skip-validation` пропускает
только диагностику. Она использует измеренную погоду и не оценивает качество
реального прогноза погоды на 24/48 часов; baseline заморожен на весь январь.

Модели сохраняются в `artifacts/models/<турбина>/<хэш>/`, активные версии — в
`latest.json`. Старые локальные `T1.pkl`/`T2.pkl` читаются при отсутствии реестра;
переобучение переводит проект на новый формат. Внешний контракт
`load_model("T1")` и обязательный CSV-вход сохранены. После обучения:

```sh
python -m scripts.smoke_model --models-dir artifacts/models
```

Команда проверяет восемь синтетических сценариев через реальное чтение CSV.

Проверка объединённой ветки: 58 тестов, сборка React и 8 CSV smoke-сценариев прошли.
Январский MAE: T1 — 0,02373; T2 — 0,02592 (нормализованные доли, измеренная погода).

## Архивный адаптер Open-Meteo

Реализован Single Runs адаптер: проверяет единицы, почасовое покрытие,
происхождение и контрольные суммы; сохраняет сырой ответ. Координаты и ссылки
единые для fixture/archive. Погодные fixtures остаются синтетическими.

Архив закрыт по умолчанию: задайте `OPEN_METEO_ARCHIVE_MANIFEST` только после
проверки независимых свидетельств выпуска и доступности прогноза до origin.
Схема и граница доверия описаны в CONTRACTS.md; исследование источника —
в docs/open-meteo-verification.md. Успешный запрос исторической погоды сегодня
не доказывает её доступность в момент выпуска. Ветер 10 м — приближение,
соответствие датчику обучения и высоте ступицы пока не подтверждено.

Предыдущие проверки описаны выше; актуальный результат слияния следует проверять
отдельно. При слиянии живые запросы погоды/OpenAI не выполнялись.

## Настоящая погода — основной режим демо

Откройте http://localhost:8000, выберите T1/T2 и 24/48 часов, нажмите
«Сформировать прогноз». Режим «Настоящая погода · сейчас» включён по умолчанию.
Сервер получает свежий Open-Meteo Forecast по координатам турбины и подаёт
проверенный CSV модели. Дата определяется сервером, первые значения — со
следующего полного часа. Ключ Open-Meteo и архивный реестр не нужны.
Ошибка провайдера показывается явно; синтетической подмены нет.

Демонстрационная погода и исторический архив остаются отдельными режимами.
Ветер на 10 м — приближение; модель обучена до февраля 2026, качество текущего
прогноза ещё не оценено. Источник: https://open-meteo.com/ (CC BY 4.0).
