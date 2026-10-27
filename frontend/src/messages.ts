export type Locale = 'en' | 'ru';
export type LocalePreference = Locale | 'system';
type Plurals = { one: string; other: string; few?: string; many?: string };
export type MessageValues = Record<string, string | number>;

/** Keep product copy separate from verbatim Docker, model, and server content. */
const russian = {
  Language: 'Язык',
  System: 'Системный',
  'Container investigation': 'Диагностика контейнера',
  'Docker diagnostics': 'Диагностика Docker',
  'Configured host': 'Настроенный хост',
  'Loading hosts…': 'Загрузка хостов…',
  'No configured hosts': 'Нет настроенных хостов',
  'Connect a backend to begin': 'Подключите бэкенд для начала',
  'Retry hosts': 'Повторить загрузку хостов',
  Investigations: 'Расследования',
  'New investigation': 'Новое расследование',
  Containers: 'Контейнеры',
  'Refresh container inventory': 'Обновить список контейнеров',
  'Retry inventory': 'Повторить загрузку',
  'Reading Docker inventory…': 'Чтение списка контейнеров Docker…',
  'No containers on this host.': 'На этом хосте нет контейнеров.',
  'Sessions live in this tab.': 'Сессии хранятся в этой вкладке.',
  'Backend state is temporary.': 'Состояние бэкенда временное.',
  'About this workspace': 'Об этом пространстве',
  'Connect your API': 'Подключить свой API',
  'Return to demo': 'Вернуться в демо',
  'Skip to investigation': 'Перейти к расследованию',
  'Host and container inventory': 'Хосты и контейнеры',
  'Open host and containers': 'Открыть хосты и контейнеры',
  Workspace: 'Рабочее пространство',
  'Docker hosts': 'Хосты Docker',
  Demo: 'Демо',
  'API mode': 'Режим API',
  'Connect API': 'Подключить API',
  'Change connection': 'Изменить подключение',
  'Inventory observed {time} · snapshots, not a live feed': 'Список получен в {time} · снимок, не прямой эфир',
  'Docker diagnostics · host-scoped sessions': 'Диагностика Docker · сессии привязаны к хосту',
  'Ask DockSight': 'Спросить DockSight',
  'Simulated observations · no Docker changes': 'Пример наблюдений · без изменений в Docker',
  Scenario: 'Сценарий',
  'Demo scenario': 'Демо-сценарий',
  'Demo controls': 'Настройки демо',
  'Connection behavior': 'Поведение подключения',
  'Demo connection behavior': 'Подключение в демо',
  Normal: 'Обычное',
  'Turn fails after collection': 'Ошибка после сбора данных',
  'Connection unavailable': 'Нет подключения',
  'Empty inventory': 'Пустой список контейнеров',
  'Action outcome': 'Результат действия',
  'Demo action outcome': 'Результат действия в демо',
  Succeeded: 'Успешно',
  Failed: 'Ошибка',
  Indeterminate: 'Результат не подтверждён',
  Expired: 'Срок истёк',
  '200 log lines': '200 строк логов',
  'Retry connection': 'Повторить подключение',
  'Host & containers': 'Хосты и контейнеры',
  'Could not load configured hosts. Check the API endpoint, bearer token, and CORS.':
    'Не удалось загрузить хосты. Проверьте адрес API, Bearer-токен и CORS.',
  'Could not read Docker inventory.': 'Не удалось прочитать список контейнеров Docker.',
  'Crash loop': 'Цикл перезапусков',
  'Out of memory': 'Нехватка памяти',
  'Dependency unavailable': 'Недоступная зависимость',
  'Truncated logs': 'Обрезанные логи',
  'Unconfirmed exit': 'Неизвестная причина выхода',
  'Running / zero CPU': 'Работает / CPU равен нулю',
  'DockSight gathers read-only Docker observations and returns a model explanation with typed cards. The backend decides permitted operations.':
    'DockSight собирает наблюдения Docker без изменений и возвращает объяснение модели с типизированными карточками. Разрешённые операции определяет бэкенд.',
  'Conclusions are interpretations. Cards and the evidence trail show the observed facts and their UTC timestamps.':
    'Выводы — это интерпретации. Карточки и источники показывают наблюдаемые факты и время в UTC.',
  "Changing hosts starts a separate session. Conversations are held in this tab's memory; the API has no past-dialogue listing. Backend sessions and actions disappear after a restart or expiry.":
    'При смене хоста начинается отдельная сессия. Диалоги хранятся в памяти вкладки; API не предоставляет список прошлых диалогов. Сессии и действия бэкенда исчезают после перезапуска или истечения срока.',
  'All current observations are fixture-based examples. Connect an API for real Docker evidence.':
    'Все текущие наблюдения — примеры на основе тестовых данных. Подключите API для получения данных Docker.',
  'Your bearer token is held only in this tab’s memory and is discarded when you disconnect or reload.':
    'Bearer-токен хранится только в памяти вкладки и удаляется при отключении или перезагрузке.',
  'Connect to DockSight': 'Подключение к DockSight',
  'Use your DockSight backend and its configured Docker hosts.':
    'Используйте свой бэкенд DockSight и настроенные в нём хосты Docker.',
  'API base URL': 'Базовый адрес API',
  'Bearer token': 'Bearer-токен',
  Cancel: 'Отмена',
  Connect: 'Подключить',
  Close: 'Закрыть',
  'Close dialog': 'Закрыть диалог',
  'Use HTTPS, or HTTP on localhost.': 'Используйте HTTPS или HTTP на localhost.',
  'The API base must end in /api/v1 and contain no credentials or query.':
    'Адрес API должен заканчиваться на /api/v1 и не содержать учётные данные или параметры запроса.',
  'Enter a bearer token.': 'Введите Bearer-токен.',
  'Check the API endpoint.': 'Проверьте адрес API.',
  'The local Vite proxy forwards /api to 127.0.0.1:8000. A remote API must allow this browser origin through CORS.':
    'Локальный прокси Vite направляет /api на 127.0.0.1:8000. Удалённый API должен разрешать источник этой страницы через CORS.',
  "Kept only in this tab's memory. Refreshing disconnects the API and returns to demo.":
    'Хранится только в памяти вкладки. Перезагрузка отключает API и возвращает в демо.',
  '{count} turns in this tab session': {
    one: '{count} запрос в сессии вкладки',
    few: '{count} запроса в сессии вкладки',
    many: '{count} запросов в сессии вкладки',
    other: '{count} запроса в сессии вкладки',
  },
  Operator: 'Оператор',
  'Diagnostic progress': 'Ход диагностики',
  'Reading container inventory': 'Чтение списка контейнеров',
  'Inspecting container state': 'Проверка состояния контейнера',
  'Reading container logs': 'Чтение логов контейнера',
  'Measuring CPU and memory': 'Замер CPU и памяти',
  'Reading allowlisted environment': 'Чтение разрешённых переменных',
  'Reading stack context': 'Чтение состава стека',
  'Read tool: {tool}': 'Инструмент чтения: {tool}',
  ' · simulated': ' · имитация',
  'Following the evidence': 'Собираем доказательства',
  'Collecting read-only Docker observations. Cards arrive with the validated answer.':
    'Собираем наблюдения Docker без изменений. Карточки появятся вместе с проверенным ответом.',
  'Model explanation': 'Объяснение модели',
  'Diagnostic conclusion': 'Вывод диагностики',
  'Cause uncertain': 'Причина не установлена',
  'The collected observations do not establish a definitive cause.':
    'Собранных наблюдений недостаточно для однозначного определения причины.',
  'Trace the evidence': 'Перейти к доказательствам',
  'View log evidence': 'Открыть логи как доказательство',
  'View container evidence': 'Открыть данные контейнера',
  'Log evidence': 'Логи как доказательство',
  'Container evidence': 'Данные контейнера',
  'No supporting evidence returned': 'Подтверждающие наблюдения не получены',
  'Diagnostic interruption': 'Прерывание диагностики',
  'Diagnosis stopped': 'Диагностика остановлена',
  'Diagnosis could not finish': 'Не удалось завершить диагностику',
  'Collection was cancelled. Submit again when you are ready.':
    'Сбор данных отменён. Когда будете готовы, отправьте запрос снова.',
  ' · Request {id}': ' · Запрос {id}',
  'Retry diagnosis': 'Повторить диагностику',
  'Start an investigation': 'Начните расследование',
  'Ask what happened on {host}. DockSight will gather observations before explaining them.':
    'Спросите, что произошло на хосте {host}. DockSight соберёт наблюдения и затем объяснит их.',
  'a configured host': 'из настроек',
  'Which containers need attention, and why?': 'Какие контейнеры требуют внимания и почему?',
  'Check this host': 'Проверить хост',
  'Continue the investigation': 'Продолжить расследование',
  'What else should we check?': 'Что ещё нужно проверить?',
  'Why did this container exit?': 'Почему завершился этот контейнер?',
  'Select a host': 'Выберите хост',
  ' · Read-only diagnosis': ' · Диагностика без изменений',
  'Stop diagnosis': 'Остановить диагностику',
  Investigate: 'Исследовать',
  'Ctrl / ⌘ + Enter to send': 'Ctrl / ⌘ + Enter — отправить',
  'Runtime evidence': 'Данные Docker',
  'Server observations': 'Наблюдения сервера',
  'No UI cards were returned for this answer.': 'В этом ответе нет карточек.',
  'Evidence and context': 'Доказательства и контекст',
  'Evidence trail': 'Источники наблюдений',
  '{count} references': {
    one: '{count} источник',
    few: '{count} источника',
    many: '{count} источников',
    other: '{count} источника',
  },
  'Inspect {kind} observation {count}': 'Наблюдение {count}: {kind}',
  State: 'Состояние',
  Logs: 'Логи',
  Env: 'Переменные',
  Metrics: 'Метрики',
  Stack: 'Стек',
  'Container status': 'Состояние контейнера',
  'Container logs': 'Логи контейнера',
  'Stack context': 'Состав стека',
  Environment: 'Окружение',
  'View {name} source': 'Источник: {name}',
  Source: 'Источник',
  'Exit code': 'Код выхода',
  'OOM killed': 'Убит из-за OOM',
  Yes: 'Да',
  No: 'Нет',
  Restarts: 'Перезапуски',
  CPU: 'CPU',
  Memory: 'Память',
  Unavailable: 'Недоступно',
  'No permitted actions': 'Нет разрешённых действий',
  'Review stop': 'Проверить остановку',
  'Review restart': 'Проверить перезапуск',
  '{count} lines returned': {
    one: 'Получена {count} строка',
    few: 'Получены {count} строки',
    many: 'Получено {count} строк',
    other: 'Получено {count} строки',
  },
  'Truncated · partial evidence': 'Логи обрезаны · данные неполные',
  'Within requested bounds': 'В пределах запроса',
  'Timestamped container logs': 'Логи контейнера с временными метками',
  'No time': 'Нет времени',
  'No log entries returned. An empty log does not establish the cause.':
    'Строки логов не получены. Пустые логи не объясняют причину.',
  'Docker logs · sanitized text': 'Логи Docker · очищенный текст',
  'Earlier or later output may be missing': 'Начало или конец вывода могут отсутствовать',
  'Docker Compose': 'Docker Compose',
  'Docker Swarm': 'Docker Swarm',
  '{running} of {total} running': 'Работают {running} из {total}',
  'No stacks in this observation.': 'В этом наблюдении нет стеков.',
  'Allowlisted variables · read only': 'Разрешённые переменные · только чтение',
  'No allowlisted variables returned.': 'Разрешённые переменные не получены.',
  Observation: 'Наблюдение',
  'Evidence observation': 'Наблюдение-источник',
  'Observed fact': 'Наблюдаемый факт',
  Host: 'Хост',
  Container: 'Контейнер',
  'Host scope': 'Весь хост',
  Observed: 'Время наблюдения',
  'Docker inspect': 'Проверка Docker',
  'Docker logs': 'Логи Docker',
  'Docker stats': 'Метрики Docker',
  'Docker stack inventory': 'Список стеков Docker',
  'Allowlisted environment': 'Разрешённые переменные окружения',
  'Inspect observation data': 'Посмотреть данные наблюдения',
  'Select an evidence reference to inspect its source and observation.':
    'Выберите источник, чтобы посмотреть происхождение и данные наблюдения.',
  prepared: 'ожидает подтверждения',
  running: 'работает',
  succeeded: 'успешно',
  failed: 'ошибка',
  expired: 'срок истёк',
  indeterminate: 'результат не подтверждён',
  created: 'создан',
  paused: 'приостановлен',
  restarting: 'перезапускается',
  removing: 'удаляется',
  exited: 'завершён',
  dead: 'неработоспособен',
  completed: 'завершён',
  stopped: 'остановлен',
  'Stop container': 'Остановить контейнер',
  'Restart container': 'Перезапустить контейнер',
  stop: 'остановка',
  restart: 'перезапуск',
  'Confirm stop': 'Подтвердить остановку',
  'Confirm restart': 'Подтвердить перезапуск',
  'Retry confirmed stop': 'Повторить подтверждённую остановку',
  'Retry confirmed restart': 'Повторить подтверждённый перезапуск',
  'Demo operation · no Docker mutation': 'Демо-действие · без изменений в Docker',
  'The container will stop serving its workload.': 'Остановка прервёт работу контейнера.',
  'The container will be interrupted and started again.':
    'Работа контейнера будет прервана, затем он будет запущен снова.',
  'Exact target below': 'Точная цель указана ниже',
  'Exact container ID': 'Точный ID контейнера',
  Expires: 'Срок действия',
  'Prepared action ID': 'ID подготовленного действия',
  'Check existing action': 'Проверить это действие',
  'Checking delivery…': 'Проверяем выполнение…',
  'The Docker result is not confirmed. Inspect Docker directly. This mutation cannot be repeated automatically; the target is fenced by the backend.':
    'Результат Docker не подтверждён. Проверьте Docker напрямую. Автоматически повторять операцию нельзя; бэкенд блокирует изменения этой цели.',
  'These cards remain historical observations. Run a new diagnosis to observe the current container state.':
    'В карточках сохранены исходные наблюдения. Запустите новую диагностику, чтобы получить текущее состояние контейнера.',
  'This action has expired. Run a new diagnosis to obtain a fresh server-prepared action.':
    'Срок действия истёк. Запустите новую диагностику для получения нового подготовленного действия.',
  'Execution response unavailable. Check the existing action.':
    'Ответ о выполнении недоступен. Проверьте это действие.',
  'Execution response unavailable. The Docker result is unconfirmed. Check this existing action before retrying.':
    'Ответ о выполнении недоступен. Результат Docker не подтверждён. Проверьте это действие перед повторной отправкой.',
  'Investigate {name} ({id}). What happened, and what evidence supports it?':
    'Проверь контейнер {name} ({id}). Что произошло и какие наблюдения это подтверждают?',
  actionRunning: 'выполняется',
  'Connection failed. Retry manually.': 'Не удалось подключиться. Повторите запрос вручную.',
  'Connection ended before the diagnostic turn completed. Retry manually.':
    'Соединение прервалось до завершения диагностики. Повторите запрос вручную.',
  'The diagnostic stream has no body.': 'В потоке диагностики нет данных.',
  'Diagnostic event exceeded the supported size.': 'Событие диагностики превысило допустимый размер.',
  'The API did not return a diagnostic event stream.': 'API не вернул поток событий диагностики.',
  'Demo: connection lost before the diagnostic stream opened.':
    'Демо: соединение прервалось до открытия потока диагностики.',
  'Demo: host connection unavailable.': 'Демо: подключение к хосту недоступно.',
  'Technical details': 'Технические подробности',
  'Cannot read this action. The Docker result remains unconfirmed. After a backend restart, inspect Docker before preparing another action.':
    'Не удалось прочитать состояние действия. Результат Docker не подтверждён. После перезапуска бэкенда проверьте Docker перед подготовкой нового действия.',
} as const;

