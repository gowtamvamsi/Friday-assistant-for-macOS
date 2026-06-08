"""
agents/scheduled_tasks.py — Phase 5: Proactive Background Agents

Implements:
  - ScheduledTaskRunner: A background daemon thread that checks scheduled
    tasks every minute and fires them at the right time without interrupting
    active voice interactions.

  - morning_digest: Fetches Gmail, Calendar, and Tasks data via Google APIs
    and compiles a spoken morning briefing delivered through the Phase 4 TTS engine.

Google API Setup:
  1. Go to https://console.cloud.google.com/ and create a project.
  2. Enable Gmail API, Google Calendar API, Google Tasks API.
  3. Create an OAuth 2.0 Client ID (Desktop App) and download credentials.json
     into the project root directory.
  4. Run Friday once and authorize the OAuth flow in the browser.
  5. token.json will be saved and reused for subsequent runs.
"""

import os
import time
import logging
import datetime
import threading
from typing import Callable, Optional, List, Dict, Any

logger = logging.getLogger("friday.scheduled_tasks")

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/tasks.readonly",
]

CREDENTIALS_PATH = "credentials.json"
TOKEN_PATH = "token.json"


# ── Google API OAuth Helper ────────────────────────────────────────────────────

def _get_google_credentials():
    """Loads or refreshes Google OAuth credentials, prompting the browser if needed."""
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow

        creds = None

        if os.path.exists(TOKEN_PATH):
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            elif os.path.exists(CREDENTIALS_PATH):
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
                creds = flow.run_local_server(port=0)
            else:
                logger.warning(
                    "Google credentials.json not found. Morning Digest will be skipped. "
                    "Download credentials.json from Google Cloud Console and place in project root."
                )
                return None

            with open(TOKEN_PATH, "w") as token:
                token.write(creds.to_json())

        return creds

    except ImportError:
        logger.error("Google API libraries not installed. Run: pip install google-api-python-client google-auth-oauthlib")
        return None
    except Exception as e:
        logger.error(f"Google OAuth failed: {e}")
        return None


# ── Morning Digest Agent ───────────────────────────────────────────────────────

def _fetch_gmail_summary(service) -> str:
    """Fetches the 5 most recent unread emails and returns a brief summary string."""
    try:
        results = service.users().messages().list(
            userId="me", q="is:unread", maxResults=5
        ).execute()
        messages = results.get("messages", [])
        if not messages:
            return "No new emails."

        summaries = []
        for msg in messages[:5]:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["Subject", "From"]
            ).execute()
            headers = {h["name"]: h["value"] for h in detail.get("payload", {}).get("headers", [])}
            subject = headers.get("Subject", "No Subject")
            sender = headers.get("From", "Unknown Sender")
            # Truncate long values
            sender_short = sender.split("<")[0].strip()[:30]
            summaries.append(f'"{subject[:60]}" from {sender_short}')

        return f"{len(messages)} unread emails. Top messages: " + "; ".join(summaries[:3]) + "."
    except Exception as e:
        logger.warning(f"Gmail fetch failed: {e}")
        return "Could not retrieve emails."


def _fetch_calendar_events(service) -> str:
    """Fetches today's Google Calendar events."""
    try:
        now = datetime.datetime.utcnow()
        end_of_day = now.replace(hour=23, minute=59, second=59)
        time_min = now.isoformat() + "Z"
        time_max = end_of_day.isoformat() + "Z"

        events_result = service.events().list(
            calendarId="primary", timeMin=time_min, timeMax=time_max,
            maxResults=10, singleEvents=True, orderBy="startTime"
        ).execute()
        events = events_result.get("items", [])

        if not events:
            return "No events on your calendar today."

        event_strs = []
        for event in events:
            start = event["start"].get("dateTime", event["start"].get("date", ""))
            if "T" in start:
                # Parse time for display
                dt = datetime.datetime.fromisoformat(start.replace("Z", "+00:00"))
                local_dt = dt.astimezone()
                time_str = local_dt.strftime("%I:%M %p")
            else:
                time_str = "All day"
            event_strs.append(f'{event.get("summary", "Untitled")} at {time_str}')

        return f"You have {len(events)} event{'s' if len(events) > 1 else ''} today: " + "; ".join(event_strs) + "."
    except Exception as e:
        logger.warning(f"Calendar fetch failed: {e}")
        return "Could not retrieve calendar events."


