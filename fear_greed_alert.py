"""
Fear & Greed Index Email Alert (repeating tiers, combined email)
-------------------------------------------------------------------
Checks CNN's Fear & Greed Index. Evaluates two independent tiers:

  1. PRIMARY: fires the first time the rating has held Fear-or-worse
     for REQUIRED_DAYS consecutive calendar days, and fires again
     every additional REQUIRED_DAYS block the streak continues
     (day 3, day 6, day 9, ...). Resets when the streak breaks.

  2. ESCALATION: same repeating behavior, but specifically for
     Extreme Fear (ESCALATION_REQUIRED_DAYS consecutive days, then
     every additional block).

If BOTH tiers trigger on the same run, only ONE combined email is
sent (not two separate emails) - it lists whichever tier(s) fired.

State (recent history + last alerts sent) is stored in state.json,
which the GitHub Actions workflow commits back to the repo after
each run, so streaks survive between runs.

Required environment variables:
    SMTP_HOST   e.g. smtp.gmail.com
    SMTP_PORT   e.g. 587
    SMTP_USER   the email address you send FROM
    SMTP_PASS   an app password (NOT your normal account password)
    ALERT_TO    the email address to send the alert TO

Optional environment variables:
    TRIGGER_LEVELS            comma-separated, default "Fear,Extreme Fear"
    REQUIRED_DAYS              default "3"
    PRIMARY_REPEAT             default "true"
    ESCALATION_LEVELS          comma-separated, default "Extreme Fear"
    ESCALATION_REQUIRED_DAYS   default "3"
    ESCALATION_REPEAT          default "true"
    STATE_FILE                 default "state.json"
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
HISTORY_KEEP_DAYS = 30  # how much history to retain in state.json

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
            state = json.load(f)
    else:
        state = {}
    state.setdefault("history", [])
    state.setdefault("last_alert_primary", None)
    state.setdefault("last_alert_escalation", None)
    return state


def save_state(path, state):
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def update_history(state, today_str, score, rating):
    """Record today's rating, keeping the most severe (lowest score)
    reading seen so far today, so a single less-severe check later in
    the day doesn't erase an earlier, more severe reading."""
    history = state["history"]
    existing = next((h for h in history if h["date"] == today_str), None)
    if existing:
        if score < existing["score"]:
            existing["score"] = score
            existing["rating"] = rating
    else:
        history.append({"date": today_str, "rating": rating, "score": score})

    history.sort(key=lambda h: h["date"])
    state["history"] = history[-HISTORY_KEEP_DAYS:]
    return state


def compute_streak(history, level_set):
    """Count consecutive calendar days, ending today, where the rating
    was in the given level set. NOTE: 'consecutive' means consecutive
    RECORDED entries - weekends and any day the check didn't run are
    simply absent from history, not treated as a break."""
    streak = 0
    streak_start = None
    for entry in reversed(history):
        if entry["rating"].lower() in level_set:
            streak += 1
            streak_start = entry["date"]
        else:
            break
    return streak, streak_start


def evaluate_tier(state, state_key, label, level_set, required_days, repeat):
    """Work out whether this tier should fire, WITHOUT sending anything
    or mutating state yet. Returns a dict describing the result."""
    streak, streak_start = compute_streak(state["history"], level_set)
    print(f"[{label}] streak: {streak} day(s) (need {required_days}, repeat={repeat}).")

    result = {
        "label": label, "state_key": state_key, "streak": streak,
        "streak_start": streak_start, "should_fire": False, "multiple": None,
    }

    if streak < required_days or streak_start is None:
        return result

    current_multiple = streak // required_days
    last_alert = state.get(state_key)
    is_same_streak = last_alert is not None and last_alert.get("streak_start") == streak_start
    last_multiple = last_alert.get("multiple", 0) if is_same_streak else 0

    should_fire = (not is_same_streak) or (repeat and current_multiple > last_multiple)
    if not should_fire:
        print(f"[{label}] already alerted for this streak/block - skipping.")
        return result

    result["should_fire"] = True
    result["multiple"] = current_multiple
    return result


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


def build_combined_email(fired_results, score, rating, now_str):
    labels = [r["label"] for r in fired_results]
    subject = f"Fear & Greed Alert: {' + '.join(labels)}"

    sections = []
    for r in fired_results:
        sections.append(
            f"- {r['label']}: {r['streak']} consecutive day(s) (since {r['streak_start']})"
        )

    body = (
        "The CNN Fear & Greed Index has triggered the following alert(s):\n\n"
        + "\n".join(sections)
        + f"\n\nCurrent score: {score} ({rating})\n"
        f"Checked at: {now_str}\n"
        f"Source: https://www.cnn.com/markets/fear-and-greed\n\n"
        f"This is an automated alert, not investment advice."
    )
    return subject, body


def _env_bool(name, default):
    return os.environ.get(name, str(default)).strip().lower() in ("1", "true", "yes")


def main():
    trigger_levels = os.environ.get("TRIGGER_LEVELS", "Fear,Extreme Fear")
    trigger_set = {lvl.strip().lower() for lvl in trigger_levels.split(",")}
    required_days = int(os.environ.get("REQUIRED_DAYS", "3"))
    primary_repeat = _env_bool("PRIMARY_REPEAT", True)

    escalation_levels = os.environ.get("ESCALATION_LEVELS", "Extreme Fear")
    escalation_set = {lvl.strip().lower() for lvl in escalation_levels.split(",")}
    escalation_required_days = int(os.environ.get("ESCALATION_REQUIRED_DAYS", "3"))
    escalation_repeat = _env_bool("ESCALATION_REPEAT", True)

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
    state = update_history(state, today_str, score, rating)

    primary_result = evaluate_tier(
        state, "last_alert_primary", "Fear+", trigger_set, required_days, primary_repeat,
    )
    escalation_result = evaluate_tier(
        state, "last_alert_escalation", "Extreme Fear", escalation_set,
        escalation_required_days, escalation_repeat,
    )

    fired = [r for r in (primary_result, escalation_result) if r["should_fire"]]

    if fired:
        subject, body = build_combined_email(fired, score, rating, now_str)
        try:
            send_email(subject, body)
            print(f"Combined alert email sent for: {[r['label'] for r in fired]}")
            for r in fired:
                state[r["state_key"]] = {
                    "date": today_str,
                    "rating": rating,
                    "streak_start": r["streak_start"],
                    "multiple": r["multiple"],
                }
        except Exception as e:
            print(f"ERROR: could not send combined email: {e}", file=sys.stderr)
    else:
        print("No tier crossed its threshold this run - no email sent.")

    save_state(state_file, state)


if __name__ == "__main__":
    main()
