# Google Calendar для Home Assistant

Custom integration for Home Assistant.

## Что делает

Интеграция создаёт сервисы:

- `gcal_cleanup.start_oauth`
- `gcal_cleanup.delete_events`

`delete_events` удаляет события Google Calendar за указанный период, если `summary` содержит одно из указанных значений.

## Логика credentials

1. Если установлена штатная интеграция `Google Calendar` и в Home Assistant есть Application Credentials для домена `google`, интеграция использует их `client_id` и `client_secret`.
2. Если штатные Google Application Credentials не найдены, интеграция показывает ручную форму, похожую на штатную форму Home Assistant: название, OAuth Client ID, OAuth Client Secret.

Важно: токен у этой интеграции отдельный. По умолчанию он сохраняется как:

`/config/gcal_cleanup_token.json`

## Установка

Скопируйте папку:

`custom_components/gcal_cleanup`

в:

`/config/custom_components/gcal_cleanup`

Перезапустите Home Assistant.

## Настройка

Настройки → Устройства и службы → Добавить интеграцию → Google Calendar Cleanup.

## OAuth

После добавления интеграции вызовите сервис:

```yaml
action: gcal_cleanup.start_oauth
data: {}
```

В уведомлении Home Assistant появится ссылка для авторизации Google.

В Google Cloud в Authorized redirect URIs должен быть указан callback, который интеграция покажет в уведомлении, например:

`http://172.16.1.18:8123/api/gcal_cleanup/oauth2callback`

## Проверка удаления

```yaml
action: gcal_cleanup.delete_events
data:
  start_date: "2026-01-01"
  end_date: "2026-12-31"
  summary_contains: "Алмател, ISP Алмател"
  dry_run: true
```

## Реальное удаление

```yaml
action: gcal_cleanup.delete_events
data:
  start_date: "2026-01-01"
  end_date: "2026-12-31"
  summary_contains: "Алмател, ISP Алмател"
  dry_run: false
```
