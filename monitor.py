from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv



# ENVIRONMENT
# ОКРУЖЕНИЕ
# Load .env from the same directory as this script.
# Загружает .env из той же папки, что и этот скрипт.
SCRIPT_DIR = Path(__file__).resolve().parent
ENV_FILE = SCRIPT_DIR / ".env"

load_dotenv(ENV_FILE)

# DAS CONFIGURATION
# КОНФИГУРАЦИЯ DAS

BASE = "https://asukassivut.das.fi"

CONTRACT_ID = "772b9d05-c389-4477-a8f1-d68527bab6e8"

CALENDAR_ID = 312

BOOKING_URL = (
    "https://asukassivut.das.fi/asiointi/"
    "772b9d05-c389-4477-a8f1-d68527bab6e8/saunavaraukset"
)


# GENERAL CONFIGURATION
# ОБЩАЯ КОНФИГУРАЦИЯ
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "120"))

INITIAL_NOTIFY = os.getenv(
    "INITIAL_NOTIFY",
    "true"
).strip().lower() in {
    "1",
    "true",
    "yes",
    "y",
    "on",
}


AVAILABLE_STATUSES = {
    value.strip().lower()
    for value in os.getenv(
        "AVAILABLE_STATUSES",
        "available,free,open"
    ).split(",")
    if value.strip()
}


STATE_FILE = Path(
    os.getenv(
        "STATE_FILE",
        str(SCRIPT_DIR / "state.json")
    )
)


LOCAL_TZ = ZoneInfo("Europe/Helsinki")


# AUTHENTICATION
# АУТЕНТИФИКАЦИЯ
DAS_COOKIE = os.getenv("DAS_COOKIE", "").strip()


# HTTP SESSION
# HTTP-СЕАНС
session = requests.Session()

session.headers.update({
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": BOOKING_URL,
})


if DAS_COOKIE:
    session.headers["Cookie"] = DAS_COOKIE



