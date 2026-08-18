# Fear & Greed Email Alert (v5 - repeating tiers, combined email)

## What it does

Two independent tiers, both repeating, combined into a single email
whenever they overlap:

**Primary (Fear+):** fires the first time the index has been at
Fear-or-worse for **3 consecutive calendar days**, and fires again
every additional 3-day block the streak continues (day 3, 6, 9, ...).

**Escalation (Extreme Fear):** same pattern, but specifically for
Extreme Fear - fires at day 3, and again every additional 3-day block
it stays extreme.

**If both tiers cross their threshold on the same run, you get ONE
combined email**, not two separate ones - it lists everything that
fired.

### Example walk-through
| Day | Rating | Email sent? |
|---|---|---|
| 1-2 | Fear | No |
| 3 | Fear | Yes - "Fear+" |
| 4-5 | Extreme Fear | No |
| 6 | Extreme Fear | Yes - one combined email: "Fear+ (day 6) + Extreme Fear (day 3)" |
| 7-8 | Fear | No |
| 9 | Fear | Yes - "Fear+" (day 9) |

Checks twice a day on weekdays via GitHub Actions (free).

## Files
- `fear_greed_alert.py` - the checker/alert logic
- `.github/workflows/fear-greed-check.yml` - schedule and settings
- `state.json` - tracks recent history so streaks persist between runs
  (updated and committed automatically by the workflow)

## Setup

### 1. Gmail app password
1. Turn on 2-Step Verification: https://myaccount.google.com/security
2. Create an app password: https://myaccount.google.com/apppasswords
3. Copy the 16-character password.

### 2. Create a private GitHub repo
Upload all files above, preserving folder structure.

### 3. Add repository secrets
Settings -> Secrets and variables -> Actions -> New repository secret:

| Name | Value |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | your Gmail address |
| `SMTP_PASS` | the app password |
| `ALERT_TO` | where alerts should go |

### 4. Allow the workflow to save its progress
Settings -> Actions -> General -> Workflow permissions -> **Read and
write permissions** -> Save.

### 5. Test it
Actions tab -> "Fear & Greed Check" -> Run workflow -> check the log.

## Customizing

| What | Where (in the workflow file) |
|---|---|
| Primary trigger levels | `TRIGGER_LEVELS` |
| Days required for primary alert | `REQUIRED_DAYS` |
| Whether primary alert repeats every N days | `PRIMARY_REPEAT` |
| Escalation trigger levels | `ESCALATION_LEVELS` |
| Days required for escalation alert | `ESCALATION_REQUIRED_DAYS` |
| Whether escalation alert repeats every N days | `ESCALATION_REPEAT` |
| Check frequency | the `cron` lines |

## Known edge cases (not changed, just worth knowing)

- **"Consecutive days" = consecutive recorded checks**, not raw calendar
  days - since it only runs on weekdays, Friday->Monday counts as
  back-to-back with no gap.
- **A failed run doesn't record a day**, so a network hiccup is
  silently skipped rather than breaking the streak count.

## Note

This is an automated data alert, not investment advice. Sustained fear
readings are not a guarantee of a bottom - pair this with your own
research and risk tolerance.
