/** Translate authored demo narratives without touching Docker evidence or API responses. */
export const demoMessages = {
  'Why does payments-api keep restarting?': 'Почему payments-api постоянно перезапускается?',
  'Why did report-worker exit with code 137?': 'Почему report-worker завершился с кодом 137?',
  'Why can checkout-api not start?': 'Почему checkout-api не запускается?',
  'What happened to migration-runner?': 'Что произошло с migration-runner?',
  'Was event-consumer killed by the OOM killer?': 'Был ли event-consumer завершён из-за нехватки памяти?',
  'Is redis healthy in this observation?': 'Что известно о состоянии redis по этому наблюдению?',
  'payments-api is caught in a restart loop. Docker reports 9 restarts and exit code 1. The startup logs report invalid application configuration. Review the configuration before restarting; stopping the loop is available for this observed state.':
    'payments-api попал в цикл перезапусков. Docker сообщает о 9 перезапусках и коде выхода 1. В логах запуска указана ошибка конфигурации приложения. Проверьте конфигурацию перед перезапуском; для этого состояния доступна остановка контейнера.',
  'Docker reports that report-worker was OOM-killed and exited with code 137. This supports an out-of-memory termination. Current memory usage is unavailable after exit; these observations do not establish which allocation caused it.':
    'Docker сообщает, что report-worker был завершён из-за нехватки памяти (OOM) с кодом выхода 137. Это подтверждает завершение из-за нехватки памяти. Текущий расход памяти после завершения недоступен; по этим наблюдениям нельзя установить, какое выделение памяти привело к сбою.',
  'checkout-api exited with code 1. Its logs report a refused database connection. This points to an unavailable dependency at startup; the database itself was not inspected, so its cause is not established.':
    'checkout-api завершился с кодом 1. В логах указано, что база данных отказала в подключении. Это указывает на недоступную зависимость при запуске; сама база данных не проверялась, поэтому причина её недоступности не установлена.',
  'migration-runner exited with code 1, but the available logs end during startup. The log batch is truncated. The evidence is insufficient to identify the failure; inspect the complete logs before choosing a fix.':
    'migration-runner завершился с кодом 1, но доступные логи заканчиваются на этапе запуска. Логи обрезаны. Данных недостаточно для определения причины сбоя; изучите полные логи, прежде чем выбирать способ исправления.',
  'event-consumer exited with code 137. Docker does not report an OOM kill, and no log entries are available. Code 137 alone does not establish an out-of-memory cause. The reason for termination remains uncertain.':
    'event-consumer завершился с кодом 137. Docker не сообщает о завершении из-за OOM, строки логов недоступны. Сам по себе код 137 не подтверждает нехватку памяти. Причина завершения остаётся неизвестной.',
  'redis is running in this observation. Current CPU usage is 0.0% and memory usage is 8.0 MiB of 128.0 MiB. No restarts or OOM kill are reported. These values are a single measurement, not a historical health guarantee.':
    'По этому наблюдению redis работает. Текущая загрузка CPU — 0,0%, расход памяти — 8,0 MiB из 128,0 MiB. Перезапусков и завершения из-за OOM не зафиксировано. Это единичный замер; он не подтверждает стабильность работы за прошлое время.',
  'No containers were returned on this host. There is no container evidence to establish a cause.':
    'На этом хосте не найдено контейнеров. Данных о контейнерах для установления причины нет.',
  'Demo: model timed out after collecting evidence.': 'Демо: время ожидания ответа модели истекло после сбора данных.',
} as const;
