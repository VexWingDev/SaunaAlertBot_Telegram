[Русская версия](README.ru.md)

# Sauna Slot Monitor

This program watches the DAS Eero reservation calendar and sends a Telegram
message when a sauna time slot becomes available.
It checks a rolling 14-day window and polls every 2 minutes by default.

## Important Notes

The bot is designed mainly for the DAS housing - Eero, where the sauna is available. However, you can toogle with a few lines of code and the API to make it personalized for your DAS housing section, or anywhere else. The main thing that changes is it, is the API. Use it however you wish to.

In the information below, you will find a guide on what you will have to do to start the bot.

I added an `example.env` for you to see how to set up your secrets. **Remember** one thing, do not share the secrets to any living or artificial being.

### 1. Install Python

Use Python 3.10+.

Check:

    python --version

### 2. Install dependencies

    python -m pip install -r requirements.txt

## 3. Create a Telegram bot

In Telegram, open **@BotFather** and use `/newbot`.

Put the token into an environment variable named `TELEGRAM_BOT_TOKEN`.

Then open your new bot and send it `/start`.

Run:

    python monitor.py chat-id

This prints recent chat IDs. Put your private chat ID into
`TELEGRAM_CHAT_ID`.

## 4. Test Telegram

Set both environment variables, then run:

    python test_telegram.py

You should receive a Telegram message.

## 5. Test access

Run:

    python monitor.py

If the API is publicly readable for this contract, it will start monitoring
immediately.

If you see:

    AUTHENTICATION REQUIRED

then set `DAS_COOKIE` to the complete value of the browser's Cookie request
header while you are logged into DAS.

### Getting DAS_COOKIE

1. Open the tenants page, specific section in your browser.
2. Press F12 -> Network. (or right click and pick ''inspect...'')
3. Reload the page.
4. Click the `time-slots?...` request.
5. Under Request Headers find `Cookie`.
6. Copy the value after `Cookie:` into `DAS_COOKIE`.

Do not copy or share `Authorization` headers, passwords, or other secrets. Not to any living person, or Artificial Intelligence.
***That is a security risk***

Cookies expire. If the monitor starts returning 401/403 later, refresh the
login/cookie.

## How availability detection works

The API response contains entries such as:

    "status": "reserved"
    "status": "own"

Those are treated as unavailable.

The default available values are:

    available
    free
    open

If the monitor logs an unexpected status value when a slot looks free in the
website, set `AVAILABLE_STATUSES` to include that value.

For example:

    AVAILABLE_STATUSES=available,free,open,unreserved

## Running continuously

For a home PC, keep the terminal open.

For Windows, Task Scheduler can launch:

    python C:\path\to\monitor.py

For Linux, systemd is recommended.

A VPS is also suitable if you want it running 24/7.

## Notes

- The program does **not** book slots. It only notifies you.
- State is stored in `state.json` to avoid repeated notifications - it will download automatically, thats why `download` file exists.
- The API timestamps are UTC; notifications are converted to Europe/Helsinki, however feel free to adjust it to your own timezone.
