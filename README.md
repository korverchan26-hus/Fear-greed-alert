# Fear & Greed Email Alert (v2 - streak-based)

Emails you when the CNN Fear & Greed Index has been at **Fear or Extreme
Fear for 2+ consecutive calendar days** - not on the first blip, so you
don't get pinged by noise. Checks twice a day on weekdays via GitHub
Actions (free), and won't re-alert every check once you've already been
notified for that streak.

## Files
- `fear_greed_alert.py` - the checker/alert logic
- `.github/workflows/fear-greed-check.yml` - the schedule
- `state.json` - tracks recent history so streaks persist between runs
  (the workflow updates and commits this automatically - you don't need
  to touch it)

## Setup

### 1. Gmail app password
1. Turn on 2-Step Verification: https://myaccount.google.com/security
2. Create an app password: https://myaccount.google.com/apppasswords
3. Copy the 16-character password.

### 2. Create a private GitHub repo
Upload all files above, preserving folder structure (`.github/workflows/...`
and `state.json` at the root alongside `fear_greed_alert.py`).

### 3. Add repository secrets
Settings → Secrets and variables → Actions → New repository secret:

| Name | Value |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | your Gmail address |
| `SMTP_PASS` | the app password |
| `ALERT_TO` | where alerts should go |

### 4. Test it
Actions tab → "Fear & Greed Check" → Run workflow → check the log.
You should see the current score, the streak count, and whether an
email was sent. After it runs, check that `state.json` in your repo
was updated with today's entry - that confirms the commit-back step
works.

## Customizing

| What | Where |
|---|---|
| Trigger levels | `TRIGGER_LEVELS` in the workflow (e.g. `"Extreme Fear"` only) |
| Days required before alerting | `REQUIRED_DAYS` in the workflow (e.g. `"3"`) |
| Check frequency | the `cron` lines in the workflow |

## How the streak logic works

- Each run records today's rating in `state.json`.
- If today already has an entry and the new rating is more severe
  (e.g. moved from Neutral to Fear later in the day), it updates to
  the worse reading - so a single good moment doesn't erase the day.
- The streak counts backward from today through consecutive days that
  were all in your trigger levels.
- Once you're alerted for a streak, you won't get alerted again until
  either the streak breaks and restarts, or (in future versions) it
  escalates further - this prevents twice-daily spam while you're
  sitting in Fear for two weeks straight.

## Note

This is an automated data alert, not investment advice. A 2-day Fear
streak is not a guarantee of a bottom - pair this with your own
research and risk tolerance.
