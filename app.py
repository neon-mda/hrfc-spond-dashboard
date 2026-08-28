# Controls & Layout
top_col1, top_col2 = st.columns([2, 8])

with top_col1:
    if st.button("🔄 Force Refresh Data"):
        st.cache_data.clear()
        st.rerun()

with top_col2:
    view_choice = st.segmented_control(
        "Section",
        options=["All Teams", "Minis (U6–U12)", "Juniors (U13+ & Warriors)"],
        default="All Teams",
        label_visibility="collapsed",
    )
    if not view_choice:
        view_choice = "All Teams"

with st.spinner("Fetching latest Spond response data..."):
    all_data = load_all_spond_data()

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

    render_card(filtered_data, subtitle_suffix=suffix)
