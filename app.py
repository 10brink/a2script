#!/usr/bin/env python3

from __future__ import annotations

import os
import re
from datetime import date, datetime
from html import escape
from typing import Any, Callable, Dict, List, Optional, Tuple

import streamlit as st
import streamlit.components.v1 as components

import aascript
import elscript


TZ = aascript.TZ


DigestModule = Dict[str, Any]


CITY_OPTIONS: Dict[str, DigestModule] = {
    "Ann Arbor": {
        "collector": aascript.collect_events,
        "formatter": aascript.format_digest,
        "sender": aascript.maybe_send_email,
        "subject": aascript.subject_for_date,
        "email_enabled": aascript.email_enabled,
        "notes": "Manual sends bypass the Ann Arbor location check used by the CLI auto-send flow.",
    },
    "East Lansing": {
        "collector": elscript.collect_events,
        "formatter": elscript.format_digest,
        "sender": elscript.maybe_send_email,
        "subject": elscript.subject_for_date,
        "email_enabled": elscript.email_enabled,
        "notes": "Email behavior matches the East Lansing CLI flow.",
    },
}


def load_digest(city: str, target_date: date) -> None:
    module = CITY_OPTIONS[city]
    collector: Callable[[date], List[Any]] = module["collector"]
    formatter: Callable[[date, List[Any]], str] = module["formatter"]
    subject_builder: Callable[[date], str] = module["subject"]

    events = collector(target_date)
    digest = formatter(target_date, events)
    st.session_state["selected_city"] = city
    st.session_state["selected_date"] = target_date.isoformat()
    st.session_state["events"] = events
    st.session_state["digest"] = digest
    st.session_state["subject"] = subject_builder(target_date)


def can_send_current_digest(city: str, target_date: date) -> bool:
    return (
        st.session_state.get("selected_city") == city
        and st.session_state.get("selected_date") == target_date.isoformat()
        and bool(st.session_state.get("digest"))
    )


def email_configured() -> bool:
    return all(os.getenv(key) for key in ("SMTP_HOST", "TO_EMAIL", "FROM_EMAIL"))


def parse_time_value(raw_time: str) -> Optional[int]:
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", raw_time.strip(), re.I)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    meridiem = match.group(3).lower()

    if hour == 12:
        hour = 0
    if meridiem == "pm":
        hour += 12

    return hour * 60 + minute


def parse_event_window(when: str) -> Optional[Tuple[int, int]]:
    time_matches = re.findall(r"\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", when, flags=re.I)
    if not time_matches:
        return None

    start = parse_time_value(time_matches[0])
    if start is None:
        return None

    end = parse_time_value(time_matches[1]) if len(time_matches) > 1 else None
    if end is None:
        end = start + 45
    if end <= start:
        end += 12 * 60

    return start, end


def format_minutes(minutes: int) -> str:
    minutes = minutes % (24 * 60)
    hour = minutes // 60
    minute = minutes % 60
    meridiem = "am" if hour < 12 else "pm"
    hour = hour % 12 or 12
    return f"{hour}:{minute:02d}{meridiem}"


