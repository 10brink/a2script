#!/usr/bin/env python3
"""
Daily Ann Arbor events digest:
- AADL
- Ann Arbor Observer
- Ann Arbor With Kids

Requirements:
  pip install requests beautifulsoup4 python-dateutil pytz python-dotenv

Email config:
  Copy .env.example to .env and fill in your Gmail credentials.
  Uses app-specific password (not your regular Gmail password).
"""

from __future__ import annotations

import os
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime, date
from email.message import EmailMessage
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import urljoin

import pytz
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Load .env from the same directory as this script
load_dotenv(Path(__file__).parent / ".env")


TZ = pytz.timezone("America/Detroit")
UA = "a2-events-digest/1.0 (personal script; contact: you@example.com)"
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


def today_tokens(d: date) -> dict:
    # Example formats seen on sites:
    # - "Sunday March 1, 2026" (AADL)
    # - "## March 1, 2026" (Observer)
    # - "### Sunday, March 1, 2026" (AAWK)
    weekday = d.strftime("%A")
    month = d.strftime("%B")
    daynum = str(int(d.strftime("%d")))
    year = d.strftime("%Y")
    return {
        "weekday": weekday,
        "month": month,
        "daynum": daynum,
        "year": year,
        "aadl_line": f"{weekday} {month} {daynum}, {year}",
        "observer_heading": f"{month} {daynum}, {year}",
        "aawk_heading": f"{weekday}, {month} {daynum}, {year}",
    }


def parse_aadl(d: date) -> List[Event]:
    url = "https://aadl.org/events-feed/upcoming"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    tok = today_tokens(d)
    # AADL events-feed pages contain repeated blocks; easiest robust method:
    # Look for text nodes containing the exact date line, then climb to the containing block.
    events: List[Event] = []
    date_re = re.compile(re.escape(tok["aadl_line"]))

    for node in soup.find_all(string=date_re):
        # The date line usually appears in a block that also includes the title near it.
        block = node.parent
        # climb a bit to a reasonable container
        for _ in range(6):
            if block and block.name in ("article", "div", "li"):
                # heuristic: if it contains an <a> that looks like an event title
                break
            block = block.parent

        if not block:
            continue

        # Find the nearest "best" title link inside the block
        a = block.find("a")
        title = a.get_text(" ", strip=True) if a else block.get_text(" ", strip=True)[:120]
        href = urljoin(url, a["href"]) if a and a.has_attr("href") else ""

        # Extract time range from the date line’s surroundings
        text = block.get_text(" ", strip=True)
        # common pattern: "Sunday March 1, 2026: 11:00am to 11:45am."
        m = re.search(r":\s*([0-9]{1,2}:[0-9]{2}(?:am|pm))\s*to\s*([0-9]{1,2}:[0-9]{2}(?:am|pm))", text, re.I)
        when = f"{m.group(1)}–{m.group(2)}" if m else "Time listed on page"

        # location often appears like "Westgate Branch: West Side Room"
        loc = ""
        m2 = re.search(r"\.\s*([A-Za-z0-9’'&\-\s]+Branch|Downtown Library|Pittsfield Branch|Traverwood Branch|Malletts Creek Branch)\s*:\s*([^\.]+)\.", text)
        if m2:
            loc = f"{m2.group(1)}: {m2.group(2).strip()}"

        # de-dup by (title, when)
        e = Event(source="AADL", title=title, when=when, location=loc, url=href)
        if not any(x.title == e.title and x.when == e.when for x in events):
            events.append(e)

    return events


def parse_observer(d: date) -> List[Event]:
    url = (
        "https://annarborobserver.com/calendar/"
        f"?cid=main-calendar&dy={int(d.strftime('%d'))}&mcat=all&month={int(d.strftime('%m'))}"
        f"&time=day&yr={d.strftime('%Y')}"
    )
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    # The day view has "## <Month> <d>, <yyyy>" heading then a list of events.
    # Titles appear as H5 with an <a>.
    events: List[Event] = []

    # Find all h5 headers for events
    for h in soup.find_all(re.compile("^h[1-6]$")):
        # Observer event titles are often "##### <a>Title</a>"
        a = h.find("a")
        if not a:
            continue

        title = a.get_text(" ", strip=True)
        href = urljoin(url, a["href"]) if a.has_attr("href") else ""

        # The event time is usually in the preceding text near the title (e.g., "8:00 am" line)
        # We'll look at a small window of previous siblings text.
        when = ""
        location = ""

        # Look up to a few previous strings
        prev_texts = []
        cur = h
        for _ in range(6):
            cur = cur.find_previous(string=True)
            if not cur:
                break
            t = str(cur).strip()
            if t:
                prev_texts.append(t)
        blob = " ".join(prev_texts)

        mt = re.search(r"\b([0-9]{1,2}:[0-9]{2}\s*(?:am|pm))\b|\b([0-9]{1,2}\s*(?:am|pm))\b", blob, re.I)
        when = mt.group(0) if mt else "Time listed on page"

        # Optional: capture "Add this event to your calendar: ... iCal" link nearby
        # (nice-to-have; not required)

        events.append(Event(source="Ann Arbor Observer", title=title, when=when, location=location, url=href))

    # crude de-dup (Observer repeats headings sometimes)
    uniq: List[Event] = []
    seen = set()
    for e in events:
        key = (e.title, e.when)
        if key not in seen:
            seen.add(key)
            uniq.append(e)
    return uniq


