"""
Fear & Greed Index Email Alert (with streak tracking)
------------------------------------------------------
Checks CNN's Fear & Greed Index. Only sends an email once the trigger
rating (default: Fear or Extreme Fear) has held for N consecutive
CALENDAR DAYS (default: 2) - not just N consecutive checks, so running
twice a day doesn't double-count the same day.

State (recent history + last alert sent) is stored in state.json,
which the GitHub Actions workflow commits back to the repo after
each run, so the streak survives between runs.

Required environment variables:
    SMTP_HOST   e.g. smtp.gmail.com
    SMTP_PORT   e.g. 587
    SMTP_USER   the email address you send FROM
    SMTP_PASS   an app password (NOT your normal account password)
    ALERT_TO    the email address to send the alert TO

Optional environment variables:
    TRIGGER_LEVELS   comma-separated, default "Fear,Extreme Fear"
    REQUIRED_DAYS    consecutive calendar days needed, default "2"
    STATE_FILE       path to state file, default "state.json"
"""

import json
import os
import smtplib
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.mime.text import MIMEText

CNN_URL = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata/"
# Public proxy fallback: routes the request through a different server so it
# isn't coming from GitHub Actions' well-known (and sometimes-blocked) IP range.
PROXY_URL = "https://api.allorigins.win/raw?url=" + urllib.parse.quote(CNN_URL, safe="")
HISTORY_KEEP_DAYS = 14  # how much history to retain in state.json

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.cnn.com/markets/fear-and-greed",
    "Origin": "https://www.cnn.com",
    "Connection": "keep-alive",
}


def _fetch_json(url):
    req = urllib.request.Request(url, headers=BROWSER_HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def fetch_fear_greed():
    """Try fetching directly first; if that's blocked, fall back to a
    public proxy (changes the requesting IP, which sidesteps IP-based
    blocks that don't respond to header changes alone)."""
    urls_to_try = [CNN_URL, PROXY_URL, CNN_URL]
    last_error = None
    for i, url in enumerate(urls_to_try):
        try:
            data = _fetch_json(url)
            current = data["fear_and_greed"]
            score = round(float(current["score"]), 1)
            rating = current["rating"].title()
            return score, rating
        except Exception as e:
            last_error = e
            print(f"Attempt {i + 1} failed ({'proxy' if url == PROXY_URL else 'direct'}): {e}")
            if i < len(urls_to_try) - 1:
                time.sleep(3)
    raise last_error


def load_state(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return {"history": [], "last_alert": None}


def save_state(path, state):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def update_history(state, today_str, score, rating, trigger_set):
    """Record today's rating. If today's entry already exists, keep the
    'worse' (more trigger-worthy) reading so a single Neutral blip during
    the day doesn't erase an earlier Fear reading."""
    history = state["history"]
    is_trigger_now = rating.lower() in trigger_set

    existing = next((h for h in history if h["date"] == today_str), None)
    if existing:
        existing_is_trigger = existing["rating"].lower() in trigger_set
        if is_trigger_now and not existing_is_trigger:
            existing["rating"] = rating
            existing["score"] = score
    else:
        history.append({"date": today_str, "rating": rating, "score": score})

    history.sort(key=lambda h: h["date"])
    state["history"] = history[-HISTORY_KEEP_DAYS:]
    return state


def compute_streak(history, trigger_set):
    """Count consecutive calendar days, ending today, where the rating
    was in the trigger set."""
    streak = 0
    streak_start = None
    for entry in reversed(history):
        if entry["rating"].lower() in trigger_set:
            streak += 1
            streak_start = entry["date"]
        else:
            break
    return streak, streak_start


def send_email(subject: str, body: str):
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    alert_to = os.environ["ALERT_TO"]

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = alert_to

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls(context=context)
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [alert_to], msg.as_string())


def main():
    trigger_levels = os.environ.get("TRIGGER_LEVELS", "Fear,Extreme Fear")
    trigger_set = {lvl.strip().lower() for lvl in trigger_levels.split(",")}
    required_days = int(os.environ.get("REQUIRED_DAYS", "2"))
    state_file = os.environ.get("STATE_FILE", "state.json")

    try:
        score, rating = fetch_fear_greed()
    except Exception as e:
        print(f"ERROR: could not fetch Fear & Greed data: {e}", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    now_str = now.strftime("%Y-%m-%d %H:%M UTC")

    print(f"[{now_str}] Score: {score} ({rating})")

    state = load_state(state_file)
    state = update_history(state, today_str, score, rating, trigger_set)
    streak, streak_start = compute_streak(state["history"], trigger_set)

    print(f"Current streak: {streak} day(s) in trigger levels (need {required_days}).")

    if streak >= required_days:
        last_alert = state.get("last_alert")
        already_alerted_this_streak = (
            last_alert is not None and last_alert.get("streak_start") == streak_start
        )
        if not already_alerted_this_streak:
            subject = f"Fear & Greed Alert: {rating} for {streak} day(s)"
            body = (
                f"The CNN Fear & Greed Index has been at '{rating}' or worse "
                f"for {streak} consecutive day(s) (since {streak_start}).\n\n"
                f"Current score: {score} ({rating})\n"
                f"Checked at: {now_str}\n"
                f"Source: https://www.cnn.com/markets/fear-and-greed\n\n"
                f"This is an automated alert, not investment advice."
            )
            try:
                send_email(subject, body)
                print("Alert email sent.")
                state["last_alert"] = {
                    "date": today_str,
                    "rating": rating,
                    "streak_start": streak_start,
                }
            except Exception as e:
                print(f"ERROR: could not send email: {e}", file=sys.stderr)
                save_state(state_file, state)
                sys.exit(1)
        else:
            print("Already alerted for this streak - skipping to avoid spam.")
    else:
        print("Streak requirement not met - no alert sent.")

    save_state(state_file, state)


if __name__ == "__main__":
    main()
