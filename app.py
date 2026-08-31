import asyncio
import base64
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
from spond import spond
import streamlit as st
import streamlit.components.v1 as components
from zoneinfo import ZoneInfo

# Relative path for Streamlit Cloud deployment
LOGO_IMAGE_PATH = Path("HRFC_CREST.png")

TARGET_SPECS = [
    {"label": "HRFC U6", "group_name": "U6", "alt_name": "HRFC U6", "category": "minis", "lead": "MATT"},
    {"label": "HRFC U7", "group_name": "U7", "alt_name": "HRFC U7", "category": "minis", "lead": "NICK"},
    {"label": "HRFC U8", "group_name": "U8", "alt_name": "HRFC U8", "category": "minis", "lead": "SARAH"},
    {"label": "HRFC U9", "group_name": "U9", "alt_name": "HRFC U9", "category": "minis", "lead": "DEBBIE"},
    {"label": "HRFC U10", "group_name": "U10", "alt_name": "HRFC U10", "category": "minis", "lead": "STEVE"},
    {"label": "HRFC U11", "group_name": "U11", "alt_name": "HRFC U11", "category": "minis", "lead": "JEN"},
    {"label": "HRFC U12", "group_name": "U12", "alt_name": "HRFC U12", "category": "minis", "lead": "HARRY"},
    {"label": "HRFC U13", "group_name": "U13", "alt_name": "HRFC U13", "category": "juniors_youth", "lead": "COXY"},
    {"label": "HRFC U14", "group_name": "U14", "alt_name": "HRFC U14", "category": "juniors_youth", "lead": "JONNY"},
    {"label": "HRFC HURRICANES", "group_name": "HURRICANES", "alt_name": "HRFC HURRICANES", "category": "juniors_youth", "lead": "HELEN"},
    {"label": "HRFC COLTS", "group_name": "COLTS", "alt_name": "HRFC COLTS", "category": "juniors_youth", "lead": "MARK"},
    {"label": "WARRIORS U12", "group_name": "WARRIORS U12", "alt_name": "WARRIORS U12", "category": "juniors_youth", "lead": "HELEN"},
    {"label": "WARRIORS U14", "group_name": "WARRIORS U14", "alt_name": "WARRIORS U14", "category": "juniors_youth", "lead": "JO"},
    {"label": "WARRIORS U16", "group_name": "WARRIORS U16", "alt_name": "WARRIORS U16", "category": "juniors_youth", "lead": "HELEN"},
]

CUSTOM_TEAM_ORDER = {spec["label"]: idx for idx, spec in enumerate(TARGET_SPECS)}

st.set_page_config(page_title="HRFC Spond Rates", layout="wide")


def clean(val):
    return re.sub(r"[^a-z0-9]", "", str(val).lower()) if val else ""


def parse_utc_timestamp(val):
    if not val:
        return None
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def resolve_group(groups, spec):
    name_primary = clean(spec.get("group_name", ""))
    name_alt = clean(spec.get("alt_name", ""))
    label = clean(spec.get("label", ""))

    for g in groups:
        g_name = clean(g.get("name", ""))
        if not g_name:
            continue
        if g_name == name_primary or g_name == name_alt or g_name == label:
            return g
        if name_primary and (name_primary in g_name or g_name in name_primary):
            return g
        if name_alt and (name_alt in g_name or g_name in name_alt):
            return g

    return None


def get_next_event(events, now_utc):
    upcoming = []
    # Start comparison from beginning of today (UTC)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)

    for ev in events or []:
        if ev.get("hidden") is True:
            continue
        st_time = parse_utc_timestamp(ev.get("startTimestamp"))
        if st_time and st_time >= today_start:
            upcoming.append((st_time, ev))

    if not upcoming:
        return None

    upcoming.sort(key=lambda x: x[0])
    return upcoming[0][1]


def extract_id_set(raw_list):
    res = set()
    for item in raw_list or []:
        if isinstance(item, str):
            res.add(item)
        elif isinstance(item, dict) and item.get("id"):
            res.add(item.get("id"))
    return res


def calculate_attendance(event):
    resp = event.get("responses") or {}
    acc = extract_id_set(resp.get("acceptedIds") or resp.get("accepted"))
    dec = extract_id_set(resp.get("declinedIds") or resp.get("declined"))
    una = extract_id_set(resp.get("unansweredIds") or resp.get("unanswered"))
    una.update(extract_id_set(resp.get("unconfirmedIds") or resp.get("unconfirmed")))

    dec -= acc
    una -= acc | dec

    n_acc, n_dec, n_una = len(acc), len(dec), len(una)
    total = n_acc + n_dec + n_una
    rate = ((n_acc + n_dec) / total * 100) if total > 0 else 0.0

    return {
        "acc": n_acc,
        "dec": n_dec,
        "una": n_una,
        "total": total,
        "rate": rate,
        "rate_str": f"{rate:.1f}%",
    }


async def _fetch_spond_data_async():
    username = st.secrets.get("SPOND_USER", os.getenv("SPOND_USER"))
    password = st.secrets.get("SPOND_PASS", os.getenv("SPOND_PASS"))

    if not username or not password:
        st.error("Missing SPOND_USER or SPOND_PASS credentials.")
        return []

    client = spond.Spond(username=username, password=password)
    now_utc = datetime.now(timezone.utc)
    results = []

    try:
        await client.login()
        all_groups = await client.get_groups() or []
        headers = {"Authorization": f"Bearer {client.token}", "Content-Type": "application/json"}

        for spec in TARGET_SPECS:
            label = spec["label"]
            category = spec["category"]
            lead = spec.get("lead", "")

            grp = resolve_group(all_groups, spec)
            group_id = grp.get("id") if grp else None

            if not group_id:
                results.append({
                    "label": label,
                    "lead": lead,
                    "category": category,
                    "team_rank": CUSTOM_TEAM_ORDER.get(label, 999),
                    "event_time": None,
                    "acc": 0,
                    "dec": 0,
                    "una": 0,
                    "total": 0,
                    "rate": 0.0,
                    "rate_str": "0.0%",
                })
