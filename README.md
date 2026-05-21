# a2script

Small Python scrapers that build daily local event digests and optionally email them through SMTP.

This repo currently includes two scripts:

- `aascript.py`: Ann Arbor events from AADL, Ann Arbor Observer, and Ann Arbor With Kids
- `elscript.py`: East Lansing toddler events from CADL, ELPL, and 517 Living

## Requirements

Install dependencies:

```bash
python3 -m pip install requests beautifulsoup4 python-dateutil pytz python-dotenv streamlit
```

## Setup

Copy `.env.example` to `.env` and fill in your SMTP settings:

```bash
cp .env.example .env
```

If you use Gmail, generate an app-specific password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

## Usage

Run the Ann Arbor digest for today:

```bash
python3 aascript.py
```

Run the East Lansing digest for today:

```bash
python3 elscript.py
```

Run the GUI:

```bash
python3 -m streamlit run app.py
```

Fetch a specific date with either script:

```bash
python3 aascript.py --date 2026-05-05
python3 elscript.py --date 2026-05-05
```

Both scripts print the digest to stdout. If email is enabled and SMTP is configured, they also send it by email.

The GUI lets you:

- choose `Ann Arbor` or `East Lansing`
- pick a date
- preview the digest in the browser
- manually send the previewed digest by email

## Configuration

Both scripts load `.env` from the repository root and share the same SMTP settings.

| Variable | Default | Used By | Purpose |
|---|---|---|---|
| `EMAIL_ENABLED` | `true` | both | Set to `false` to skip email sending |
| `FORCE_SEND` | `false` | `aascript.py` | Bypass the Ann Arbor geo-check |
| `SMTP_HOST` | `smtp.gmail.com` | both | SMTP host |
| `SMTP_PORT` | `587` | both | SMTP port |
| `SMTP_USER` | none | both | SMTP username |
| `SMTP_PASS` | none | both | SMTP password or Gmail app password |
| `FROM_EMAIL` | none | both | Sender address |
| `TO_EMAIL` | none | both | Comma-separated recipient list |

## Behavior Notes

`aascript.py` only sends when `EMAIL_ENABLED=true` and your IP appears to be in the Ann Arbor area, unless `FORCE_SEND=true`.

`elscript.py` has no location check. It always builds the digest, prints it, and sends email when `EMAIL_ENABLED=true` and SMTP is configured.

If SMTP settings are missing, both scripts still print the digest and silently skip sending email.
