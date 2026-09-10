from datetime import timedelta

DOMAIN = "google_calendar"

CONF_CREDENTIALS_FILE = "credentials_file"
CONF_TOKEN_FILE = "token_file"
CONF_CALENDAR_ID = "calendar_id"
CONF_BASE_URL = "base_url"
CONF_TASK_LIST_ID = "task_list_id"

DEFAULT_CREDENTIALS_FILE = "credentials.json"
DEFAULT_TOKEN_FILE = "token.json"
DEFAULT_CALENDAR_ID = "primary"

CALLBACK_PATH = "/api/google_calendar/oauth2callback"

SCOPE_CALENDAR = "https://www.googleapis.com/auth/calendar"
SCOPE_TASKS = "https://www.googleapis.com/auth/tasks"
CALENDAR_SCOPES = [SCOPE_CALENDAR]
TASKS_SCOPES = [SCOPE_TASKS]
SCOPES = [SCOPE_CALENDAR, SCOPE_TASKS]

HOLIDAYS_CALENDAR_ID = "ru.russian#holiday@group.v.calendar.google.com"
CONTACTS_BIRTHDAYS_CALENDAR_ID = "addressbook#contacts@group.v.calendar.google.com"

UPDATE_INTERVAL_EVENTS = timedelta(seconds=60)
UPDATE_INTERVAL_HOLIDAYS = timedelta(seconds=71)
UPDATE_INTERVAL_CONTACTS = timedelta(seconds=92)
UPDATE_INTERVAL_TASKS = timedelta(seconds=104)
