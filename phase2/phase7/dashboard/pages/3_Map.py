import json
from pathlib import Path

import pydeck as pdk
import streamlit as st

from phase2.phase7.dashboard.neo4j_client import get_driver
from phase2.phase7.dashboard.graph_map import fetch_map_nodes, fetch_active_alert_locations
from phase2.phase7.dashboard.graph_edges import fetch_edges

import datetime as dt

if "customer_id" not in st.session_state:
    st.warning("Please log in from the main page.")
    st.stop()

customer_id = st.session_state["customer_id"]
driver = get_driver()

st.title("Supply Chain Map")

with driver.session() as session:
    nodes = fetch_map_nodes(session, customer_id)
    alerts = fetch_active_alert_locations(session, customer_id)
    edges = fetch_edges(session, customer_id)


alerted_supplier_ids = {a["supplier_id"] for a in alerts}

for e in edges:
    is_disrupted = e["src_id"] in alerted_supplier_ids or e["dst_id"] in alerted_supplier_ids
    e["src_color"] = [220, 20, 60] if is_disrupted else [30, 144, 255]
    e["dst_color"] = [220, 20, 60] if is_disrupted else [255, 140, 0]
    e["width"] = 5 if is_disrupted else 2

arc_layer = pdk.Layer(
    "ArcLayer",
    data=edges,
    get_source_position=["src_lon", "src_lat"],
    get_target_position=["dst_lon", "dst_lat"],
    get_source_color="src_color",
    get_target_color="dst_color",
    get_width="width",
    pickable=True,
)

if alerts:
    dates = [
        a["created_at"].to_native().date() if hasattr(a.get("created_at"), "to_native")
        else a.get("created_at")
        for a in alerts
        if a.get("created_at") is not None
    ]
    if dates:
        min_d, max_d = min(dates), max(dates)
    else:
        visible_alerts = alerts  # no timestamps available, show all
    if min_d == max_d:
        st.caption(f"All active alerts occurred on {min_d}")
        visible_alerts = alerts
    else:
        selected_date = st.slider("Show alerts up to:", min_value=min_d, max_value=max_d, value=max_d)
        visible_alerts = [a for a, d in zip(alerts, dates) if d <= selected_date]
else:
    visible_alerts = []

if not nodes:
    st.info("No geo-located nodes found for this customer.")
    st.stop()

# ---------------------------------------------------------------------------
# Map style + India boundary controls
# ---------------------------------------------------------------------------
MAP_STYLES = {
    "None (blank / theme match)": None,
    "Light": "light",
    "Dark": "dark",
    "Road": "road",
    "Satellite": "satellite",
    "Dark (no labels)": "dark_no_labels",
    "Light (no labels)": "light_no_labels",
}

ASSETS_DIR = Path(__file__).parent / "assets"
INDIA_STATES_GEOJSON = ASSETS_DIR / "india_states.geojson"

ctrl_col1, ctrl_col2 = st.columns([2, 1])
with ctrl_col1:
    selected_style_label = st.selectbox("Map style", list(MAP_STYLES.keys()), index=0)
show_india_boundary = True

selected_style = MAP_STYLES[selected_style_label]

# ---------------------------------------------------------------------------
# India boundary layer (state-level outline, dissolved from district data)
# Source: udit-001/india-maps-data (community-curated; districts dissolved
# to state boundaries here). J&K and Ladakh are represented as separate UTs.
# Verify against Survey of India before using in any officially-compliant
# context - see conversation notes.
# ---------------------------------------------------------------------------
india_boundary_layer = None
if show_india_boundary and INDIA_STATES_GEOJSON.exists():
    with open(INDIA_STATES_GEOJSON, encoding="utf-8") as f:
        india_geojson = json.load(f)

    india_boundary_layer = pdk.Layer(
        "GeoJsonLayer",
        data=india_geojson,
        stroked=True,
        filled=False,
        get_line_color=[90, 90, 90, 180],
        line_width_min_pixels=1,
        pickable=False,
    )

# ---------------------------------------------------------------------------
# Node + alert layers
# ---------------------------------------------------------------------------
NODE_COLORS = {
    "Supplier": [30, 144, 255, 160],   # blue
    "Factory":  [255, 165, 0, 160],    # orange
    "Port":     [46, 139, 87, 160],    # green
}

for n in nodes:
    n["color"] = NODE_COLORS.get(n["node_type"], [128, 128, 128, 160])

node_layer = pdk.Layer(
    "ScatterplotLayer",
    data=nodes,
    get_position=["longitude", "latitude"],
    get_fill_color="color",
    get_radius=40000,
    pickable=True,
)

alert_layer = None
if alerts:
    for a in alerts:
        a["color"] = [220, 20, 60, 220] if a["severity"] == "critical" else [255, 140, 0, 220]
    alert_layer = pdk.Layer(
        "ScatterplotLayer",
        data=alerts,
        get_position=["longitude", "latitude"],
        get_fill_color="color",
        get_radius=70000,
        pickable=True,
        stroked=True,
        get_line_color=[0, 0, 0],
        line_width_min_pixels=2,
    )

avg_lat = sum(n["latitude"] for n in nodes) / len(nodes)
avg_lon = sum(n["longitude"] for n in nodes) / len(nodes)

layers = (
    ([india_boundary_layer] if india_boundary_layer else [])
    + [arc_layer, node_layer]
    + ([alert_layer] if alert_layer else [])
)

st.pydeck_chart(pdk.Deck(
    map_style=selected_style,
    initial_view_state=pdk.ViewState(latitude=avg_lat, longitude=avg_lon, zoom=3),
    layers=layers,
    tooltip={"text": "{name} ({node_type})"},
))

col1, col2, col3 = st.columns(3)
col1.markdown("🔵 Supplier &nbsp;&nbsp; 🟠 Factory &nbsp;&nbsp; 🟢 Port")
if alerts:
    col2.markdown(f"🔴 **{len(alerts)} active high/critical alert location(s)** — larger, outlined markers")
else:
    col3.markdown("No active high/critical alerts for this customer")

st.divider()
st.subheader("Nodes on map")
st.dataframe(
    [{"Type": n["node_type"], "Name": n["name"], "Country": n["country"], "Tier": n.get("tier") or "—"}
     for n in nodes],
    use_container_width=True,
)