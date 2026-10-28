import { demoMessages } from './demoMessages';

export type Locale = 'en' | 'ru';
export type LocalePreference = Locale | 'system';
type Plurals = { one: string; other: string; few?: string; many?: string };
export type MessageValues = Record<string, string | number>;

/** Keep product copy separate from verbatim Docker, model, and server content. */
const russian = {
  ...demoMessages,
  'Inventory observed {time} · refreshes every 10 seconds': 'Список получен в {time} · обновляется каждые 10 секунд',
  'State refreshes every 10 seconds · logs and metrics refresh manually.':
    'Состояние обновляется каждые 10 секунд · логи и метрики обновляются вручную.',
  'This container no longer exists on the selected host.': 'Этот контейнер больше не существует на выбранном хосте.',
  'Workspace: choose host': 'Рабочее пространство: выбрать хост',
  'Choose a host': 'Выбрать хост',
  'Choose a configured Docker host. Selecting another host starts a separate session.':
    'Выберите настроенный хост Docker. При выборе другого хоста начнётся отдельная сессия.',
  'Current host': 'Текущий хост',
  'Refreshing container list…': 'Обновляем список контейнеров…',
  'Container list refreshed': 'Список контейнеров обновлён',
  'List received at {time}': 'Список получен в {time}',
  API: 'API',
  Docker: 'Docker',
  Model: 'Модель',
  Provider: 'Провайдер',
  Available: 'Доступно',
  'Not checked': 'Не проверено',
  'System status': 'Состояние системы',
  'View system status': 'Посмотреть состояние системы',
  'API & authorization': 'API и авторизация',
  'Provider & model': 'Провайдер и модель',
  'No host selected': 'Хост не выбран',
  'Check again': 'Проверить снова',
  'Checking dependencies…': 'Проверяем подключения…',
  'No background polling': 'Автоматического опроса нет',
  'API and authorization verified.': 'API доступен, авторизация подтверждена.',
  'The API rejected the bearer token.': 'API отклонил токен авторизации.',
  'API access is denied. Check permissions and allowed origins.':
    'Доступ к API запрещён. Проверьте права и разрешённые источники.',
  'No connection to the API. Check the endpoint and network.': 'Нет соединения с API. Проверьте адрес и сеть.',
  'Status checks are not supported by this API.': 'Этот API не поддерживает проверку состояния системы.',
  'The API could not complete the status check.': 'API не смог завершить проверку состояния системы.',
  'Demo statuses are simulated. No connections are checked.':
    'Статусы в демо смоделированы. Реальные подключения не проверяются.',
  'Dependency results are from the previous successful check.':
    'Показаны результаты последней успешной проверки подключений.',
  'Tools and structured output have not been tested.': 'Вызов инструментов и структурированный ответ не проверялись.',
  'This check reads metadata only and never generates an answer.':
    'Проверка читает только метаданные и не генерирует ответ.',
  'Provider and model settings are managed on the server.': 'Настройки провайдера и модели задаются на сервере.',
  'Docker is unavailable for this host. Diagnosis cannot collect evidence. Check the connection and try again.':
    'Docker выбранного хоста недоступен. Диагностика не сможет собрать данные. Проверьте подключение и повторите проверку.',
  'The configured model is unavailable. You can still inspect Docker directly.':
    'Настроенная модель недоступна. Данные Docker можно просматривать напрямую.',
  'The model provider is unavailable. You can still inspect Docker directly.':
    'Провайдер модели недоступен. Данные Docker можно просматривать напрямую.',
  'Availability check succeeded.': 'Проверка доступности выполнена успешно.',
  'Select a configured host to check Docker.': 'Выберите настроенный хост для проверки Docker.',
  'The availability check timed out.': 'Время проверки доступности истекло.',
  'Could not connect to the provider.': 'Не удалось подключиться к провайдеру.',
  'Could not connect to the selected Docker host.': 'Не удалось подключиться к выбранному хосту Docker.',
  'The provider rejected its server-configured credentials.':
    'Провайдер отклонил учётные данные, настроенные на сервере.',
  'Model metadata access is denied; generation access was not tested.':
    'Доступ к метаданным модели запрещён; возможность генерации не проверялась.',
  'The provider does not expose a supported model metadata endpoint.':
    'Провайдер не предоставляет поддерживаемый API метаданных модели.',
  'The configured model was not found by the provider.': 'Провайдер не нашёл настроенную модель.',
  'The model is not in the returned catalog; aliases and generation were not tested.':
    'Модель отсутствует в полученном каталоге; псевдонимы и генерация не проверялись.',
  'The provider rate-limited the availability check.': 'Провайдер ограничил частоту запросов проверки доступности.',
  'The provider could not complete the availability check.': 'Провайдер не смог завершить проверку доступности.',
  'The provider returned unsupported or oversized metadata.':
    'Провайдер вернул неподдерживаемые или слишком большие метаданные.',
  'Metadata checks are not configured for this model adapter.':
    'Проверка метаданных для этого адаптера модели не настроена.',
  'The availability check could not finish.': 'Не удалось завершить проверку доступности.',
  'Model availability was not checked because the provider check failed.':
    'Доступность модели не проверена из-за ошибки проверки провайдера.',
  'Refresh failed': 'Не удалось обновить список',
  'Showing the last received list.': 'Показан последний полученный список.',
  'Container overview': 'Обзор контейнера',
  'Container facts': 'Факты о контейнере',
  'Read-only · no model request': 'Только чтение · без запроса к модели',
  'Back to investigation': 'Вернуться к расследованию',
  'Refresh data': 'Обновить данные',
  'Retry data': 'Повторить загрузку данных',
  Diagnose: 'Диагностировать',
  'Refreshing container data…': 'Обновляем данные контейнера…',
  'Snapshot only · refresh manually for current data.': 'Снимок данных · для актуальных значений обновите вручную.',
  'Current metrics': 'Текущие метрики',
  'Memory usage': 'Использование памяти',
  'Memory limit': 'Лимит памяти',
  'One measurement · no metric history': 'Один замер · без истории метрик',
  'Compose project': 'Проект Compose',
  Started: 'Время запуска',
  Received: 'Получено',
  'None reported': 'Не указан',
  'Could not read container state.': 'Не удалось получить состояние контейнера.',
  'Could not read container logs.': 'Не удалось получить логи контейнера.',
  'Could not read container metrics.': 'Не удалось получить метрики контейнера.',
  'Could not read allowlisted environment.': 'Не удалось получить разрешённые переменные окружения.',
  'Showing the last successful observation.': 'Показаны данные последнего успешного запроса.',
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
  'Test error states': 'Проверить ошибки',
  'Demo host / EU': 'Демо-хост / EU',
  'Demo host / Empty': 'Демо-хост / Пустой',
  'Example data from a fictional host. Connect an API to diagnose your Docker.':
    'Пример данных вымышленного хоста. Подключите API для диагностики своего Docker.',
  'Simulated connection': 'Имитация подключения',
  'Requests succeed normally.': 'Запросы выполняются без ошибок.',
  'Submit a question to simulate a failure after collecting evidence.':
    'Отправьте вопрос, чтобы увидеть ошибку после сбора данных.',
  'The container list cannot load; submitting a question also fails.':
    'Список контейнеров не загружается; отправка вопроса тоже завершится ошибкой.',
  'The container list is empty; new questions return no container evidence.':
    'Список контейнеров пуст; новые вопросы вернут ответ без данных о контейнерах.',
  'After action confirmation': 'После подтверждения действия',
  'Action outcome': 'Результат действия',
  'Choose a result, review a container action, then confirm it. Shown cards stay unchanged.':
    'Выберите результат, откройте действие контейнера и подтвердите его. Данные в карточках останутся прежними.',
  'Demo connection behavior': 'Подключение в демо',
  Normal: 'Обычное',
  'Turn fails after collection': 'Ошибка после сбора данных',
  'Connection unavailable': 'Нет подключения',
  'Empty inventory': 'Пустой список контейнеров',
  'Demo action outcome': 'Результат действия в демо',
  Succeeded: 'Успешно',
  Failed: 'Ошибка',
  Indeterminate: 'Результат не подтверждён',
  Expired: 'Срок истёк',
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
