import streamlit as st
import pandas as pd
import plotly.express as px
import requests
import duckdb
from datetime import datetime, timedelta
import os

# ==================== PAGE CONFIG ====================
st.set_page_config(
    page_title="TenderVista Pro",
    page_icon="🚀",
    layout="wide"
)

st.title("TenderVista Pro")
st.caption("Met DuckDB lokale database + slimme dagelijkse refresh")

# ==================== DUCKDB SETUP ====================
DB_FILE = "tenders.duckdb"

@st.cache_resource
def get_db_connection():
    return duckdb.connect(DB_FILE)

conn = get_db_connection()

# Create table if not exists
conn.execute("""
    CREATE TABLE IF NOT EXISTS tenders (
        id VARCHAR,
        source VARCHAR,
        title VARCHAR,
        buyer VARCHAR,
        location VARCHAR,
        nuts VARCHAR,
        cpv VARCHAR,
        value DOUBLE,
        procedure VARCHAR,
        pub_date TIMESTAMP,
        deadline TIMESTAMP,
        description VARCHAR,
        link VARCHAR,
        last_updated TIMESTAMP
    )
""")

def save_to_db(df):
    if df.empty:
        return
    df = df.copy()
    df['last_updated'] = datetime.now()
    conn.execute("DELETE FROM tenders")
    conn.execute("INSERT INTO tenders SELECT * FROM df")

def load_from_db():
    try:
        df = conn.execute("SELECT * FROM tenders").df()
        if not df.empty:
            df['pub_date'] = pd.to_datetime(df['pub_date'], errors='coerce')
            df['deadline'] = pd.to_datetime(df['deadline'], errors='coerce')
            df['days_left'] = (df['deadline'] - pd.Timestamp.now()).dt.days
        return df
    except:
        return pd.DataFrame()

# ==================== TED API ====================
def fetch_ted_data(keywords="", country="NL", limit=30, days_back=90, api_key=""):
    base_url = "https://api.ted.europa.eu/v3/notices/search"
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days_back)
    
    query = f"publication_date:[{start_date.strftime('%Y-%m-%d')} TO {end_date.strftime('%Y-%m-%d')}]"
    if keywords:
        query = f"({keywords}) AND {query}"
    if country:
        query += f" AND country:{country}"

    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    params = {
        "query": query,
        "limit": limit,
        "fields": "notice_id,title,buyer_name,estimated_value,deadline_date,cpv_codes,procedure_type,publication_date,place_of_performance,nuts_code"
    }

    try:
        response = requests.get(base_url, params=params, headers=headers, timeout=15)
        response.raise_for_status()
        notices = response.json().get("notices", [])
        
        parsed = []
        for n in notices:
            value = n.get("estimated_value", 0)
            if isinstance(value, dict):
                value = value.get("amount", 0)
            
            parsed.append({
                "id": n.get("notice_id", ""),
                "source": "TED",
                "title": n.get("title", ""),
                "buyer": n.get("buyer_name", ""),
                "location": n.get("place_of_performance", ""),
                "nuts": n.get("nuts_code", ""),
                "cpv": ", ".join(n.get("cpv_codes", [])[:3]) if n.get("cpv_codes") else "",
                "value": float(value) if value else 0,
                "procedure": n.get("procedure_type", ""),
                "pub_date": n.get("publication_date", ""),
                "deadline": n.get("deadline_date", ""),
                "description": n.get("title", ""),
                "link": f"https://ted.europa.eu/udl?uri=TED:NOTICE:{n.get('notice_id','')}:TEXT:EN:HTML"
            })
        return pd.DataFrame(parsed)
    except Exception as e:
        st.error(f"TED API fout: {e}")
        return pd.DataFrame()

# ==================== SIDEBAR ====================
st.sidebar.header("Data Bronnen")

api_key = st.sidebar.text_input("TED API Key (optioneel)", type="password")
use_live_ted = st.sidebar.checkbox("Live TED data ophalen", value=False)

if use_live_ted:
    ted_keywords = st.sidebar.text_input("Zoektermen", value="renovation OR electrical OR pump")
    ted_limit = st.sidebar.slider("Aantal resultaten", 10, 50, 25)
    ted_days = st.sidebar.slider("Dagen terug", 30, 180, 90)

