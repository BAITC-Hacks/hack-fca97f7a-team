export const ru = {
  title: 'Прогноз мощности · Исторический запуск',
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
  chatHint: 'Объяснение результата и вопросы по выбранному прогнозу.',
  questionHint: 'Ответы основаны на данных этого прогноза.',
  loadingHint: 'Получаем погодные данные и рассчитываем мощность.',
  replay: 'ИСТОРИЧЕСКИЙ ПРОГНОЗ', demo: 'ЛОКАЛЬНОЕ ДЕМО',
  kicker: 'ПРОГНОЗ ВЕТРОЭНЕРГИИ / 01', heroStart: 'Мощность', heroEnd: 'под прогнозом.',
  heroText: 'Исследуйте почасовой прогноз по измерениям турбин и погодным признакам. Сдвиньте дату запуска, чтобы сравнить результаты.',
  heroSide: 'ПОЧАСОВОЙ ПРОГНОЗ',
  notice: 'Погода демонстрационная. Модель обучена на измерениях турбин. Мощность нормализована от 0 до 1; значения на графике показаны в процентах этой шкалы.',
  configure: '01 / ПАРАМЕТРЫ', selectForecast: 'Настройка прогноза', selectHint: 'Выберите зарегистрированную турбину и дату запуска.',
  registeredTurbine: 'ЗАРЕГИСТРИРОВАННАЯ ТУРБИНА', coordinates: 'Координаты пользователя',
  mapHint: 'Координаты из предоставленных ссылок Google Maps.',
  turbine: 'Турбина', chooseTurbine: 'Выберите турбину', originDate: 'Дата запуска', horizon: 'Горизонт', hours24: '24 часа', hours48: '48 часов',
  live: 'Настоящая погода · сейчас', liveTime: 'Начало — следующий полный час. Время определяется сервером.', liveNotice: 'Настоящий прогноз Open-Meteo. Модель обучена на истории турбин; ветер 10 м — приближение. Мощность нормализована, не МВт.', weatherSource: 'Источник погоды', fixture: 'Демонстрационная погода', archive: 'Проверенный архив',
  calculating: 'Формируем прогноз…', predict: 'Сформировать прогноз',
  pipelineWeather: 'ПОГОДА', pipelineCsv: 'ВХОДНОЙ CSV', pipelineModel: 'МОДЕЛЬ', pipelineExplanation: 'ОБЪЯСНЕНИЕ',
  awaiting: 'ОЖИДАНИЕ ПРОГНОЗА', emptyTitle: 'Сформируйте первый прогноз', emptyText: 'Выберите турбину, дату и горизонт слева. Здесь появятся график мощности и основные показатели, ниже — анализ и чат.',
  result: '02 / РЕЗУЛЬТАТ ПРОГНОЗА', ready: '● ГОТОВО',
  meanPower: 'Средняя мощность', peakPower: 'Максимум', lowestPower: 'Минимум', normalized: 'нормализованная мощность',
  chart: 'Почасовая нормализованная мощность', forecast: 'Прогноз', baseline: 'Базовый прогноз',
  chartAria: 'Почасовой прогноз нормализованной мощности и базовый прогноз',
  downloadForecast: 'Скачать прогноз CSV', downloadInput: 'Скачать входной CSV', modelInput: 'Входные данные модели', rows: 'строк',
  analysis: '03 / АНАЛИЗ', analysisTitle: 'Анализ и чат', aiExplanation: 'Объяснение ИИ', computedExplanation: 'Расчётное объяснение — ИИ недоступен',
  explanationLoading: 'Готовим объяснение…', explanationUnavailable: 'Не удалось получить объяснение',
  askLabel: 'Вопрос по этому прогнозу', askPlaceholder: 'В какие шесть часов средняя мощность максимальна?', asking: 'Ищем ответ…', ask: 'Задать вопрос', answer: 'ОТВЕТ', ai: 'ИИ', computed: 'Расчётный ответ',
  comparison: 'Сравнение запусков', whatChanged: 'Что изменилось?', inspectOverlap: 'Посмотреть совпадающие часы',
  localHour: 'Местный час', previous: 'Ранее', current: 'Сейчас', change: 'Изменение',
  hourlyData: 'Почасовые данные', lead: 'Шаг', wind: 'Ветер, м/с', temperature: 'Температура, °C', power: 'Мощность',
  provenance: 'Происхождение данных и этапы расчёта', steps: 'этапов', weatherRun: 'Запуск погоды', model: 'Модель', trainingCutoff: 'Конец обучения', cached: 'Результат из кеша', yes: 'Да', no: 'Нет',
  advance: 'Следующий день и новый прогноз', footer: 'Время указано в часовом поясе Asia/Almaty. Доступны демонстрационные запуски 31 января и 1 февраля 2026 года.',
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
}
export const fieldLabel = (key: string) => fields[key] || key.replaceAll('_', ' ')
export const statusLabel = (status: string) => ({ ok: 'ГОТОВО', cached: 'ИЗ КЕША', retry: 'ПОВТОР', error: 'ОШИБКА' }[status] || status)
export const stepLabel = (step: string) => ({
  validate_request: 'Проверка запроса', resolve_site: 'Выбор турбины', fetch_weather: 'Получение погоды',
  validate_weather: 'Проверка погоды', prepare_features: 'Подготовка признаков', write_model_input_csv: 'Запись входного CSV',
  load_model: 'Загрузка модели', predict_power: 'Расчёт мощности', analyze_result: 'Анализ результата', error: 'Ошибка',
}[step] || step.replaceAll('_', ' '))
export const provenanceLabel = (value: string) => ({
  live: ru.live, fixture: ru.fixture, archive: ru.archive, synthetic: 'Условные', verified: 'Проверенные',
  'synthetic deterministic fixture': 'Детерминированная демонстрационная погода',
  'synthetic fixture schedule': 'Демонстрационное расписание', none: 'Нет',
}[value] || value)
export const coordinateLabel = (value: string) => ({ user_provided: ru.coordinates, verified: 'Проверенные координаты', fixture: 'Условные координаты' }[value] || 'Источник координат не указан')
export function provenanceValue(key: string, value: string, zone: string): string {
  if (key.endsWith('_at') && !Number.isNaN(Date.parse(value))) return localTime(value, zone)
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
  NOT_FOUND: 'Прогноз больше не доступен. Сформируйте его заново.',
  INVALID_REQUEST: 'Проверьте турбину, дату и горизонт, затем повторите запрос.',
  INVALID_INPUT: 'Проверьте турбину, дату и горизонт, затем повторите запрос.',
  WEATHER_UNAVAILABLE: 'Погода для выбранной даты недоступна. Выберите дату с демонстрационными данными или повторите позже.',
  DATA_INVALID: 'Входные данные прогноза не прошли проверку. Повторите запрос.',
  MODEL_INVALID: 'Модель вернула некорректные данные. Повторите запрос позже.',
  MODEL_UNAVAILABLE: 'Модель временно недоступна. Повторите запрос позже.',
  INTERNAL_ERROR: 'Сервис временно недоступен. Повторите запрос позже.',
  EXPLANATION_FAILED: 'Не удалось подготовить объяснение. Числовой прогноз доступен ниже.',
  HTTP_ERROR: 'Запрос не выполнен. Повторите попытку.',
  REQUEST_FAILED: 'Не удалось выполнить запрос. Повторите попытку.',
}
