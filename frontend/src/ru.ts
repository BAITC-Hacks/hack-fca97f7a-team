export const ru = {
  title: 'Прогноз мощности ветровых турбин',
  pageTitle: 'Прогноз мощности',
  pageSubtitle: 'Ветровые турбины · почасовой прогноз',
  resultTitle: 'Прогноз и показатели',
  chartAxis: 'Нормализованная мощность, %',
  chartExportError: 'Не удалось сохранить график. Повторите попытку или выберите SVG.',
  downloadChart: 'Скачать график', downloadPng: 'PNG', downloadSvg: 'SVG',
  mapLoading: 'Загрузка карты…', mapLabel: 'Расположение турбин', zoomIn: 'Приблизить', zoomOut: 'Отдалить',
  tilesUnavailable: 'Подложка карты недоступна',
  openMap: 'Открыть в Google Картах', chooseDate: 'Выберите дату запуска',
  technicalDetails: 'Данные и метод расчёта',
  analysisAuthor: 'Анализ прогноза', you: 'Вы',
  chatHint: 'Задавайте уточняющие вопросы по выбранному прогнозу. Новый прогноз начнёт новый диалог.',
  questionHint: 'Например: «Найди лучшие четыре часа подряд», затем «А какой там ветер?»',
  loadingHint: 'Получаем погодные данные и рассчитываем мощность.',
  replay: 'ИСТОРИЧЕСКИЙ ПРОГНОЗ', demo: 'ЛОКАЛЬНОЕ ДЕМО',
  kicker: 'ПРОГНОЗ ВЕТРОЭНЕРГИИ / 01', heroStart: 'Мощность', heroEnd: 'под прогнозом.',
  heroText: 'Исследуйте почасовой прогноз мощности по текущему прогнозу погоды.',
  heroSide: 'ПОЧАСОВОЙ ПРОГНОЗ',
  notice: 'Погода демонстрационная. Модель обучена на измерениях турбин. Мощность нормализована от 0 до 1; значения на графике показаны в процентах этой шкалы.',
  configure: '01 / ПАРАМЕТРЫ', selectForecast: 'Настройка прогноза', selectHint: 'Выберите зарегистрированную турбину и горизонт.',
  registeredTurbine: 'ЗАРЕГИСТРИРОВАННАЯ ТУРБИНА', coordinates: 'Координаты пользователя',
  mapHint: 'Координаты из предоставленных ссылок Google Maps.',
  turbine: 'Турбина', chooseTurbine: 'Выберите турбину', originDate: 'Дата запуска', horizon: 'Горизонт', hours24: '24 часа', hours48: '48 часов',
  live: 'Настоящая погода · сейчас', liveTime: 'Начало — следующий полный час. Время определяется сервером.', liveNotice: 'Текущий прогноз Open-Meteo ECMWF IFS. Модель обучена на погоде этого источника и измеренной мощности. Точность на 24–48 часов пока не подтверждена. Мощность нормализована, не МВт.', weatherSource: 'Источник погоды', fixture: 'Демонстрационная погода', archive: 'Проверенный архив',
  calculating: 'Формируем прогноз…', predict: 'Сформировать прогноз',
  refreshWeather: 'Обновить погоду и прогноз', refreshingWeather: 'Обновляем погоду…',
  weatherProvider: 'Источник погоды', weatherProviderUnknown: 'Не указан', weatherRetrieved: 'Погода получена', weatherRetrievalUnknown: 'Время получения не указано',
  cachedWeather: 'Погода из кеша',
  savedForecast: 'Сохранённый прогноз',
  savedForecastNotice: 'Показан ранее рассчитанный прогноз. Время получения погоды указано ниже. Чтобы получить актуальный прогноз, обновите погоду.',
  savedForecastUnavailable: 'Сохранённый прогноз больше не доступен. Сформируйте новый прогноз.',
  savedForecastLoadFailed: 'Не удалось открыть сохранённый прогноз. Повторите попытку позже или сформируйте новый.',
  openingSavedForecast: 'Открываем сохранённый прогноз…',
  loadExplanation: 'Получить объяснение',
  savedExplanationHint: 'Объяснение сохранённого прогноза загружается по запросу.',
  pipelineWeather: 'ПОГОДА', pipelineCsv: 'ВХОДНОЙ CSV', pipelineModel: 'МОДЕЛЬ', pipelineExplanation: 'ОБЪЯСНЕНИЕ',
  awaiting: 'ОЖИДАНИЕ ПРОГНОЗА', emptyTitle: 'Сформируйте первый прогноз', emptyText: 'Выберите турбину и горизонт слева. Здесь появятся график мощности и основные показатели, ниже — анализ и чат.',
  result: '02 / РЕЗУЛЬТАТ ПРОГНОЗА', ready: '● ГОТОВО',
  meanPower: 'Средняя мощность', peakPower: 'Максимум', lowestPower: 'Минимум', normalized: 'нормализованная мощность',
  chart: 'Почасовая нормализованная мощность', forecast: 'Прогноз',
  chartAria: 'Почасовой прогноз нормализованной мощности',
  downloadForecast: 'Скачать прогноз CSV', downloadInput: 'Скачать входной CSV', modelInput: 'Входные данные модели', rows: 'строк',
  analysis: '03 / АНАЛИЗ', analysisTitle: 'Анализ и чат', aiExplanation: 'Объяснение ИИ', computedExplanation: 'Расчётное объяснение — ИИ недоступен',
  explanationLoading: 'Готовим объяснение…', explanationUnavailable: 'Не удалось получить объяснение',
  askLabel: 'Вопрос по этому прогнозу', askPlaceholder: 'Найди лучшие четыре часа подряд', asking: 'Ищем ответ…', ask: 'Задать вопрос', answer: 'ОТВЕТ', ai: 'ИИ', computed: 'Расчётный ответ',
  calculationTable: 'Расчёт по данным прогноза', selectedPeriod: 'Выбранный период:', limitations: 'Ограничения прогноза', newConversation: 'Предыдущий диалог больше не доступен. Вопрос сохранён: отправьте его снова, чтобы начать новый диалог.',
  comparison: 'Сравнение запусков', whatChanged: 'Что изменилось?', inspectOverlap: 'Посмотреть совпадающие часы',
  localHour: 'Местный час', previous: 'Ранее', current: 'Сейчас', change: 'Изменение',
  hourlyData: 'Почасовые данные', lead: 'Шаг', wind: 'Ветер, м/с', temperature: 'Температура, °C', power: 'Мощность',
  provenance: 'Происхождение данных и этапы расчёта', steps: 'этапов', weatherRun: 'Запуск погоды', model: 'Модель', modelProfile: 'Профиль модели', profileEcmwf: 'Модель по данным Open-Meteo ECMWF IFS, ветер 10 м', profileMeasured: 'Модель по измерениям турбины', trainingWeather: 'Погода при обучении', retrospectiveTrainingWeather: 'Ретроспективный прогноз погоды', forecastAccuracy: 'Точность прогноза подтверждена', notVerified: 'Нет, не проверена', notSpecified: 'Не указано', trainingCutoff: 'Конец обучения', cached: 'Результат из кеша', yes: 'Да', no: 'Нет',
  advance: 'Следующий день и новый прогноз', footer: 'Время указано в часовом поясе Asia/Almaty. Погода поступает из текущего прогноза Open-Meteo.',
  noSites: 'Нет доступных зарегистрированных турбин.', noArchiveSites: 'Список турбин для архивного режима недоступен.',
  incompleteForecast: 'Ответ сервера не содержит полного прогноза.', staleExplanation: 'Объяснение относится к другому прогнозу.', staleAnswer: 'Ответ относится к другому прогнозу.', requestFailed: 'Не удалось завершить запрос.',
  originAt: 'Прогноз выпущен в 23:00', local: 'местного времени', utc: 'UTC',
  overlapping: 'совпадающих часов изменились. Среднее абсолютное изменение:', units: 'нормализованной мощности',
  pp: 'п. п.',
  networkError: 'Нет связи с сервером. Проверьте подключение и повторите запрос.',
  invalidServerResponse: 'Сервер вернул некорректный ответ. Повторите запрос.',
} as const

