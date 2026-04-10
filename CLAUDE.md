# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python script (`aascript.py`) that scrapes three Ann Arbor event sources daily and emails a plain-text digest. No framework, no database — just `requests` + `BeautifulSoup` + `smtplib`.

## Running

```bash
python3 aascript.py
```

Install dependencies first:
```bash
pip install requests beautifulsoup4 python-dateutil pytz python-dotenv
```

Optional: pass `--date YYYY-MM-DD` to fetch events for a specific date instead of today:
```bash
python3 aascript.py --date 2026-04-07
```

## Configuration

Copy `.env.example` to `.env` and fill in Gmail SMTP credentials. Key env vars:

| Variable | Default | Purpose |
|---|---|---|
| `EMAIL_ENABLED` | `true` | Set `false` to skip sending |
| `FORCE_SEND` | `false` | Set `true` to send even when not in Ann Arbor |
| `SMTP_HOST/PORT` | `smtp.gmail.com:587` | SMTP server |
| `SMTP_USER/PASS` | — | Gmail + app-specific password |
| `FROM_EMAIL` / `TO_EMAIL` | — | Sender and comma-separated recipients |

The script geo-checks the current IP via `ip-api.com` and skips sending if outside the Ann Arbor area (bypass with `FORCE_SEND=true`).

## Architecture

Everything lives in `aascript.py`:

- **`Event` dataclass** — source, title, when, location, url
- **`parse_aadl(d)`** — scrapes `aadl.org/events-feed/upcoming`; matches date string, climbs DOM to find containing block, extracts time via regex, location via CSS class heuristics then line-scanning fallback
- **`parse_observer(d)`** — scrapes Observer calendar day-view URL; finds event `<h[1-6]>/<a>` elements, backtracks through previous text nodes for time; filters out "looking for live music" nav link
- **`parse_aawk(d)`** — scrapes `annarborwithkids.com/events/`; finds `<h3>` matching today's date, parses the following `<table>`, optionally fetches individual event pages for venue details
- **`format_digest(d, events)`** — groups by source, emits plain-text output ordered AADL → AAWK → Observer
- **`maybe_send_email(subject, body)`** — SMTP send via `smtplib`; no-ops if env vars are absent
- **`main()`** — parses `--date` arg, checks `EMAIL_ENABLED` first (exits early if disabled), then geo-checks → scrape → format → print → email

---

## elscript.py

A companion script targeting **East Lansing toddler events** from three sources: CADL, ELPL, and 517 Living.

### Running

```bash
python3 elscript.py                    # today
python3 elscript.py --date 2026-04-07  # specific date
```

Same dependencies as `aascript.py`. Shares the same `.env` file. No geo-check — email sends whenever configured.

### Architecture

Everything lives in `elscript.py`:

- **`Event` dataclass** — identical structure to `aascript.py`
- **`parse_cadl(d)`** — scrapes `cadl.org/events/all-events` (audience=11171 for toddlers); the page embeds a `libCalEventsCalendar` JS object with a nested `events:` JSON blob; paginates up to 20 pages (15 events/page) until the target date is reached
- **`parse_elpl(d)`** — scrapes ELPL's Bibliocommons event page filtered by toddler audience and date; finds `<li>` elements with `.date-stamp__month`/`.date-stamp__day` matching today, extracts `<h3>/<a>` title and time via regex; location hardcoded to "East Lansing Public Library"
- **`parse_517living(d)`** — calls the Tockify calendar JSON API (`api.tockify.com`) for the `517calendar` feed, filtering by epoch-ms bounds for today in Eastern time
- **`format_digest(d, events)`** — plain-text output ordered CADL → ELPL → 517 Living
- **`maybe_send_email(subject, body)`** — same SMTP logic as `aascript.py`
- **`main()`** — reads optional positional date arg → scrape → format → print → email (no `EMAIL_ENABLED` check, no geo-check)

### Scraper notes

CADL uses a brace-matching JSON extractor (`_parse_cadl_html`) since the JS object has unquoted keys but the nested `events:` value is valid JSON. 517 Living's Tockify API returns `{"items": [...]}`. De-duplication is by `(title, when)` within each source.

---

## Shared scraper notes

Each parser uses `today_tokens(d)` to build site-specific date strings (the three sites format dates differently). De-duplication is done by `(title, when)` pairs within each source. AAWK falls back to fetching individual event pages (`fetch_aawk_location`) when the listing table lacks venue info.
