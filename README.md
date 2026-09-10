# Google Calendar для Home Assistant

Пользовательская интеграция Home Assistant для работы с Google Calendar и Google Tasks.

Версия: **1.4.1**

## Возможности

Интеграция создаёт четыре сенсора:

- `sensor.google_calendar_events` — мероприятия на сегодня;
- `sensor.google_calendar_holidays` — праздники на сегодня;
- `sensor.google_calendar_contacts_birthdays` — дни рождения и события контактов;
- `sensor.google_tasks` — задачи из выбранного списка Google Tasks.

Также интеграция предоставляет сервис:

- `google_calendar.delete_events` — поиск и удаление событий Google Calendar за указанный период по совпадению текста в `summary`.

## Сенсоры

### `sensor.google_calendar_events`

Показывает мероприятия из выбранного календаря Google Calendar на текущий день.

Атрибуты:

- `text` — подробный текст со списком мероприятий.

По умолчанию используется календарь:

```text
primary
```

Из списка мероприятий исключаются события, содержащие:

- `день рождения`
- `День рождения`
- `Именины`
- `Годовщина смерти`

Интервал обновления: **60 секунд**.

### `sensor.google_calendar_holidays`

Показывает праздники на текущий день из календаря:

```text
ru.russian#holiday@group.v.calendar.google.com
```

Атрибуты:

- `text` — подробный текст.

Интервал обновления: **71 секунда**.

### `sensor.google_calendar_contacts_birthdays`

Показывает дни рождения и другие события контактов из календаря:

```text
addressbook#contacts@group.v.calendar.google.com
```

Атрибуты:

- `text` — подробный текст.

Интервал обновления: **92 секунды**.

### `sensor.google_tasks`

Показывает задачи Google Tasks из выбранного Task List.

Атрибуты:

- `text` — список задач;
- `notes` — подробные описания задач.

Интервал обновления: **104 секунды**.

Список Google Tasks выбирается в настройках интеграции:

```text
Настройки → Устройства и службы → Google Calendar → Настроить
```

Интеграция сама получает доступные Task Lists из Google Tasks API и показывает их названия в выпадающем списке.

## OAuth и права доступа

Интеграция использует один OAuth-токен для двух API:

```text
https://www.googleapis.com/auth/calendar
https://www.googleapis.com/auth/tasks
```

По умолчанию используются файлы:

```text
/config/credentials.json
/config/token.json
```

Для OAuth используется штатный механизм Home Assistant.

При первичной настройке или необходимости повторной авторизации Home Assistant открывает стандартный внешний OAuth flow:

```text
Home Assistant
→ Google
→ My Home Assistant
→ Home Assistant
```

Если токен отсутствует, истёк без возможности обновления или не содержит необходимых scope, интеграция инициирует штатную повторную авторизацию Home Assistant.

## Настройка Google Cloud

В Google Cloud должны быть включены:

- Google Calendar API;
- Google Tasks API.

Используйте OAuth 2.0 Client ID типа:

```text
Web application
```

В **Authorized redirect URIs** добавьте:

```text
https://my.home-assistant.io/redirect/oauth
```

Файл `credentials.json` должен соответствовать именно этому Web OAuth client.

Пример структуры:

```json
{
  "web": {
    "client_id": "YOUR_CLIENT_ID.apps.googleusercontent.com",
    "project_id": "YOUR_PROJECT_ID",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_secret": "YOUR_CLIENT_SECRET",
    "redirect_uris": [
      "https://my.home-assistant.io/redirect/oauth"
    ]
  }
}
```

## Установка

Скопируйте папку:

```text
google_calendar
```

в:

```text
/config/custom_components/google_calendar
```

Итоговая структура:

```text
/config/custom_components/google_calendar/
├── __init__.py
├── api.py
├── config_flow.py
├── const.py
├── coordinator.py
├── manifest.json
├── sensor.py
├── services.yaml
└── strings.json
```

После копирования файлов полностью перезапустите Home Assistant.

## Добавление интеграции

Откройте:

```text
Настройки
→ Устройства и службы
→ Добавить интеграцию
→ Google Calendar
```

Укажите:

- путь к `credentials.json`;
- путь к `token.json`;
- Calendar ID.

Значения по умолчанию:

```text
credentials.json
token.json
primary
```

После этого Home Assistant запустит OAuth-авторизацию Google.

## Выбор Google Tasks List

После успешной авторизации откройте:

```text
Настройки
→ Устройства и службы
→ Google Calendar
→ Настроить
```

Выберите нужный список Google Tasks.

После сохранения интеграция автоматически перезагрузится.

## Удаление событий Google Calendar

Сервис:

```text
google_calendar.delete_events
```

Поддерживает:

- начальную дату;
- конечную дату;
- поиск одного или нескольких фрагментов текста в `summary`;
- выбор `calendar_id`;
- безопасный режим `dry_run`.

### Проверка без удаления

```yaml
action: google_calendar.delete_events
data:
  start_date: "2026-01-01"
  end_date: "2026-12-31"
  summary_contains: "Алмател, ISP Алмател"
  dry_run: true
```

Интеграция найдёт подходящие события, но не удалит их.

### Реальное удаление

```yaml
action: google_calendar.delete_events
data:
  start_date: "2026-01-01"
  end_date: "2026-12-31"
  summary_contains: "Алмател, ISP Алмател"
  dry_run: false
```

Если `calendar_id` не указан, используется Calendar ID из настроек интеграции.

## Хранение данных

Интеграция не создаёт собственный большой кеш календаря в `.storage`.

Она получает данные через Google API и хранит в Home Assistant только текущее состояние сенсоров.

## Требования

- Home Assistant;
- доступ к Интернету;
- Google Cloud project;
- Google Calendar API;
- Google Tasks API;
- OAuth 2.0 Web application credentials.

Python-зависимости устанавливаются Home Assistant автоматически:

```text
google-api-python-client
google-auth
```

## Предупреждение

Это пользовательская интеграция, не являющаяся частью официального Home Assistant Core.

Перед массовым удалением событий рекомендуется сначала запускать `google_calendar.delete_events` с:

```yaml
dry_run: true
```
