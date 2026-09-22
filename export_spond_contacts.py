import asyncio
import os
import pandas as pd
from spond import spond

TARGET_SPECS = [
    {"label": "HRFC U6", "group_name": "HRFC U6"},
    {"label": "HRFC U7", "group_name": "HRFC U7"},
    {"label": "HRFC U8", "group_name": "HRFC U8"},
    {"label": "HRFC U9", "group_name": "HRFC U9"},
    {"label": "HRFC U10", "group_name": "HRFC U10"},
    {"label": "HRFC U11", "group_name": "HRFC U11"},
    {"label": "HRFC U12", "group_name": "HRFC U12"},
    {"label": "HRFC U13", "group_name": "HRFC U13"},
    {"label": "HRFC U14", "group_name": "HRFC U14"},
    {"label": "HRFC HURRICANES", "group_name": "HRFC HURRICANES"},
    {"label": "HRFC COLTS", "group_name": "HRFC COLTS"},
    {"label": "WARRIORS U12", "group_name": "WARRIORS U12"},
    {"label": "WARRIORS U14", "group_name": "WARRIORS U14"},
    {"label": "WARRIORS U16", "group_name": "WARRIORS U16"},
]

def clean(val):
    return "".join(c.lower() for c in str(val) if c.isalnum()) if val else ""

def proper_case(val):
    if not val or pd.isna(val):
        return ""
    return str(val).strip().title()

def resolve_group(groups, name):
    norm = clean(name)
    for g in groups:
        if clean(g.get("name")) == norm or norm in clean(g.get("name")):
            return g
    return None

async def main():
    username = os.getenv("SPOND_USER")
    password = os.getenv("SPOND_PASS")

    if not username or not password:
        print("Missing credentials. Please set SPOND_USER and SPOND_PASS environment variables.")
        return

    client = spond.Spond(username=username, password=password)
    output_dir = r"C:\Users\matth\Downloads\SPOND"
    output_filename = os.path.join(output_dir, "SpondMemberData.xlsx")

    try:
        await client.login()
        all_groups = await client.get_groups() or []

        os.makedirs(output_dir, exist_ok=True)
        rows = []

        for spec in TARGET_SPECS:
            label = spec["label"]
            grp = resolve_group(all_groups, spec["group_name"])
            if not grp:
                print(f"Skipping {label} (Group not found)")
                continue

            group_id = grp.get("id")
            detailed_group = await client.get_group(group_id) if group_id else grp
            members = detailed_group.get("members", [])

            print(f"Processing {label} ({len(members)} total raw members)...")

            for m in members:
                # Generalized admin check across all possible Spond permission flags and role designations
                is_admin = (
                    m.get("isAdmin", False) or 
                    m.get("admin", False) or 
                    m.get("isCreator", False) or
                    str(m.get("role", "")).upper() in ["ADMIN", "COACH", "MANAGER", "LEADER"] or
                    str(m.get("type", "")).upper() in ["ADMIN", "COACH", "MANAGER", "LEADER"]
                )

                if is_admin:
                    continue

                p_id = m.get("id", "")
                p_first = proper_case(m.get("firstName", ""))
                p_last = proper_case(m.get("lastName", ""))
                p_phone = m.get("phoneNumber", "")
                p_email = m.get("email", "").lower()

                guardians = m.get("guardians", [])
                if guardians:
                    for g in guardians:
                        g_first = proper_case(g.get("firstName", ""))
                        g_last = proper_case(g.get("lastName", ""))
                        g_phone = g.get("phoneNumber", "")
                        g_email = g.get("email", "").lower()
                        rows.append({
                            "Team": label,
                            "Member ID": p_id,
                            "Player First Name": p_first,
                            "Player Last Name": p_last,
                            "Player Phone": p_phone,
                            "Player Email": p_email,
                            "Contact Type": "Guardian",
                            "Guardian First Name": g_first,
                            "Guardian Last Name": g_last,
                            "Guardian Phone": g_phone,
                            "Guardian Email": g_email
                        })
                else:
                    rows.append({
                        "Team": label,
                        "Member ID": p_id,
                        "Player First Name": p_first,
                        "Player Last Name": p_last,
                        "Player Phone": p_phone,
                        "Player Email": p_email,
                        "Contact Type": "Player Only",
                        "Guardian First Name": "",
                        "Guardian Last Name": "",
                        "Guardian Phone": "",
                        "Guardian Email": ""
                    })

        df = pd.DataFrame(rows)
        df.to_excel(output_filename, index=False)
        print(f"\nExport complete! File saved to: {output_filename}")

    finally:
        if client.clientsession:
            await client.clientsession.close()

if __name__ == "__main__":
    asyncio.run(main())