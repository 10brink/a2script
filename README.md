# a2script

Daily Ann Arbor events digest delivered to your inbox.

Scrapes events from:
- [AADL](https://aadl.org/events-feed/upcoming) (Ann Arbor District Library)
- [Ann Arbor Observer](https://annarborobserver.com/calendar/)
- [Ann Arbor With Kids](https://annarborwithkids.com/events/)

## Setup

1. Install dependencies:
   ```bash
   pip install requests beautifulsoup4 python-dateutil pytz python-dotenv
   ```

2. Copy `.env.example` to `.env` and fill in your Gmail credentials:
   ```bash
   cp .env.example .env
   ```

3. Generate a Gmail app-specific password at https://myaccount.google.com/apppasswords

## Usage

Run manually:
```bash
python3 aascript.py
```

Or schedule with launchd (macOS) or cron.

## Configuration

| Variable | Description |
|----------|-------------|
| `EMAIL_ENABLED` | Set to `false` to disable emails entirely |
| `FORCE_SEND` | Set to `true` to send regardless of location |

The script checks your IP location and only sends when you're in the Ann Arbor area. Use `FORCE_SEND=true` when you're away but still want the digest.
