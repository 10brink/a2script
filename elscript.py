#!/usr/bin/env python3
# Daily East Lansing toddler events digest: CADL, ELPL, 517 Living.
# Scrapes three sources, prints to stdout, and optionally emails a digest.
#
# Requirements:
#   pip install requests beautifulsoup4 pytz python-dotenv
#
# Configuration:
#   Shares .env with aascript.py.
#   Set EMAIL_ENABLED=false to print only (no email).
#   Email is always sent when configured — no geo check.

from __future__ import annotations

import json
import os
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import List
from urllib.parse import urljoin

import pytz
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load .env from the same directory as this script
load_dotenv(Path(__file__).parent / ".env")

TZ = pytz.timezone("America/Detroit")
UA = "el-events-digest/1.0 (personal script)"
TIMEOUT = 25


@dataclass
class Event:
    source: str
    title: str
    when: str
    location: str = ""
    url: str = ""

    def line(self) -> str:
        bits = [f"- {self.title} — {self.when}"]
        if self.location:
            bits.append(f" @ {self.location}")
        if self.url:
            bits.append(f" ({self.url})")
        return "".join(bits)


def fetch(url: str) -> str:
    r = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def _fmt_time(dt: datetime) -> str:
    """Format datetime as '10:00am' (no leading zero)."""
    return dt.strftime("%I:%M%p").lstrip("0").lower()


def _parse_cadl_html(html: str) -> dict:
    """Extract the libCalEventsCalendar events JSON object from a CADL page."""
    cal_idx = html.find("libCalEventsCalendar")
    if cal_idx == -1:
        return {}
    events_key_idx = html.find("events:", cal_idx)
    if events_key_idx == -1:
        return {}
    start_brace = html.find("{", events_key_idx)
    if start_brace == -1:
        return {}
    depth = 0
    end_brace = -1
    for i in range(start_brace, min(start_brace + 500_000, len(html))):
        if html[i] == "{":
            depth += 1
        elif html[i] == "}":
            depth -= 1
            if depth == 0:
                end_brace = i
                break
    if end_brace == -1:
        return {}
    try:
        return json.loads(html[start_brace : end_brace + 1])
    except json.JSONDecodeError:
        return {}


def parse_cadl(d: date) -> List[Event]:
    """
    Scrape CADL toddler events via their LibCal-powered events page.
    The page embeds a JS object (libCalEventsCalendar) with unquoted keys;
    the nested `events:` value is valid JSON containing the events array.
    Paginates until the target date is reached (server caps per_page at 15).
    """
    today_str = d.strftime("%Y-%m-%d")
    base = "https://www.cadl.org/events/all-events?audience=11171&per_page=15"

    raw: List[dict] = []
    for page in range(1, 20):  # cap at 20 pages (~300 events) to avoid infinite loop
        html = fetch(f"{base}&page={page}")
        data = _parse_cadl_html(html)
        batch = data.get("events", [])
        if not isinstance(batch, list) or not batch:
            break
        raw.extend(batch)
        # Stop once we've seen events on or past the target date
        last_start = batch[-1].get("start", "")
        if isinstance(last_start, str) and last_start >= today_str:
            break

    events: List[Event] = []
    for ev in raw:
        start_field = ev.get("start", "")
        if not isinstance(start_field, str) or not start_field.startswith(today_str):
            continue

        title = ev.get("title", "").strip()
        if not title:
            continue

        # Parse start/end times.
        try:
            start_dt = datetime.strptime(start_field, "%Y-%m-%d %H:%M:%S")
            end_field = ev.get("end", "")
            end_dt = datetime.strptime(end_field, "%Y-%m-%d %H:%M:%S") if end_field else None
            when = f"{_fmt_time(start_dt)}–{_fmt_time(end_dt)}" if end_dt else _fmt_time(start_dt)
        except (ValueError, TypeError):
            when = "Time listed on page"

        # Location: branch (campus) + room (location).
        loc_parts: List[str] = []
        campus = ev.get("campus") or {}
        campus_name = (campus.get("name") or "").strip()
        if campus_name:
            loc_parts.append(campus_name)
        location = ev.get("location") or {}
        loc_name = (location.get("name") or "").strip()
        if loc_name and loc_name.lower() not in ("in library", ""):
            loc_parts.append(loc_name)
        loc = ", ".join(loc_parts)

        href = ev.get("publicUrl", "")

        e = Event(source="CADL", title=title, when=when, location=loc, url=href)
        if not any(x.title == e.title and x.when == e.when for x in events):
            events.append(e)

    return events


