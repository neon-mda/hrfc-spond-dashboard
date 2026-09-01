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

# Relative paths for Streamlit Cloud deployment
LOGO_IMAGE_PATH = Path("HRFC_CREST.png")
SPOND_LOGO_PATH = Path("SPOND_LOGO.png")

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


def get_signature_title(all_data, view_choice):
    uk_tz = ZoneInfo("Europe/London")
    
    events_by_label = {d["label"]: d["event_time"].astimezone(uk_tz) for d in all_data if d.get("event_time")}

    minis_dt = events_by_label.get("HRFC U7")
    if not minis_dt:
        for lbl in ["HRFC U8", "HRFC U9", "HRFC U10", "HRFC U6", "HRFC U11", "HRFC U12"]:
            if lbl in events_by_label:
                minis_dt = events_by_label[lbl]
                break

    juniors_dt = events_by_label.get("HRFC U14") or events_by_label.get("HRFC COLTS")
    if not juniors_dt:
        for lbl in ["HRFC U13", "HRFC HURRICANES", "WARRIORS U14", "WARRIORS U16", "WARRIORS U12"]:
            if lbl in events_by_label:
                juniors_dt = events_by_label[lbl]
                break

    minis_str = minis_dt.strftime("%a %d %b").upper() if minis_dt else None
    juniors_str = juniors_dt.strftime("%a %d %b").upper() if juniors_dt else None

    if view_choice == "Minis (U6–U12)":
        return f"{minis_str or 'UPCOMING'} - HRFC TEAM SPOND RESPONSE RATES"
    elif view_choice == "Juniors (U13+ & Warriors)":
        return f"{juniors_str or 'UPCOMING'} - HRFC TEAM SPOND RESPONSE RATES"
    else:
        if juniors_str and minis_str and juniors_str != minis_str:
            return f"{juniors_str} & {minis_str} - HRFC TEAM SPOND RESPONSE RATES"
        elif juniors_str:
            return f"{juniors_str} - HRFC TEAM SPOND RESPONSE RATES"
        elif minis_str:
            return f"{minis_str} - HRFC TEAM SPOND RESPONSE RATES"
        return "HRFC TEAM SPOND RESPONSE RATES"