# TELEGRAM SECTION
# РАЗДЕЛ TELEGRAM
def die(message: str) -> None:
    """
    Print an error and stop the program.
    Вывести ошибку и остановить программу.
    """
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def telegram_call(
    method: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Call the Telegram Bot API.
    Вызвать API Telegram Bot.
    """

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN",
        ""
    ).strip()

    if not token:
        die(
            "TELEGRAM_BOT_TOKEN is not set. "
            "Add it to your .env file."
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{token}/{method}"
    )

    response = requests.post(
        url,
        json=payload,
        timeout=20,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(
            f"Telegram API error: {data}"
        )

    return data


def send_telegram(text: str) -> None:
    """
    Send a Telegram message.
    Отправить сообщение в Telegram.
    """

    chat_id = os.getenv(
        "TELEGRAM_CHAT_ID",
        ""
    ).strip()

    if not chat_id:
        die(
            "TELEGRAM_CHAT_ID is not set. "
            "Add it to your .env file."
        )

    telegram_call(
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
    )


def get_chat_id() -> None:
    """
    Print recent Telegram chat IDs.
    Вывести последние идентификаторы чатов Telegram.

    Usage:
    Использование:

        python sauna_monitor.py chat-id

    First send /start to your Telegram bot.
    Сначала отправьте /start своему боту Telegram.
    """

    data = telegram_call(
        "getUpdates",
        {
            "limit": 20,
            "timeout": 0,
        },
    )

    updates = data.get("result", [])

    if not updates:
        print(
            "No updates found.\n"
            "Open your bot in Telegram, send /start, "
            "then run this command again."
        )
        return

    seen: set[int] = set()

    for update in updates:

        message = (
            update.get("message")
            or update.get("edited_message")
        )

        if not message:
            continue

        chat = message.get("chat", {})

        chat_id = chat.get("id")

        if chat_id in seen:
            continue

        seen.add(chat_id)

        first_name = chat.get("first_name", "")
        last_name = chat.get("last_name", "")

        name = f"{first_name} {last_name}".strip()

        print(
            f"chat_id={chat_id} | "
            f"type={chat.get('type')} | "
            f"name={name}"
        )


# API
# API
def api_url() -> str:
    """
    Return the DAS time-slot API URL.
    Вернуть URL API временных слотов DAS.
    """

    return (
        f"{BASE}/api/contracts/"
        f"{CONTRACT_ID}/"
        f"reservation-calendars/"
        f"{CALENDAR_ID}/time-slots"
    )


def fetch_slots(
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    """
    Fetch sauna slots from DAS.
    Получить слоты сауны из DAS.

    Raises PermissionError when DAS requires authentication.
    Вызывает PermissionError, когда DAS требует аутентификацию.
    """

    params = {
        "startDate": start_date,
        "endDate": end_date,
    }

    response = session.get(
        api_url(),
        params=params,
        timeout=30,
    )

    if response.status_code in (401, 403):

        raise PermissionError(
            f"DAS returned HTTP {response.status_code}. "
            "Your DAS login session/cookie is missing "
            "or has expired."
        )

    response.raise_for_status()

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(
            "DAS returned a response that was not valid JSON."
        ) from exc

    if not isinstance(data, dict):
        raise RuntimeError(
            "Unexpected DAS response: expected a JSON object."
        )

    return data


# STATE FILE
# ФАЙЛ СОСТОЯНИЯ
def load_state() -> dict[str, str]:
    """
    Load the previous slot state.
    Загрузить предыдущее состояние слотов.
    """

    if not STATE_FILE.exists():
        return {}

    try:

        raw = STATE_FILE.read_text(
            encoding="utf-8"
        )

        data = json.loads(raw)

        if not isinstance(data, dict):
            print(
                "WARNING: state.json does not contain "
                "a valid object. Starting fresh."
            )
            return {}

        return {
            str(key): str(value)
            for key, value in data.items()
        }

    except (OSError, json.JSONDecodeError) as exc:

        print(
            f"WARNING: Could not read state file: {exc}"
        )

        return {}


def save_state(
    state: dict[str, str]
) -> None:
    """
    Save state atomically.
    Атомарно сохранить состояние.
    """

    STATE_FILE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    temp_file = STATE_FILE.with_suffix(
        ".tmp"
    )

    temp_file.write_text(
        json.dumps(
            state,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    temp_file.replace(STATE_FILE)



# SLOT PROCESSING
# ОБРАБОТКА СЛОТОВ
def get_slot_status(
    slot: dict[str, Any]
) -> str:
    """
    Return a normalized slot status.
    Вернуть нормализованный статус слота.
    """

    return str(
        slot.get("status", "unknown")
    ).strip().lower()


def is_available(
    slot: dict[str, Any]
) -> bool:
    """
    Return True if the slot is considered available.
    Вернуть True, если слот считается доступным.
    """

    status = get_slot_status(slot)

    return status in AVAILABLE_STATUSES


def get_slot_id(
    slot: dict[str, Any]
) -> str | None:
    """
    Return a usable slot ID.
    Вернуть пригодный для использования идентификатор слота.
    """

    slot_id = slot.get("id")

    if slot_id is None:
        return None

    slot_id = str(slot_id).strip()

    if not slot_id:
        return None

    return slot_id


def format_slot(
    slot: dict[str, Any]
) -> str:
    """
    Format an available slot for Telegram.
    Отформатировать доступный слот для Telegram.
    """

    starts_at = slot.get("startsAt")
    ends_at = slot.get("endsAt")

    if not starts_at or not ends_at:
        raise RuntimeError(
            f"Slot {slot.get('id')} is missing "
            "startsAt or endsAt."
        )

    try:

        start = (
            datetime
            .fromisoformat(
                str(starts_at).replace(
                    "Z",
                    "+00:00",
                )
            )
            .astimezone(LOCAL_TZ)
        )

        end = (
            datetime
            .fromisoformat(
                str(ends_at).replace(
                    "Z",
                    "+00:00",
                )
            )
            .astimezone(LOCAL_TZ)
        )

    except ValueError as exc:

        raise RuntimeError(
            f"Could not parse slot dates: "
            f"{starts_at} / {ends_at}"
        ) from exc

    return (
        "🔔 DAS Eero sauna slot available!\n\n"
        f"{start.strftime('%A %d.%m.%Y')}\n"
        f"{start.strftime('%H:%M')}–"
        f"{end.strftime('%H:%M')}\n"
        f"Slot {slot.get('id')}\n\n"
        f"Book here:\n{BOOKING_URL}"
    )



# MONITORING
# МОНИТОРИНГ
def monitor_once(
    state: dict[str, str]
) -> tuple[dict[str, str], int]:
    """
    Check DAS once.
    Проверить DAS один раз.

    Returns:
    Возвращает:
        new_state, number_of_notifications
        новое состояние, количество уведомлений
    """

    now = datetime.now(timezone.utc)

    local_today = (
        now
        .astimezone(LOCAL_TZ)
        .date()
    )

    start_date = local_today

    end_date = (
        start_date
        + timedelta(days=14)
    )

    print(
        f"Checking DAS: "
        f"{start_date.isoformat()} → "
        f"{end_date.isoformat()}"
    )

    data = fetch_slots(
        start_date.isoformat(),
        end_date.isoformat(),
    )

    slots = data.get(
        "timeSlots",
        []
    )

    if not isinstance(slots, list):

        raise RuntimeError(
            "Unexpected DAS response: "
            "'timeSlots' is not a list."
        )

    new_state: dict[str, str] = {}

    notifications = 0

    available_count = 0

    for slot in slots:

        if not isinstance(slot, dict):
            continue

        slot_id = get_slot_id(slot)

        if slot_id is None:
            continue

        status = get_slot_status(slot)

        available = (
            status in AVAILABLE_STATUSES
        )

        current_state = (
            "available"
            if available
            else status
        )

        previous_state = state.get(
            slot_id
        )

        new_state[slot_id] = current_state

        if available:
            available_count += 1

        # Slot changed from unavailable -> available.
        # Слот изменился с недоступного на доступный.
        became_available = (
            available
            and previous_state is not None
            and previous_state != "available"
        )

        # Slot was already available when
        # the monitor first encountered it.
        # Слот уже был доступен при первом обнаружении монитором.
        first_seen_available = (
            available
            and previous_state is None
        )

        should_notify = (
            became_available
            or (
                first_seen_available
                and INITIAL_NOTIFY
            )
        )

        if should_notify:

            try:

                message = format_slot(
                    slot
                )

                send_telegram(
                    message
                )

                notifications += 1

                print(
                    f"NOTIFIED: slot {slot_id}"
                )

            except Exception as exc:

                print(
                    f"WARNING: Failed to "
                    f"notify slot {slot_id}: "
                    f"{type(exc).__name__}: {exc}"
                )

    print(
        f"Found {len(slots)} total slots, "
        f"{available_count} currently available."
    )

    return new_state, notifications


# STARTUP CHECKS
# ПРОВЕРКИ ПРИ ЗАПУСКЕ
def validate_configuration() -> None:
    """
    Validate the important environment variables.
    Проверить важные переменные окружения.
    """

    telegram_token = os.getenv(
        "TELEGRAM_BOT_TOKEN",
        ""
    ).strip()

    telegram_chat_id = os.getenv(
        "TELEGRAM_CHAT_ID",
        ""
    ).strip()

    if not telegram_token:
        die(
            "TELEGRAM_BOT_TOKEN is missing.\n"
            "Add it to .env."
        )

    if not telegram_chat_id:
        die(
            "TELEGRAM_CHAT_ID is missing.\n"
            "Add it to .env."
        )

    if POLL_SECONDS < 10:
        die(
            "POLL_SECONDS is too low. "
            "Use at least 10 seconds."
        )

    if not AVAILABLE_STATUSES:
        die(
            "AVAILABLE_STATUSES is empty."
        )


def print_configuration() -> None:
    """
    Print safe startup information.
    Вывести безопасную информацию при запуске.
    """

    print()
    print("=" * 60)
    print("DAS Eero sauna monitor")
    print("=" * 60)

    print(
        f"Polling every: "
        f"{POLL_SECONDS} seconds"
    )

    print(
        "Recognized available statuses: "
        f"{sorted(AVAILABLE_STATUSES)}"
    )

    print(
        f"Initial notification: "
        f"{INITIAL_NOTIFY}"
    )

    print(
        f"State file: "
        f"{STATE_FILE.resolve()}"
    )

    print(
        "DAS authentication: "
        f"{'configured' if DAS_COOKIE else 'NOT CONFIGURED'}"
    )

    print("=" * 60)
    print()


# MAIN LOOP
# ГЛАВНЫЙ ЦИКЛ
def main() -> None:

    validate_configuration()

    print_configuration()

    if not DAS_COOKIE:

        print(
            "WARNING: DAS_COOKIE is not configured."
        )

        print(
            "If DAS returns HTTP 401/403, "
            "copy the Cookie request header from "
            "your logged-in DAS browser session "
            "into .env."
        )

        print()

    state = load_state()

    print(
        f"Loaded {len(state)} saved slot states."
    )

    print(
        "Monitor started. "
        "Press Ctrl+C to stop."
    )

    print()

    while True:

        try:

            state, notification_count = (
                monitor_once(state)
            )

            save_state(state)

            now = (
                datetime
                .now(LOCAL_TZ)
                .strftime(
                    "%Y-%m-%d %H:%M:%S %Z"
                )
            )

            print(
                f"[{now}] "
                f"Checked successfully: "
                f"{len(state)} slots, "
                f"{notification_count} "
                f"notification(s)"
            )

        except PermissionError as exc:

            print()
            print(
                "DAS AUTHENTICATION REQUIRED"
            )

            print(str(exc))

            print(
                "Update DAS_COOKIE in your .env "
                "with the current Cookie header "
                "from your logged-in DAS browser."
            )

            print()

        except requests.RequestException as exc:

            print()
            print(
                f"NETWORK ERROR: "
                f"{type(exc).__name__}: {exc}"
            )
            print()

        except Exception as exc:

            print()
            print(
                f"ERROR: "
                f"{type(exc).__name__}: {exc}"
            )
            print()

        try:

            time.sleep(POLL_SECONDS)

        except KeyboardInterrupt:

            print()
            print(
                "Monitor stopped."
            )
            break


# ENTRY POINT
# ТОЧКА ВХОДА
if __name__ == "__main__":

    if (
        len(sys.argv) > 1
        and sys.argv[1].lower() == "chat-id"
    ):
        get_chat_id()

    else:
        main()