uploaded_file = st.sidebar.file_uploader("Upload TenderNed CSV", type=["csv"])

# ==================== DATA LOADING ====================
df = load_from_db()

# If no data in DB or force refresh
if df.empty or st.sidebar.button("Force Refresh (nieuwste data)"):
    with st.spinner("Data ophalen..."):
        new_data = pd.DataFrame()
        
        # Load TenderNed from CSV if uploaded
        if uploaded_file:
            try:
                tn_df = pd.read_csv(uploaded_file)
                tn_df['source'] = 'TenderNed'
                if 'id' not in tn_df.columns:
                    tn_df['id'] = [f"TN-{i}" for i in range(len(tn_df))]
                new_data = pd.concat([new_data, tn_df], ignore_index=True)
            except Exception as e:
                st.error(f"Fout bij CSV: {e}")

        # Fetch TED if enabled
        if use_live_ted:
            ted_df = fetch_ted_data(ted_keywords, limit=ted_limit, days_back=ted_days, api_key=api_key)
            if not ted_df.empty:
                new_data = pd.concat([new_data, ted_df], ignore_index=True)

        if not new_data.empty:
            save_to_db(new_data)
            df = load_from_db()
            st.success("Data succesvol ververst en opgeslagen!")

# Apply filters
st.sidebar.header("Filters")
search = st.sidebar.text_input("Zoeken in titel of organisatie")
min_val, max_val = st.sidebar.slider("Waarde (€)", 0, 15000000, (0, 15000000))

filtered = df.copy()
if search:
    filtered = filtered[filtered['title'].str.contains(search, case=False, na=False) | 
                        filtered['buyer'].str.contains(search, case=False, na=False)]
filtered = filtered[(filtered['value'] >= min_val) & (filtered['value'] <= max_val)]

# ==================== DASHBOARD ====================
st.subheader("Overzicht")

col1, col2, col3 = st.columns(3)
col1.metric("Totaal tenders", len(filtered))
col2.metric("Totale waarde", f"€ {filtered['value'].sum():,.0f}".replace(",", "."))
col3.metric("Binnen 30 dagen", len(filtered[filtered['days_left'] <= 30]))

# Charts
c1, c2 = st.columns(2)
with c1:
    if not filtered.empty:
        fig = px.pie(filtered.groupby('source')['value'].sum().reset_index(), 
                     values='value', names='source', hole=0.6)
        st.plotly_chart(fig, use_container_width=True)
with c2:
    if not filtered.empty:
        cpv_top = filtered['cpv'].value_counts().head(6).reset_index()
        cpv_top.columns = ['CPV', 'Aantal']
        fig2 = px.bar(cpv_top, x='Aantal', y='CPV', orientation='h')
        st.plotly_chart(fig2, use_container_width=True)

# Table
st.subheader(f"Aanbestedingen ({len(filtered)})")

if not filtered.empty:
    display_df = filtered[['id', 'source', 'title', 'buyer', 'value', 'procedure', 'deadline', 'days_left']].copy()
    display_df['value'] = display_df['value'].apply(lambda x: f"€ {x:,.0f}".replace(",", "."))
    
    event = st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        on_select="rerun",
        selection_mode="single-row"
    )

    if event.selection.rows:
        row = filtered.iloc[event.selection.rows[0]]
        with st.expander("Details", expanded=True):
            st.write(f"**{row['title']}**")
            st.write(f"**Opdrachtgever:** {row['buyer']}")
            st.write(f"**Locatie:** {row['location']} (NUTS: {row.get('nuts', 'N/A')})")
            st.write(f"**Waarde:** € {row['value']:,.0f}")
            st.write(f"**Deadline:** {row['deadline']}")
            st.markdown(f"[Open tender]({row['link']})")

            if st.button("AI Samenvatting (demo)"):
                st.info("Demo samenvatting: Belangrijke aandachtspunten zijn toegang, planning en telemetrie-eisen.")

st.caption("Data lokaal opgeslagen in tenders.duckdb • TenderVista Pro v3")