const number = new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 1, maximumFractionDigits: 1 })
export const percent = (value: number) => `${number.format(value * 100)} %`
export const decimal = (value: number) => number.format(value)
export const signedPoints = (value: number) => `${value >= 0 ? '+' : '−'}${number.format(Math.abs(value * 100))} ${ru.pp}`
export const localTime = (stamp: string, zone: string) => new Intl.DateTimeFormat('ru-RU', {
  timeZone: zone, day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
}).format(new Date(stamp)) + ` (${zone})`

const fields: Record<string, string> = {
  turbine_id: 'Турбина', run_id: 'Запуск', provider: 'Поставщик', source_url: 'Источник',
  initialized_at: 'Время выпуска', available_at: 'Время доступности', availability_basis: 'Основание доступности',
  retrieved_at: 'Время получения', provenance_status: 'Статус происхождения', raw_sha256: 'Контрольная сумма источника', interpolation: 'Интерполяция',
  coordinate_status: 'Статус координат',
  assumed_available_by: 'Предполагаемая доступность', availability_verified: 'Доступность подтверждена',
  run_policy: 'Правило выбора выпуска', documentation_url: 'Документация поставщика',
  forecast_date: 'Первый день прогноза', object_count: 'Число исходных объектов', provider_documentation: 'Документация источника',
  grid_resolution: 'Разрешение погодной сетки', grid_resolution_degrees: 'Разрешение сетки, градусы',
  source_step_hours: 'Исходный шаг прогноза, часы', publication_evidence: 'Подтверждение публикации',
  weather_model: 'Погодная модель', wind_height_m: 'Высота ветра, м',
  temperature_height_m: 'Высота температуры, м', wind_height_status: 'Смысл высоты ветра',
  grid_latitude: 'Широта погодной сетки', grid_longitude: 'Долгота погодной сетки',
  forecast_sha256: 'Контрольная сумма погодного прогноза',
}
export const fieldLabel = (key: string) => fields[key] || key.replaceAll('_', ' ')
export const statusLabel = (status: string) => ({ ok: 'ГОТОВО', cached: 'ИЗ КЕША', retry: 'ПОВТОР', error: 'ОШИБКА' }[status] || status)
export const stepLabel = (step: string) => ({
  validate_request: 'Проверка запроса', resolve_site: 'Выбор турбины', fetch_weather: 'Получение погоды',
  validate_weather: 'Проверка погоды', prepare_features: 'Подготовка признаков', write_model_input_csv: 'Запись входного CSV',
  load_model: 'Загрузка модели', predict_power: 'Расчёт мощности', analyze_result: 'Анализ результата', error: 'Ошибка',
}[step] || step.replaceAll('_', ' '))
export const provenanceLabel = (value: string) => ({
  linear: 'Линейная интерполяция', linear_3h_to_hourly: 'Линейная интерполяция с 3-часового на почасовой шаг',
  s3_last_modified: 'Время публикации копии в публичном архиве',
  operational_object_last_modified: 'Время публикации операционного объекта архива',
  provider_documented: 'Архив · доступность по допущению',
  provider_documented_conservative_24h: 'Документация поставщика; запас 24 часа',
  previous_day_00z_for_18z_origin: 'Выпуск 00:00 UTC предыдущего дня для расчёта в 18:00 UTC',
  external_capture_log: 'Внешний журнал публикации', reviewed_as_issued: 'Проверенный исторический выпуск',
  true: 'Да', false: 'Нет',
  live: ru.live, fixture: ru.fixture, archive: ru.archive, synthetic: 'Условные', verified: 'Проверенные',
  'synthetic deterministic fixture': 'Детерминированная демонстрационная погода',
  'synthetic fixture schedule': 'Демонстрационное расписание', none: 'Нет',
  provider_feature_not_sensor_measurement: 'Признак погодного провайдера; не измерение датчика турбины',
  live_http_retrieval: 'Получено текущим запросом API', ecmwf_ifs: 'ECMWF IFS', user_provided: ru.coordinates,
}[value] || value)
export const weatherProviderLabel = (value?: string) => value?.startsWith('Open-Meteo Forecast')
  ? 'Open-Meteo · ECMWF IFS'
  : value?.startsWith('Open-Meteo Single Runs') ? 'Open-Meteo · ECMWF IFS (архив)' : value || ru.weatherProviderUnknown