def source_class(source: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", source.lower()).strip("-")
    return f"source-{slug}"


def render_calendar(events: List[Any]) -> None:
    timed_events = []
    unknown_events = []

    for event in events:
        window = parse_event_window(event.when)
        if window:
            timed_events.append({"event": event, "start": window[0], "end": window[1]})
        else:
            unknown_events.append(event)

    if not events:
        st.warning("No events found for this date.")
        return

    if not timed_events:
        st.warning("No timed events found. The text view still includes everything returned by the sources.")
        return

    timed_events.sort(key=lambda item: (item["start"], item["end"], item["event"].title))
    grouped_events: List[Dict[str, Any]] = []
    for item in timed_events:
        if not grouped_events or grouped_events[-1]["start"] != item["start"]:
            grouped_events.append({"start": item["start"], "items": []})
        grouped_events[-1]["items"].append(item)

    rows = []
    for group in grouped_events:
        cards = []
        for item in group["items"]:
            event = item["event"]
            href = escape(event.url or "")
            title = escape(event.title)
            source = escape(event.source)
            when = escape(event.when)
            location = escape(event.location)
            link_open = f'<a href="{href}" target="_blank" rel="noopener noreferrer">' if href else "<div>"
            link_close = "</a>" if href else "</div>"
            location_html = f'<div class="event-location">{location}</div>' if location else ""
            cards.append(
                f"""
                <article class="event-card {source_class(event.source)}">
                    {link_open}
                        <div class="event-card-time">{when}</div>
                        <div class="event-card-title">{title}</div>
                        {location_html}
                        <div class="event-card-source">{source}</div>
                    {link_close}
                </article>
                """
            )

        rows.append(
            f"""
            <section class="time-row">
                <div class="time-marker">
                    <span>{format_minutes(group["start"])}</span>
                </div>
                <div class="event-grid">
                    {''.join(cards)}
                </div>
            </section>
            """
        )

    unknown_html = ""
    if unknown_events:
        unknown_items = []
        for event in unknown_events:
            url = escape(event.url or "")
            title = escape(event.title)
            source = escape(event.source)
            href_open = f'<a href="{url}" target="_blank" rel="noopener noreferrer">' if url else "<span>"
            href_close = "</a>" if url else "</span>"
            unknown_items.append(f"<li>{href_open}{title}{href_close} <small>{source}</small></li>")
        unknown_html = f"""
        <div class="untimed-events">
            <h3>Listed without a specific time</h3>
            <ul>{''.join(unknown_items)}</ul>
        </div>
        """

    component_height = min(
        1200,
        max(560, len(timed_events) * 112 + len(grouped_events) * 18 + len(unknown_events) * 42 + 80),
    )
    components.html(
        f"""
        <!doctype html>
        <html>
        <head>
            <style>
            * {{
                box-sizing: border-box;
            }}
            body {{
                margin: 0;
                color: #1d2935;
                font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }}
            .calendar-shell {{
                border: 1px solid #d7dde3;
                border-radius: 8px;
                overflow: visible;
                background: #ffffff;
            }}
            .day-agenda {{
                background: #fbfcfd;
            }}
            .time-row {{
                display: grid;
                grid-template-columns: 86px minmax(0, 1fr);
                gap: 14px;
                padding: 14px 16px 16px 0;
                border-top: 1px solid #e6ebef;
            }}
            .time-row:first-child {{
                border-top: 0;
            }}
            .time-marker {{
                border-right: 1px solid #cbd3dc;
                min-height: 100%;
                padding: 2px 14px 0 0;
                text-align: right;
            }}
            .time-marker span {{
                color: #6b7886;
                font-size: 0.78rem;
                font-weight: 800;
                white-space: nowrap;
            }}
            .event-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
                gap: 12px;
                min-width: 0;
            }}
            .event-card {{
                border: 1px solid #a8b4bf;
                border-left-width: 5px;
                border-radius: 8px;
                background: #ffffff;
                box-shadow: 0 8px 18px rgba(29, 41, 53, 0.08);
                min-width: 0;
            }}
            .event-card a,
            .event-card > div {{
                color: inherit;
                display: block;
                min-height: 100%;
                padding: 0.68rem 0.75rem 0.72rem;
                text-decoration: none;
            }}
            .event-card-time {{
                color: #526170;
                font-size: 0.76rem;
                font-weight: 700;
                line-height: 1.2;
            }}
            .event-card-title {{
                color: #182431;
                font-size: 0.98rem;
                font-weight: 750;
                line-height: 1.25;
                margin-top: 0.25rem;
                overflow-wrap: anywhere;
            }}
            .event-location {{
                color: #465462;
                font-size: 0.82rem;
                line-height: 1.28;
                margin-top: 0.28rem;
                overflow-wrap: anywhere;
            }}
            .event-card-source {{
                color: #687684;
                font-size: 0.7rem;
                font-weight: 700;
                margin-top: 0.42rem;
                text-transform: uppercase;
            }}
            .source-aadl {{ border-left-color: #2f6f7e; }}
            .source-ann-arbor-with-kids {{ border-left-color: #bd5b2c; }}
            .source-ann-arbor-observer {{ border-left-color: #5267a7; }}
            .source-cadl {{ border-left-color: #2d7a4f; }}
            .source-elpl {{ border-left-color: #9a5c9f; }}
            .source-517-living {{ border-left-color: #b0832d; }}
            .untimed-events {{
                border: 1px solid #d7dde3;
                border-radius: 8px;
                margin-top: 0.75rem;
                padding: 0.85rem 1rem;
                background: #ffffff;
            }}
            .untimed-events h3 {{
                color: #1d2935;
                font-size: 0.95rem;
                margin: 0 0 0.45rem;
            }}
            .untimed-events ul {{
                margin: 0;
                padding-left: 1.1rem;
            }}
            .untimed-events li {{
                margin: 0.24rem 0;
            }}
            .untimed-events small {{
                color: #687684;
                margin-left: 0.25rem;
            }}
            @media (max-width: 720px) {{
                .time-row {{
                    grid-template-columns: 1fr;
                    gap: 8px;
                    padding: 14px 12px;
                }}
                .time-marker {{
                    border-right: 0;
                    padding: 0;
                    text-align: left;
                }}
                .event-grid {{
                    grid-template-columns: 1fr;
                }}
                .event-card-title {{
                    font-size: 0.94rem;
                }}
            }}
            </style>
        </head>
        <body>
            <div class="calendar-shell">
                <div class="day-agenda">
                    {''.join(rows)}
                </div>
            </div>
            {unknown_html}
        </body>
        </html>
        """,
        height=component_height,
        scrolling=True,
    )


st.set_page_config(page_title="Local Events Digest", layout="wide")

st.markdown(
    """
    <style>
    .block-container {
        max-width: 1120px;
        padding-top: 2rem;
        padding-bottom: 3rem;
    }
    .hero {
        padding: 1rem 0 1.15rem;
        border-bottom: 1px solid #d7dde3;
        margin-bottom: 1.25rem;
    }
    .hero h1 {
        margin: 0;
        font-size: 2rem;
        letter-spacing: 0;
        color: #1d2935;
    }
    .hero p {
        margin: 0.35rem 0 0;
        color: #566574;
        font-size: 1rem;
    }
    .calendar-shell {
        border: 1px solid #d7dde3;
        border-radius: 8px;
        overflow: hidden;
        background: #ffffff;
    }
    .calendar-track {
        position: relative;
        margin-left: 78px;
        border-left: 1px solid #cbd3dc;
        background:
            linear-gradient(90deg, rgba(242, 245, 248, 0.75) 0 1px, transparent 1px 100%),
            #fbfcfd;
        background-size: 25% 100%;
    }
    .hour-line {
        position: absolute;
        left: 0;
        right: 0;
        border-top: 1px solid #e6ebef;
    }
    .hour-line span {
        position: absolute;
        left: -70px;
        top: -0.7rem;
        width: 55px;
        color: #6b7886;
        font-size: 0.76rem;
        text-align: right;
    }
    .event-block {
        position: absolute;
        border: 1px solid #a8b4bf;
        border-left-width: 5px;
        border-radius: 8px;
        background: #ffffff;
        box-shadow: 0 8px 18px rgba(29, 41, 53, 0.08);
        overflow: hidden;
    }
    .event-block a,
    .event-block div {
        color: inherit;
        display: block;
        height: 100%;
        padding: 0.45rem 0.55rem;
        text-decoration: none;
    }
    .event-time {
        color: #526170;
        font-size: 0.72rem;
        font-weight: 700;
        line-height: 1.1;
        padding: 0 !important;
        height: auto !important;
    }
    .event-title {
        color: #182431;
        font-size: 0.86rem;
        font-weight: 750;
        line-height: 1.17;
        margin-top: 0.18rem;
        padding: 0 !important;
        height: auto !important;
    }
    .event-location {
        color: #465462;
        font-size: 0.72rem;
        line-height: 1.18;
        margin-top: 0.16rem;
        padding: 0 !important;
        height: auto !important;
    }
    .event-source {
        color: #687684;
        font-size: 0.68rem;
        font-weight: 700;
        margin-top: 0.24rem;
        text-transform: uppercase;
        padding: 0 !important;
        height: auto !important;
    }
    .source-aadl { border-left-color: #2f6f7e; }
    .source-ann-arbor-with-kids { border-left-color: #bd5b2c; }
    .source-ann-arbor-observer { border-left-color: #5267a7; }
    .source-cadl { border-left-color: #2d7a4f; }
    .source-elpl { border-left-color: #9a5c9f; }
    .source-517-living { border-left-color: #b0832d; }
    .untimed-events {
        border: 1px solid #d7dde3;
        border-radius: 8px;
        margin-top: 0.75rem;
        padding: 0.85rem 1rem;
        background: #ffffff;
    }
    .untimed-events h3 {
        color: #1d2935;
        font-size: 0.95rem;
        margin: 0 0 0.45rem;
    }
    .untimed-events ul {
        margin: 0;
        padding-left: 1.1rem;
    }
    .untimed-events li {
        margin: 0.24rem 0;
    }
    .untimed-events small {
        color: #687684;
        margin-left: 0.25rem;
    }
    @media (max-width: 720px) {
        .calendar-track {
            margin-left: 58px;
            background-size: 50% 100%;
        }
        .hour-line span {
            left: -52px;
            width: 42px;
            font-size: 0.68rem;
        }
        .event-block {
            border-radius: 6px;
        }
        .event-block a,
        .event-block div {
            padding: 0.38rem 0.42rem;
        }
        .event-title {
            font-size: 0.78rem;
        }
        .event-location,
        .event-source {
            display: none !important;
        }
    }
    </style>
    <div class="hero">
        <h1>Local Events Digest</h1>
        <p>Preview the day as a timeline, while keeping the plain-text digest ready for email.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

default_date = datetime.now(TZ).date()

with st.form("digest_form"):
    col1, col2 = st.columns([1, 1])
    with col1:
        city = st.selectbox("City", list(CITY_OPTIONS.keys()))
    with col2:
        target_date = st.date_input("Date", value=default_date)

    preview = st.form_submit_button("Load Digest", use_container_width=True)

if preview:
    with st.spinner("Building digest..."):
        try:
            load_digest(city, target_date)
        except Exception as exc:
            st.session_state.pop("events", None)
            st.session_state.pop("digest", None)
            st.session_state.pop("subject", None)
            st.error(f"Failed to build digest: {exc}")

current_city = st.session_state.get("selected_city", city)
current_date = st.session_state.get("selected_date")
current_events = st.session_state.get("events", [])
current_digest = st.session_state.get("digest", "")
current_subject = st.session_state.get("subject", "")

st.info(CITY_OPTIONS[current_city]["notes"])

if current_digest:
    st.subheader(f"{current_city} digest")
    if current_date:
        st.caption(f"Date: {current_date}")

    calendar_tab, text_tab = st.tabs(["Calendar", "Text digest"])

    with calendar_tab:
        render_calendar(current_events)

    with text_tab:
        st.code(current_digest, language="text")

    send_disabled = not can_send_current_digest(city, target_date)
    if send_disabled:
        st.warning("Load the digest for the currently selected city and date before sending email.")

    email_enabled = CITY_OPTIONS[current_city]["email_enabled"]()
    if not email_enabled:
        st.warning("`EMAIL_ENABLED` is false. Enable email in `.env` before sending.")

    smtp_ready = email_configured()
    if not smtp_ready:
        st.warning("SMTP settings are incomplete. Set `SMTP_HOST`, `FROM_EMAIL`, and `TO_EMAIL` in `.env`.")

    send_clicked = st.button(
        "Send Email",
        type="primary",
        disabled=send_disabled or not email_enabled or not smtp_ready,
        use_container_width=True,
    )

    if send_clicked:
        try:
            CITY_OPTIONS[current_city]["sender"](current_subject, current_digest)
            st.success("Email sent.")
        except Exception as exc:
            st.error(f"Failed to send email: {exc}")
else:
    st.caption("Choose a city and date, then load a digest.")