def render_card(results, card_title, subtitle_suffix=""):
    uk_tz = ZoneInfo("Europe/London")
    uk_now = datetime.now(uk_tz)
    timestamp = uk_now.strftime("As at %d %b %Y, %H:%M")

    logos_html = ""
    # HRFC Crest: 80px height
    if LOGO_IMAGE_PATH.exists():
        with open(LOGO_IMAGE_PATH, "rb") as f:
            b64_hrfc = base64.b64encode(f.read()).decode("utf-8")
            logos_html += f'<img src="data:image/png;base64,{b64_hrfc}" style="height: 80px; width: auto; object-fit: contain; display: block;">'

    # Spond Logo: 60px height (75% of HRFC crest)
    if SPOND_LOGO_PATH.exists():
        with open(SPOND_LOGO_PATH, "rb") as f:
            b64_spond = base64.b64encode(f.read()).decode("utf-8")
            logos_html += f'<img src="data:image/png;base64,{b64_spond}" style="height: 60px; width: auto; object-fit: contain; display: block;">'

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

    data_payload.sort(key=lambda x: x["rate"], reverse=True)
    data_json = json.dumps(data_payload)

    template = (
        '<!DOCTYPE html><html><head>'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        '<link rel="preconnect" href="https://fonts.googleapis.com">'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        '<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@400;600;700;800&display=swap" rel="stylesheet">'
        '<script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>'
        '<style>'
        '* { box-sizing: border-box; font-family: "Poppins", sans-serif; margin: 0; padding: 0; }'
        'body { background-color: transparent; padding: 4px; }'
        '.card-wrapper { display: inline-block; position: relative; max-width: 100%; }'
        '.card {'
        '  background-color: #1C0304;'
        '  border: 1px solid rgba(130, 28, 52, 0.4);'
        '  border-radius: 16px;'
        '  padding: 18px 16px;'
        '  width: fit-content;'
        '  max-width: 100%;'
        '  box-shadow: 0 10px 25px rgba(0, 0, 0, 0.2);'
        '}'
        '.header-container {'
        '  display: flex;'
        '  justify-content: space-between;'
        '  align-items: center;'
        '  gap: 16px;'
        '  margin-bottom: 14px;'
        '}'
        '.logos-wrapper {'
        '  display: flex;'
        '  align-items: center;'
        '  gap: 16px;'
        '}'
        '.action-row {'
        '  display: flex;'
        '  justify-content: flex-end;'
        '  margin-bottom: 8px;'
        '}'
        '.copy-img-btn {'
        '  background-color: #1C0304;'
        '  border: 1px solid rgba(130, 28, 52, 0.8);'
        '  color: #FFE602;'
        '  border-radius: 8px;'
        '  padding: 6px 14px;'
        '  font-size: 13px;'
        '  font-weight: 600;'
        '  cursor: pointer;'
        '  transition: all 0.15s ease;'
        '  display: inline-flex;'
        '  align-items: center;'
        '  gap: 6px;'
        '  user-select: none;'
        '}'
        '.copy-img-btn:hover {'
        '  background-color: #821C34;'
        '  color: #FFFFFF;'
        '  border-color: #821C34;'
        '}'
        '.table-container {'
        '  width: 100%;'
        '  overflow-x: auto;'
        '  -webkit-overflow-scrolling: touch;'
        '  border-radius: 8px;'
        '  scrollbar-color: rgba(255, 255, 255, 0.45) #1C0304;'
        '  scrollbar-width: thin;'
        '}'
        '.table-container::-webkit-scrollbar { height: 6px; }'
        '.table-container::-webkit-scrollbar-track { background: #1C0304; border-radius: 4px; }'
        '.table-container::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.45); border-radius: 4px; }'
        'table { width: 100%; border-collapse: separate; border-spacing: 0; min-width: 640px; }'
        'th {'
        '  color: #FFE602;'
        '  font-size: 11px;'
        '  font-weight: 700;'
        '  padding: 8px 14px;'
        '  cursor: pointer;'
        '  user-select: none;'
        '  transition: color 0.15s ease;'
        '  white-space: nowrap;'
        '  pointer-events: auto;'
        '}'
        'th:hover { color: #FFFFFF; }'
        'th .sort-icon { font-size: 9px; margin-left: 4px; opacity: 0.35; }'
        'th.active .sort-icon { opacity: 1; color: #FFFFFF; }'
        '.sticky-col-lead {'
        '  position: sticky;'
        '  left: 0;'
        '  width: 90px;'
        '  min-width: 90px;'
        '  max-width: 90px;'
        '  z-index: 2;'
        '  padding: 8px 12px !important;'
        '  text-align: left;'
        '}'
        '.sticky-col-team {'
        '  position: sticky;'
        '  left: 90px;'
        '  width: 180px;'
        '  min-width: 180px;'
        '  max-width: 180px;'
        '  z-index: 2;'
        '  box-shadow: 3px 0 5px rgba(0, 0, 0, 0.35);'
        '  text-align: left;'
        '}'
        'th.sticky-col-lead, th.sticky-col-team { background-color: #1C0304; z-index: 3; }'
        '.team-total { color: #F3C5CE; font-weight: 500; font-size: 11px; margin-left: 4px; }'
        '</style></head><body>'
        '<div class="card-wrapper">'
        '  <div class="action-row">'
        '    <button id="copy-btn" class="copy-img-btn" onclick="copyCardAsImage()">📸 Copy</button>'
        '  </div>'
        '  <div id="target-card" class="card">'
        '    <div class="header-container">'
        '      <div>'
        '        <div style="color: #FFE602; font-size: 16px; font-weight: 800; text-transform: uppercase; letter-spacing: 0.5px; line-height: 1.2;">__CARD_TITLE__</div>'
        '        <div style="color: #F3C5CE; font-size: 11px; font-weight: 500; margin-top: 4px;">__SUBTITLE__</div>'
        '      </div>'
        '      <div class="logos-wrapper">__LOGOS_HTML__</div>'
        '    </div>'
        '    <div class="table-container">'
        '      <table>'
        '        <thead>'
        '          <tr style="border: none;">'
        '            <th id="th-lead" class="sticky-col-lead" onclick="sortBy(\'lead\')">LEAD <span class="sort-icon">▲▼</span></th>'
        '            <th id="th-team" class="sticky-col-team" onclick="sortBy(\'team_rank\')">TEAM <span class="sort-icon">▲▼</span></th>'
        '            <th id="th-acc" style="text-align: center;" onclick="sortBy(\'acc\')">ACCEPTED <span class="sort-icon">▲▼</span></th>'
        '            <th id="th-dec" style="text-align: center;" onclick="sortBy(\'dec\')">DECLINED <span class="sort-icon">▲▼</span></th>'
        '            <th id="th-una" style="text-align: center;" onclick="sortBy(\'una\')">NO RESPONSE <span class="sort-icon">▲▼</span></th>'
        '            <th id="th-rate" class="active" style="text-align: right;" onclick="sortBy(\'rate\')">% RESPONDED <span class="sort-icon">▼</span></th>'
        '          </tr>'
        '        </thead>'
        '        <tbody id="table-body"></tbody>'
        '      </table>'
        '    </div>'
        '  </div>'
        '</div>'
        '<script>'
        'let rowsData = __DATA_JSON__;'
        'let currentSortKey = "rate";'
        'let isAsc = false;'
        'function renderRows() {'
        '  const tbody = document.getElementById("table-body");'
        '  tbody.innerHTML = "";'
        '  rowsData.forEach((r, idx) => {'
        '    const bgColour = (idx % 2 === 0) ? "#821C34" : "#1C0304";'
        '    const rateColor = r.rate >= 70 ? "#10B981" : (r.rate >= 50 ? "#F59E0B" : "#EF4444");'
        '    const tr = document.createElement("tr");'
        '    tr.style.backgroundColor = bgColour;'
        '    tr.style.border = "none";'
        '    tr.style.whiteSpace = "nowrap";'
        '    tr.innerHTML = `'
        '      <td class="sticky-col-lead" style="background-color: ${bgColour}; padding: 8px 12px; text-align: left; font-weight: 600; color: #F3C5CE; font-size: 13px;">${r.lead}</td>'
        '      <td class="sticky-col-team" style="background-color: ${bgColour}; padding: 8px 14px; text-align: left; font-weight: 700; color: #FFFFFF; font-size: 13px;">'
        '        ${r.label} <span class="team-total">(${r.total})</span>'
        '      </td>'
        '      <td style="padding: 8px 14px; text-align: center; color: #FFFFFF; font-size: 13px;">${r.acc}</td>'
        '      <td style="padding: 8px 14px; text-align: center; color: #FFFFFF; font-size: 13px;">${r.dec}</td>'
        '      <td style="padding: 8px 14px; text-align: center; color: #FFFFFF; font-size: 13px;">${r.una}</td>'
        '      <td style="padding: 8px 14px; text-align: right; font-weight: 700; color: ${rateColor}; font-size: 13px;">${r.rate_str}</td>'
        '    `;'
        '    tbody.appendChild(tr);'
        '  });'
        '}'
        'function sortBy(key) {'
        '  if (currentSortKey === key) { isAsc = !isAsc; } else { currentSortKey = key; isAsc = false; }'
        '  rowsData.sort((a, b) => {'
        '    let valA = a[key]; let valB = b[key];'
        '    if (typeof valA === "string") { return isAsc ? valA.localeCompare(valB) : valB.localeCompare(valA); }'
        '    return isAsc ? (Number(valA) - Number(valB)) : (Number(valB) - Number(valA));'
        '  });'
        '  const headerMap = { lead: "th-lead", team_rank: "th-team", acc: "th-acc", dec: "th-dec", una: "th-una", rate: "th-rate" };'
        '  Object.values(headerMap).forEach(id => {'
        '    const el = document.getElementById(id);'
        '    if (el) { el.classList.remove("active"); const icon = el.querySelector(".sort-icon"); if (icon) icon.textContent = "▲▼"; }'
        '  });'
        '  const activeTh = document.getElementById(headerMap[key]);'
        '  if (activeTh) { activeTh.classList.add("active"); const icon = activeTh.querySelector(".sort-icon"); if (icon) icon.textContent = isAsc ? "▲" : "▼"; }'
        '  renderRows();'
        '}'
        'async function copyCardAsImage() {'
        '  const btn = document.getElementById("copy-btn");'
        '  const cardElement = document.getElementById("target-card");'
        '  btn.textContent = "⏳ Generating...";'
        '  try {'
        '    if (typeof html2canvas === "undefined") {'
        '      throw new Error("html2canvas not loaded");'
        '    }'
        '    const canvas = await html2canvas(cardElement, {'
        '      backgroundColor: null,'
        '      scale: 2,'
        '      useCORS: true,'
        '      logging: false'
        '    });'
        '    canvas.toBlob(async (blob) => {'
        '      if (!blob) {'
        '        btn.textContent = "❌ Failed";'
        '        setTimeout(() => { btn.textContent = "📸 Copy"; }, 2000);'
        '        return;'
        '      }'
        '      try {'
        '        await navigator.clipboard.write(['
        '          new ClipboardItem({ "image/png": blob })'
        '        ]);'
        '        btn.textContent = "✅ Image Copied!";'
        '      } catch (err) {'
        '        const link = document.createElement("a");'
        '        link.download = "HRFC_Spond_Rates.png";'
        '        link.href = canvas.toDataURL("image/png");'
        '        link.click();'
        '        btn.textContent = "💾 Downloaded!";'
        '      }'
        '      setTimeout(() => { btn.textContent = "📸 Copy"; }, 2500);'
        '    }, "image/png");'
        '  } catch (error) {'
        '    btn.textContent = "❌ Error";'
        '    setTimeout(() => { btn.textContent = "📸 Copy"; }, 2000);'
        '  }'
        '}'
        'renderRows();'
        '</script></body></html>'
    )

    card_html = (
        template
        .replace("__CARD_TITLE__", card_title)
        .replace("__SUBTITLE__", subtitle)
        .replace("__LOGOS_HTML__", logos_html)
        .replace("__DATA_JSON__", data_json)
    )

    card_height = 250 + (len(results) * 44)
    components.html(card_html, height=card_height, scrolling=False)


# Fetch Data First
with st.spinner("Fetching latest Spond response data..."):
    all_data = load_all_spond_data()

# Controls Row
ctrl_col1, ctrl_col2 = st.columns([2.0, 8.0])

with ctrl_col2:
    view_choice = st.segmented_control(
        "Section",
        options=["All Teams", "Minis (U6–U12)", "Juniors (U13+ & Warriors)"],
        default="All Teams",
        label_visibility="collapsed",
    )
    if not view_choice:
        view_choice = "All Teams"

if all_data:
    if view_choice == "Minis (U6–U12)":
        filtered_data = [d for d in all_data if d["category"] == "minis"]
        suffix = "Minis Section (U6–U12)"
    elif view_choice == "Juniors (U13+ & Warriors)":
        filtered_data = [d for d in all_data if d["category"] == "juniors_youth"]
        suffix = "Juniors Section (U13+ & Warriors)"
    else:
        filtered_data = all_data
        suffix = "All Teams"

    with ctrl_col1:
        if st.button("🔄 Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    title_text = get_signature_title(all_data, view_choice)
    render_card(filtered_data, card_title=title_text, subtitle_suffix=suffix)