def parse_aawk(d: date) -> List[Event]:
    url = "https://annarborwithkids.com/events/"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    tok = today_tokens(d)
    target = tok['aawk_heading']  # e.g., "Sunday, March 1, 2026"

    # Find the h3 heading for today's date
    date_heading = None
    for h3 in soup.find_all("h3"):
        if h3.get_text(strip=True) == target:
            date_heading = h3
            break

    if not date_heading:
        return []

    # Find the table that follows the date heading
    table = date_heading.find_next("table")
    if not table:
        return []

    events: List[Event] = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        # Find the event link (usually in a td, could be in h3 or directly)
        event_link = None
        title = ""
        for cell in cells:
            a = cell.find("a", href=re.compile(r"^https://annarborwithkids\.com/events/[^/]+/$"))
            if a:
                event_link = a
                title = a.get_text(strip=True)
                break

        if not title:
            continue

        href = event_link["href"] if event_link else url

        # Extract time from the date/time cell (first cell with "March X" pattern)
        when = "Time listed on page"
        for cell in cells:
            text = cell.get_text(" ", strip=True)
            # Look for time pattern like "10:00am-11:00am" or "10:00am - 11:00am"
            m = re.search(r"(\d{1,2}:\d{2}\s*(?:am|pm))\s*[-–]\s*(\d{1,2}:\d{2}\s*(?:am|pm))", text, re.I)
            if m:
                when = f"{m.group(1)}–{m.group(2)}"
                break
            # Single time
            m = re.search(r"(\d{1,2}:\d{2}\s*(?:am|pm))", text, re.I)
            if m:
                when = m.group(1)
                break

        events.append(Event(source="Ann Arbor With Kids", title=title, when=when, location="", url=href))

    return events


def format_digest(d: date, events: List[Event]) -> str:
    header = f"Events for {d.strftime('%A, %B %d, %Y')} (America/Detroit)"
    out = [header, "=" * len(header), ""]
    if not events:
        out.append("No events found.")
        return "\n".join(out)

    # group by source
    by_source = {}
    for e in events:
        by_source.setdefault(e.source, []).append(e)

    source_order = ["AADL", "Ann Arbor With Kids", "Ann Arbor Observer"]
    for src in source_order:
        if src not in by_source:
            continue
        out.append(f"{src}")
        out.append("-" * len(src))
        for e in by_source[src]:
            out.append(e.line())
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def is_in_ann_arbor() -> bool:
    """Check if current IP is near Ann Arbor using free geolocation API."""
    try:
        r = requests.get("http://ip-api.com/json/", timeout=10)
        data = r.json()
        if data.get("status") != "success":
            return True  # default to sending if check fails

        city = data.get("city", "").lower()
        region = data.get("regionName", "").lower()

        # Ann Arbor area cities
        aa_cities = ["ann arbor", "ypsilanti", "saline", "dexter", "chelsea", "milan"]
        return any(c in city for c in aa_cities) or (region == "michigan" and "arbor" in city)
    except Exception:
        return True  # default to sending if check fails


def maybe_send_email(subject: str, body: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    to_email = os.getenv("TO_EMAIL")
    from_email = os.getenv("FROM_EMAIL")

    if not (smtp_host and to_email and from_email):
        return  # email not configured

    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")

    # Support comma-separated recipients
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
    # Skip everything if email is disabled
    if os.getenv("EMAIL_ENABLED", "true").lower() != "true":
        print("Email disabled — skipping.")
        return

    # Skip if not in Ann Arbor (unless force send)
    if os.getenv("FORCE_SEND", "false").lower() != "true":
        if not is_in_ann_arbor():
            print("Not in Ann Arbor area — skipping.")
            return

    d = datetime.now(TZ).date()
    events: List[Event] = []
    events += parse_aadl(d)
    events += parse_observer(d)
    events += parse_aawk(d)

    digest = format_digest(d, events)
    print(digest)

    maybe_send_email(
        subject=f"Today in Ann Arbor: {d.strftime('%a %b %d')}",
        body=digest
    )


if __name__ == "__main__":
    main()