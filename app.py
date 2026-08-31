import asyncio
import base64
from datetime import datetime, timezone
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
    {"label": "HRFC U6", "group_name": "HRFC U6", "category": "minis", "lead": "MATT"},
    {"label": "HRFC U7", "group_name": "HRFC U7", "category": "minis", "lead": "NICK"},
    {"label": "HRFC U8", "group_name": "HRFC U8", "category": "minis", "lead": "SARAH"},
    {"label": "HRFC U9", "group_name": "HRFC U9", "category": "minis", "lead": "DEBBIE"},
    {"label": "HRFC U10", "group_name": "HRFC U10", "category": "minis", "lead": "STEVE"},
    {"label": "HRFC U11", "group_name": "HRFC U11", "category": "minis", "lead": "JEN"},
    {"label": "HRFC U12", "group_name": "HRFC U12", "category": "minis", "lead": "HARRY"},
    {"label": "HRFC U13", "group_name": "HRFC U13", "category": "juniors_youth", "lead": "COXY"},
    {"label": "HRFC U14", "group_name": "HRFC U14", "category": "juniors_youth", "lead": "JONNY"},
    {"label": "HRFC HURRICANES", "group_name": "HRFC HURRICANES", "category": "juniors_youth", "lead": "HELEN"},
    {"label": "HRFC COLTS", "group_name": "HRFC COLTS", "category": "juniors_youth", "lead": "MARK"},
    {"label": "WARRIORS U12", "group_name": "WARRIORS U12", "category": "juniors_youth", "lead": "HELEN"},
    {"label": "WARRIORS U14", "group_name": "WARRIORS U14", "category": "juniors_youth", "lead": "JO"},
    {"label": "WARRIORS U16", "group_name": "WARRIORS U16", "category": "juniors_youth", "lead": "HELEN"},
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


def resolve_group(groups, name):
    norm = clean(name)
    for g in groups:
        if clean(g.get("name")) == norm or norm in clean(g.get("name")):
            return g
    return None


def get_next_event(events, now_utc):
    upcoming = []
    for ev in events or []:
        if ev.get("hidden") is True:
            continue
        st_time = parse_utc_timestamp(ev.get("startTimestamp"))
        if st_time and st_time >= now_utc:
            upcoming.append((st_time, ev))

    if not upcoming:
        for ev in events or []:
            st_time = parse_utc_timestamp(ev.get("startTimestamp"))
            if st_time and st_time >= now_utc:
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

            grp = resolve_group(all_groups, spec["group_name"])
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
                continue

            query = {
                "group_id": group_id,
                "include_scheduled": True,
                "include_hidden": True,
                "min_start": now_utc,
                "max_events": 1000,
            }

            events = await client.get_events(**query) or []
            next_ev = get_next_event(events, now_utc)

            if not next_ev:
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
                continue

            ev_time = parse_utc_timestamp(next_ev.get("startTimestamp"))
            ev_id = next_ev.get("id")
            detailed_ev = next_ev
            if ev_id:
                try:
                    async with client.clientsession.get(
                        f"https://api.spond.com/core/v1/sponds/{ev_id}", headers=headers
                    ) as resp:
                        if resp.status == 200:
                            detailed_ev = await resp.json()
                except Exception:
                    pass

            stats = calculate_attendance(detailed_ev)
            results.append({
                "label": label,
                "lead": lead,
                "category": category,
                "team_rank": CUSTOM_TEAM_ORDER.get(label, 999),
                "event_time": ev_time,
                "acc": stats["acc"],
                "dec": stats["dec"],
                "una": stats["una"],
                "total": stats["total"],
                "rate": stats["rate"],
                "rate_str": stats["rate_str"],
            })

    finally:
        if client.clientsession:
            await client.clientsession.close()

    results.sort(key=lambda r: r["rate"], reverse=True)
    return results


@st.cache_data(ttl=300, show_spinner=False)
def load_all_spond_data():
    return asyncio.run(_fetch_spond_data_async())


def render_card(results, subtitle_suffix=""):
    uk_tz = ZoneInfo("Europe/London")
    uk_now = datetime.now(uk_tz)
    timestamp = uk_now.strftime("As at %d %b %Y, %H:%M")

    # Smart date handling: Collect all distinct upcoming dates
    valid_dates = [r["event_time"].astimezone(uk_tz) for r in results if r.get("event_time") is not None]
    unique_date_strs = sorted(list({dt.strftime("%a %d %b").upper() for dt in valid_dates}), key=lambda d: datetime.strptime(d, "%a %d %b")) if valid_dates else []

    if len(unique_date_strs) == 1:
        card_title = f"{unique_date_strs[0]} - HRFC TEAM SPOND RESPONSE RATES"
    elif len(unique_date_strs) == 2:
        card_title = f"{unique_date_strs[0]} & {unique_date_strs[1]} - HRFC TEAM SPOND RESPONSE RATES"
    elif len(unique_date_strs) > 2:
        card_title = f"{unique_date_strs[0]} to {unique_date_strs[-1]} - HRFC TEAM SPOND RESPONSE RATES"
    else:
        card_title = "HRFC TEAM SPOND RESPONSE RATES"

    logo_img_tag = ""
    if LOGO_IMAGE_PATH.exists():
        with open(LOGO_IMAGE_PATH, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
            logo_img_tag = f'<img src="data:image/png;base64,{b64_data}" style="height: 64px; width: auto; object-fit: contain;">'

    subtitle = f"Upcoming Fixtures & Sessions &bull; {timestamp}"
    if subtitle_suffix:
        subtitle = f"{subtitle_suffix} &bull; {timestamp}"

    data_payload = [{
        "lead": r["lead"],
        "label": r["label"],
        "team_rank": int(r.get("team_rank", 999)),
        "acc": int(r["acc"]),
        "dec": int(r["dec"]),
        "una": int(r["una"]),
        "total": int(r.get("total", r["acc"] + r["dec"] + r["una"])),
        "rate": float(r["rate"]),
        "rate_str": r["rate_str"]
    } for r in results]

    # Pre-sort descending by rate by default
    data_payload.sort(key=lambda x: x["rate"], reverse=True)
    data_json = json.dumps(data_payload)

    card_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@4
