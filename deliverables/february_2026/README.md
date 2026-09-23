# Февраль 2026 — результат расчёта

- `documented_forecast.csv`: 56 запусков × 48 часов = 2 688 строк.
- `documented_daily_forecast.csv`: первые 24 часа каждого запуска, по 672 часа февраля на T1/T2, всего 1 344 строки.
- `report.json`: модели, CSV-входы, погода, происхождение, полнота и ограничения.
- `replay_bundle.zip`: 177 файлов для повторного расчёта без сети — модели,
  погода, входы, результаты, README и манифест SHA-256. Код запускается из репозитория.
- `reproduction_check.json`: SHA-256 обоих результатов после переноса и повторного расчёта.

Результат основан на реальных отдельных выпусках Open-Meteo ECMWF IFS.
Доступность каждого исторического выпуска **предполагается** по консервативному
правилу (выпуск предыдущего дня 00 UTC, origin 18 UTC), а не подтверждена журналом.
Статус `provider_documented` сохранён в CSV. Фактическая мощность февраля
не предоставлена, поэтому точность не оценена. Полное покрытие вычислений
не означает доказанного полного соответствия историческому условию задания.

Из корня проекта с установленными зависимостями и совместимой версией
Python/scikit-learn из bundle_manifest.json (пакет создан на Python 3.14):

```sh
python -m zipfile -e deliverables/february_2026/replay_bundle.zip artifacts/february_bundle
ARTIFACT_DIR="$PWD/artifacts/february_bundle/artifacts" REPLAY_WEATHER_DIR="$PWD/artifacts/february_bundle/artifacts/replay_weather" python -m scripts.replay --weather-source provider-documented --output-dir artifacts/reproduced_february
cmp deliverables/february_2026/documented_forecast.csv artifacts/reproduced_february/documented_forecast.csv
cmp deliverables/february_2026/documented_daily_forecast.csv artifacts/reproduced_february/documented_daily_forecast.csv
```

Проверено: после переноса результаты совпали побайтно, 165 тестов прошли.
Новых платных вызовов OpenAI не было. Архив содержит локально обученные pickle-модели;
используйте доверенную копию репозитория.

Источник погодных данных: [Open-Meteo Single Runs](https://open-meteo.com/en/docs/single-runs-api),
ECMWF IFS, [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Подробности: [февральский расчёт](../../docs/february-replay.md).