def parse_517living(d: date) -> List[Event]:
    """
    Fetch 517 Living events for today via the Tockify calendar API.
    517 Living embeds a Tockify calendar at calendar.517living.com.
    """
    # Build epoch-ms bounds for today in Eastern time.
    today_start = TZ.localize(datetime(d.year, d.month, d.day, 0, 0, 0))
    today_end = today_start + timedelta(days=1)
    start_ms = int(today_start.timestamp() * 1000)
    end_ms = int(today_end.timestamp() * 1000)

    api_url = (
        f"https://api.tockify.com/api/ngevent"
        f"?calname=517calendar&max=50&startms={start_ms}&endms={end_ms}"
    )

    try:
        r = requests.get(api_url, headers={"User-Agent": UA}, timeout=TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return []

    # The Tockify API wraps events in {"items": [...]}
    if isinstance(data, list):
        items = data
    else:
        items = data.get("items", data.get("events", []))

    events: List[Event] = []
    for item in items:
        content = item.get("content") or {}
        title = (content.get("summary") or {}).get("text", "").strip()
        if not title:
            continue

        when_data = item.get("when") or {}
        start_ms_ev = (when_data.get("start") or {}).get("millis")
        end_ms_ev = (when_data.get("end") or {}).get("millis")

        if start_ms_ev:
            start_dt = datetime.fromtimestamp(start_ms_ev / 1000, tz=TZ)
            if end_ms_ev:
                end_dt = datetime.fromtimestamp(end_ms_ev / 1000, tz=TZ)
                when = f"{_fmt_time(start_dt)}–{_fmt_time(end_dt)}"
            else:
                when = _fmt_time(start_dt)
        else:
            when = "Time listed on page"

        loc_parts: List[str] = []
        place = (content.get("place") or "").strip()
        if place:
            loc_parts.append(place)
        address = (content.get("address") or "").strip()
        if address and address != place:
            loc_parts.append(address)
        loc = ", ".join(loc_parts)

        # Prefer a custom event link; fall back to Tockify event permalink.
        href = (content.get("customButtonLink") or "").strip()
        if not href:
            eid = (item.get("eid") or {}).get("uid", "")
            if eid:
                href = f"https://calendar.517living.com/p/517calendar/event/{eid}"

        e = Event(source="517 Living", title=title, when=when, location=loc, url=href)
        if not any(x.title == e.title and x.when == e.when for x in events):
            events.append(e)

    return events


def parse_elpl(d: date) -> List[Event]:
    """
    Scrape ELPL toddler events from Bibliocommons.
    Events are rendered as <li> elements with a date-box and <h3> title link.
    """
    date_str = d.strftime("%Y-%m-%d")
    url = (
        f"https://elpl.bibliocommons.com/v2/events"
        f"?audiences=580e781325f273b12a0d10a1"
        f"&startDate={date_str}&endDate={date_str}"
    )
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    # Date matching uses the abbreviated month ("Mar") and bare day ("28").
    today_month = d.strftime("%b")   # e.g. "Mar"
    today_day = str(int(d.strftime("%d")))  # e.g. "28" (no leading zero)

    events: List[Event] = []

    for li in soup.find_all("li"):
        month_el = li.find(class_="date-stamp__month")
        date_el = li.find(class_="date-stamp__day")
        if not (month_el and date_el):
            continue

        ev_month = month_el.get_text(strip=True)
        ev_day = date_el.get_text(strip=True).lstrip("0")
        if ev_month != today_month or ev_day != today_day:
            continue

        h3 = li.find("h3")
        if not h3:
            continue
        a = h3.find("a")
        if not a:
            continue

        title = a.get_text(" ", strip=True)
        href = a.get("href", "")
        if href and not href.startswith("http"):
            href = urljoin("https://elpl.bibliocommons.com", href)

        # Time is in a span.event-time — get_text collapses the comment nodes.
        text = li.get_text(" ", strip=True)
        m = re.search(
            r"(\d{1,2}:\d{2}\s*(?:am|pm))\s*[–\-]\s*(\d{1,2}:\d{2}\s*(?:am|pm))",
            text, re.I
        )
        if m:
            when = f"{m.group(1)}–{m.group(2)}"
        else:
            m2 = re.search(r"(\d{1,2}:\d{2}\s*(?:am|pm))", text, re.I)
            when = m2.group(1) if m2 else "Time listed on page"

        loc = "East Lansing Public Library"

        e = Event(source="ELPL", title=title, when=when, location=loc, url=href)
        if not any(x.title == e.title and x.when == e.when for x in events):
            events.append(e)

    return events


def format_digest(d: date, events: List[Event]) -> str:
    header = f"East Lansing Toddler Events for {d.strftime('%A, %B %d, %Y')}"
    out = [header, "=" * len(header), ""]
    if not events:
        out.append("No events found.")
        return "\n".join(out)

    by_source: dict = {}
    for e in events:
        by_source.setdefault(e.source, []).append(e)

    for src in ["CADL", "ELPL", "517 Living"]:
        if src not in by_source:
            continue
        out.append(src)
        out.append("-" * len(src))
        for e in by_source[src]:
            out.append(e.line())
        out.append("")

    return "\n".join(out).rstrip() + "\n"


def maybe_send_email(subject: str, body: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    to_email = os.getenv("TO_EMAIL")
    from_email = os.getenv("FROM_EMAIL")

    if not (smtp_host and to_email and from_email):
        return  # email not configured

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")

    recipients = [e.strip() for e in to_email.split(",")]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = ", ".join(recipients)
    msg["From"] = from_email
    msg.set_content(body)

    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.starttls()
        if smtp_user and smtp_pass:
            s.login(smtp_user, smtp_pass)
        s.send_message(msg)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="East Lansing toddler events digest")
    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Date to fetch events for (default: today)",
    )
    args = parser.parse_args()

    if args.date:
        try:
            d = date.fromisoformat(args.date)
        except ValueError:
            parser.error(f"Invalid date '{args.date}'. Use YYYY-MM-DD format.")
    else:
        d = datetime.now(TZ).date()

    events: List[Event] = []
    events += parse_cadl(d)
    events += parse_elpl(d)
    events += parse_517living(d)

    digest = format_digest(d, events)
    print(digest)

    if os.getenv("EMAIL_ENABLED", "true").lower() == "true":
        maybe_send_email(
            subject=f"Today in East Lansing: {d.strftime('%a %b %d')}",
            body=digest,
        )


if __name__ == "__main__":
    main()