export const coordinateLabel = (value: string) => ({ user_provided: ru.coordinates, verified: 'Проверенные координаты', fixture: 'Условные координаты' }[value] || 'Источник координат не указан')
export function provenanceValue(key: string, value: string, zone: string): string {
  if ((key.endsWith('_at') || key === 'assumed_available_by') && !Number.isNaN(Date.parse(value))) return localTime(value, zone)
  return provenanceLabel(value)
}
export function warningLabel(warning: string): string {
  if (/[А-Яа-яЁё]/.test(warning)) return warning
  if (warning.includes('Real turbine training data; synthetic weather')) return 'Модель обучена на реальных данных турбины; погода демонстрационная.'
  if (warning.includes('Timezone and interval semantics assumed')) return 'Часовой пояс и начало интервалов исходных данных приняты по допущению.'
  const clipping = warning.match(/^(\d+) model predictions clipped/)
  if (clipping) return `${clipping[1]} прогнозных значений ограничены диапазоном от 0 до 1.`
  return 'Есть ограничение исходных данных. Подробности доступны в ответе API.'
}
export function traceDetail(step: string, detail: string): string {
  const known: Record<string, string> = {
    validate_request: 'Проверены параметры и время UTC', resolve_site: 'Выбрана зарегистрированная турбина',
    fetch_weather: 'Погода получена', validate_weather: 'Проверены время доступности, происхождение и полнота часов',
    prepare_features: 'Подготовлены значения ветра и температуры', write_model_input_csv: 'Создан входной CSV',
    load_model: 'Модель загружена', predict_power: 'Рассчитан почасовой прогноз', analyze_result: 'Рассчитаны максимум, минимум и ограничения',
  }
  return known[step] || (step === 'error' ? detail : 'Этап выполнен')
}

