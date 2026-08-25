import asyncio
import base64
from datetime import datetime, timezone
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
    {"label": "WARRIORS U12", "parent_group": "BERKSHIRE WARRIORS", "subgroup": "U12"},
    {"label": "WARRIORS U14", "parent_group": "BERKSHIRE WARRIORS", "subgroup": "U14"},
    {"label": "WARRIORS U16", "parent_group": "BERKSHIRE WARRIORS", "subgroup": "U16"},
    {"label": "HRFC U12", "group_name": "HRFC U12"},
    {"label": "HRFC U13", "group_name": "HRFC U13"},
    {"label": "HRFC U14", "group_name": "HRFC U14"},
    {"label": "HRFC HURRICANES", "group_name": "HRFC HURRICANES"},
    {"label": "HRFC COLTS", "group_name": "HRFC COLTS"},
]

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


def resolve_subgroup(group_obj, name):
    norm = clean(name)
    for sg in group_obj.get("subGroups", []):
        if clean(sg.get("name")) == norm or norm in clean(sg.get("name")):
            return sg
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

    return {"acc": n_acc, "dec": n_dec, "una": n_una, "rate": rate, "rate_str": f"{rate:.1f}%"}


async def fetch_spond_data():
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
            group_id, subgroup_id = None, None

            if "parent_group" in spec:
                parent = resolve_group(all_groups, spec["parent_group"])
                if parent:
                    group_id = parent.get("id")
                    sg = resolve_subgroup(parent, spec["subgroup"])
                    if sg:
                        subgroup_id = sg.get("id")
            else:
                grp = resolve_group(all_groups, spec["group_name"])
                if grp:
                    group_id = grp.get("id")

            if not group_id:
                results.append({"label": label, "acc": 0, "dec": 0, "una": 0, "rate": 0.0, "rate_str": "0.0%"})
                continue

            query = {
                "group_id": group_id,
                "include_scheduled": True,
                "include_hidden": True,
                "min_start": now_utc,
                "max_events": 1000,
            }
            if subgroup_id:
                query["subgroup_id"] = subgroup_id

            events = await client.get_events(**query) or []
            next_ev = get_next_event(events, now_utc)

            if not next_ev:
                results.append({"label": label, "acc": 0, "dec": 0, "una": 0, "rate": 0.0, "rate_str": "0.0%"})
                continue

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
                "acc": stats["acc"],
                "dec": stats["dec"],
                "una": stats["una"],
                "rate": stats["rate"],
                "rate_str": stats["rate_str"],
            })

    finally:
        if client.clientsession:
            await client.clientsession.close()

    results.sort(key=lambda r: r["rate"], reverse=True)
    return results


def render_card(results):
    uk_now = datetime.now(ZoneInfo("Europe/London"))
    timestamp = uk_now.strftime("As at %d %b %Y, %H:%M")

    logo_img_tag = ""
    if LOGO_IMAGE_PATH.exists():
        with open(LOGO_IMAGE_PATH, "rb") as f:
            b64_data = base64.b64encode(f.read()).decode("utf-8")
            logo_img_tag = f'<img src="data:image/png;base64,{b64_data}" style="height: 75px; width: auto; object-fit: contain;">'

    rows_html = ""
    for idx, r in enumerate(results):
        rate_val = r["rate"]
        rate_color = "#10B981" if rate_val >= 70 else ("#F59E0B" if rate_val >= 50 else "#EF4444")
        bg_colour = "#821C34" if idx % 2 == 0 else "transparent"

        rows_html += (
            f'<tr style="background-color: {bg_colour}; border: none; white-space: nowrap;">'
            f'<td style="padding: 10px 18px; text-align: left; font-weight: 700; color: #FFFFFF; font-size: 15px;">{r["label"]}</td>'
            f'<td style="padding: 10px 18px; text-align: center; color: #FFFFFF; font-size: 15px;">{r["acc"]}</td>'
            f'<td style="padding: 10px 18px; text-align: center; color: #FFFFFF; font-size: 15px;">{r["dec"]}</td>'
            f'<td style="padding: 10px 18px; text-align: center; color: #FFFFFF; font-size: 15px;">{r["una"]}</td>'
            f'<td style="padding: 10px 18px; text-align: right; font-weight: 700; color: {rate_color}; font-size: 15px;">{r["rate_str"]}</td>'
            f'</tr>'
        )

    card_html = (
        f'<!DOCTYPE html>'
        f'<html>'
        f'<head>'
        f'<link rel="preconnect" href="https://fonts.googleapis.com">'
        f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700;800&display=swap" rel="stylesheet">'
        f'<style>'
        f'* {{ box-sizing: border-box; font-family: "Poppins", sans-serif; margin: 0; padding: 0; }}'
        f'body {{ background-color: transparent; padding: 8px; }}'
        f'.card {{'
        f'background-color: #1C0304;'
        f'border: 1px solid rgba(130, 28, 52, 0.4);'
        f'border-radius: 16px;'
        f'padding: 24px;'
        f'display: inline-block;'
        f'box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);'
        f'white-space: nowrap;'
        f'}}'
        f'</style>'
        f'</head>'
        f'<body>'
        f'<div class="card">'
        f'<div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 32px; margin-bottom: 20px;">'
        f'<div>'
        f'<div style="color: #FFE602; font-size: 18px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px;">'
        f'HRFC TEAM SPOND RESPONSE RATES'
        f'</div>'
        f'<div style="color: #F3C5CE; font-size: 11px; font-weight: 500; margin-top: 4px;">'
        f'Upcoming Fixtures & Sessions &bull; {timestamp}'
        f'</div>'
        f'</div>'
        f'<div>{logo_img_tag}</div>'
        f'</div>'
        f'<table style="width: 100%; border-collapse: collapse;">'
        f'<thead>'
        f'<tr style="border: none; white-space: nowrap;">'
        f'<th style="color: #FFE602; font-size: 11px; font-weight: 700; text-align: left; padding: 8px 18px;">TEAM</th>'
        f'<th style="color: #FFE602; font-size: 11px; font-weight: 700; text-align: center; padding: 8px 18px;">ACCEPTED</th>'
        f'<th style="color: #FFE602; font-size: 11px; font-weight: 700; text-align: center; padding: 8px 18px;">DECLINED</th>'
        f'<th style="color: #FFE602; font-size: 11px; font-weight: 700; text-align: center; padding: 8px 18px;">NO RESPONSE</th>'
        f'<th style="color: #FFE602; font-size: 11px; font-weight: 700; text-align: right; padding: 8px 18px;">% RESPONDED</th>'
        f'</tr>'
        f'</thead>'
        f'<tbody>{rows_html}</tbody>'
        f'</table>'
        f'</div>'
        f'</body>'
        f'</html>'
    )
    components.html(card_html, height=650, scrolling=False)


# Execution
col1, col2 = st.columns([1, 8])
with col1:
    if st.button("🔄 Refresh Data"):
        st.rerun()

with st.spinner("Fetching latest Spond response data..."):
    data = asyncio.run(fetch_spond_data())

if data:
    render_card(data)