export type MessageKey = keyof typeof russian;
export type Translator = (key: MessageKey, values?: MessageValues) => string;

const englishOverrides: Partial<Record<MessageKey, string | Plurals>> = {
  actionRunning: 'running',
  '{count} lines returned': { one: '{count} line returned', other: '{count} lines returned' },
  '{count} references': { one: '{count} reference', other: '{count} references' },
  '{count} turns in this tab session': {
    one: '{count} turn in this tab session',
    other: '{count} turns in this tab session',
  },
};

/** Narrow locally authored error messages without treating server prose as translation keys. */
export function isMessageKey(value: string): value is MessageKey {
  return Object.hasOwn(russian, value);
}

/** Resolve supported browser preferences without consulting or changing the operating system. */
export function resolveLocale(preference: LocalePreference, languages: readonly string[]): Locale {
  if (preference !== 'system') return preference;
  for (const language of languages) {
    const base = language.toLowerCase().split(/[-_]/)[0];
    if (base === 'en' || base === 'ru') return base;
  }
  return 'en';
}

/** Translate only typed product copy, using locale-specific plural and number formatting. */
export function translate(locale: Locale, key: MessageKey, values: MessageValues = {}): string {
  const entry: string | Plurals = locale === 'ru' ? russian[key] : (englishOverrides[key] ?? key);
  const template =
    typeof entry === 'string'
      ? entry
      : (entry[new Intl.PluralRules(locale).select(Number(values.count)) as keyof Plurals] ?? entry.other);
  return template.replace(/\{(\w+)\}/g, (placeholder: string, name: string) => {
    const value = values[name];
    return typeof value === 'number' ? new Intl.NumberFormat(locale).format(value) : (value ?? placeholder);
  });
}

/** Display a known contract state without altering the underlying server value. */
export function stateLabel(state: string, t: Translator, action = false): string {
  if (action && state === 'running') return t('actionRunning');
  return Object.hasOwn(russian, state) ? t(state as MessageKey) : state;
}