def _fetch_tasks_summary(service) -> str:
    """Fetches pending Google Tasks."""
    try:
        tasklists = service.tasklists().list().execute()
        lists = tasklists.get("items", [])
        if not lists:
            return "No task lists found."

        pending = []
        for tl in lists[:2]:  # Check first 2 task lists
            tasks = service.tasks().list(
                tasklist=tl["id"], showCompleted=False, maxResults=5
            ).execute()
            for task in tasks.get("items", []):
                if task.get("status") == "needsAction":
                    pending.append(task.get("title", "Unnamed task"))

        if not pending:
            return "No pending tasks."
        return f"{len(pending)} pending task{'s' if len(pending) > 1 else ''}: " + "; ".join(pending[:3]) + "."
    except Exception as e:
        logger.warning(f"Tasks fetch failed: {e}")
        return "Could not retrieve tasks."


def run_morning_digest(
    tts_sentence_queue,
    audio_player,
    allowed_event: Optional[threading.Event] = None
) -> None:
    """
    Fetches Gmail, Calendar, and Tasks data and delivers a spoken morning briefing.

    Args:
        tts_sentence_queue: The queue to send TTS sentences to.
        audio_player: The AudioPlayer instance to check if actively speaking.
        allowed_event: Threading event that is set when the system is idle.
    """
    try:
        logger.info("Morning Digest: starting data collection...")

        # Wait until Friday is not actively in a voice interaction
        if allowed_event is not None:
            allowed_event.wait(timeout=60)  # Wait up to 60s for idle

        if audio_player and audio_player.is_speaking():
            logger.info("Morning Digest: audio busy, skipping for now.")
            return

        creds = _get_google_credentials()

        gmail_summary = "Google credentials not configured."
        calendar_summary = ""
        tasks_summary = ""

        if creds:
            from googleapiclient.discovery import build

            gmail_service = build("gmail", "v1", credentials=creds)
            calendar_service = build("calendar", "v3", credentials=creds)
            tasks_service = build("tasks", "v1", credentials=creds)

            gmail_summary = _fetch_gmail_summary(gmail_service)
            calendar_summary = _fetch_calendar_events(calendar_service)
            tasks_summary = _fetch_tasks_summary(tasks_service)

        today = datetime.date.today().strftime("%A, %B %d")

        # Build the spoken briefing in natural sentences
        briefing_parts = [
            f"Good morning! Today is {today}.",
            f"Here's your briefing.",
            gmail_summary,
            calendar_summary,
            tasks_summary,
            "That's your morning digest. Have a great day!"
        ]

        for sentence in briefing_parts:
            if sentence:
                tts_sentence_queue.put(sentence)
                logger.info(f"Morning Digest: queued: '{sentence}'")

    except Exception as e:
        logger.exception(f"Morning Digest failed: {e}")


# ── Scheduler ─────────────────────────────────────────────────────────────────

class ScheduledTaskRunner:
    """
    Background daemon thread that manages cron-like scheduled tasks.

    Tasks are defined as dicts with:
      - "name": str
      - "hour": int (24h format)
      - "minute": int
      - "func": callable
    """

    def __init__(self):
        self._tasks: List[Dict[str, Any]] = []
        self._last_run: Dict[str, datetime.date] = {}
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def add_task(self, name: str, hour: int, minute: int, func: Callable) -> None:
        """Registers a daily task to run at the specified time."""
        self._tasks.append({
            "name": name,
            "hour": hour,
            "minute": minute,
            "func": func
        })
        logger.info(f"Scheduled task registered: '{name}' at {hour:02d}:{minute:02d} daily.")

    def start(self) -> None:
        """Starts the background scheduler thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("ScheduledTaskRunner started.")

    def stop(self) -> None:
        """Stops the scheduler."""
        self._running = False

    def trigger_now(self, task_name: str) -> bool:
        """Manually fires a named task immediately (useful for testing)."""
        for task in self._tasks:
            if task["name"] == task_name:
                logger.info(f"Manually triggering task: '{task_name}'")
                threading.Thread(target=task["func"], daemon=True).start()
                return True
        logger.warning(f"Task '{task_name}' not found.")
        return False

    def _loop(self) -> None:
        """Main loop: checks every 30 seconds if any task is due."""
        while self._running:
            now = datetime.datetime.now()
            today = now.date()

            for task in self._tasks:
                name = task["name"]
                scheduled_hour = task["hour"]
                scheduled_minute = task["minute"]

                # Check if it's the right time and hasn't run today
                if (now.hour == scheduled_hour
                        and now.minute == scheduled_minute
                        and self._last_run.get(name) != today):
                    self._last_run[name] = today
                    logger.info(f"Scheduler: firing task '{name}'")
                    try:
                        threading.Thread(target=task["func"], daemon=True).start()
                    except Exception as e:
                        logger.error(f"Task '{name}' raised: {e}")

            time.sleep(30)  # Check every 30 seconds