export const apiErrors: Record<string, string> = {
  ARCHIVE_UNAVAILABLE: 'Операционный архив ECMWF отсутствует или не прошёл проверку исторической публикации. Подготовьте архив на сервере и повторите расчёт.',
  REPLAY_UNAVAILABLE: 'Февральский архив отсутствует или не прошёл проверку. Проверьте комплект погоды на сервере.',
  NOT_FOUND: 'Прогноз больше не доступен. Сформируйте его заново.',
  CONVERSATION_NOT_FOUND: ru.newConversation,
  CONVERSATION_BUSY: 'Дождитесь ответа на предыдущий вопрос и повторите запрос.',
  INVALID_REQUEST: 'Проверьте турбину и горизонт, затем повторите запрос.',
  INVALID_INPUT: 'Проверьте турбину и горизонт, затем повторите запрос.',
  WEATHER_UNAVAILABLE: 'Текущий прогноз погоды недоступен. Повторите запрос позже.',
  DATA_INVALID: 'Входные данные прогноза не прошли проверку. Повторите запрос.',
  MODEL_INVALID: 'Модель вернула некорректные данные. Повторите запрос позже.',
  MODEL_UNAVAILABLE: 'Модель временно недоступна. Повторите запрос позже.',
  INTERNAL_ERROR: 'Сервис временно недоступен. Повторите запрос позже.',
  EXPLANATION_FAILED: 'Не удалось подготовить объяснение. Числовой прогноз доступен ниже.',
  HTTP_ERROR: 'Запрос не выполнен. Повторите попытку.',
  REQUEST_FAILED: 'Не удалось выполнить запрос. Повторите попытку.',
  REFRESH_FAILED: 'Не удалось обновить погоду. Повторите попытку.',
}
