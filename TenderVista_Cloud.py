import streamlit as st
import pandas as pd
import plotly.express as px
import requests
from datetime import datetime, timedelta

st.set_page_config(page_title="TenderVista Cloud", page_icon="☁️", layout="wide")

st.title("TenderVista Cloud")
st.caption("Versie voor Streamlit Community Cloud • Geen installatie nodig")

# ==================== DATA HANDLING ====================
if "tenders" not in st.session_state:
    st.session_state.tenders = pd.DataFrame()

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
        "fields": "notice_id,title,buyer_name,estimated_value,deadline_date,cpv_codes,procedure_type,publication_date,place_of_performance"
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
use_ted = st.sidebar.checkbox("Live TED data ophalen", value=False)

if use_ted:
    keywords = st.sidebar.text_input("Zoektermen", value="renovation OR electrical")
    limit = st.sidebar.slider("Aantal resultaten", 10, 50, 25)
    days_back = st.sidebar.slider("Dagen terug", 30, 180, 90)

uploaded_file = st.sidebar.file_uploader("Upload TenderNed CSV", type=["csv"])

# Load data
if st.sidebar.button("Data laden / vernieuwen"):
    with st.spinner("Data ophalen..."):
        new_data = pd.DataFrame()
        
        if uploaded_file:
            try:
                tn = pd.read_csv(uploaded_file)
                tn["source"] = "TenderNed"
                new_data = pd.concat([new_data, tn], ignore_index=True)
            except Exception as e:
                st.error(f"CSV fout: {e}")

        if use_ted:
            ted_df = fetch_ted_data(keywords, limit=limit, days_back=days_back, api_key=api_key)
            if not ted_df.empty:
                new_data = pd.concat([new_data, ted_df], ignore_index=True)

        if not new_data.empty:
            st.session_state.tenders = new_data
            st.success(f"{len(new_data)} tenders geladen!")

df = st.session_state.tenders

# Filters
st.sidebar.header("Filters")
search = st.sidebar.text_input("Zoeken")
min_val, max_val = st.sidebar.slider("Waarde", 0, 15000000, (0, 15000000))

filtered = df.copy()
if search and not filtered.empty:
    filtered = filtered[filtered['title'].str.contains(search, case=False, na=False) | 
                        filtered['buyer'].str.contains(search, case=False, na=False)]
if not filtered.empty:
    filtered = filtered[(filtered['value'] >= min_val) & (filtered['value'] <= max_val)]

# ==================== DASHBOARD ====================
st.subheader("Overzicht")

c1, c2, c3 = st.columns(3)
c1.metric("Totaal", len(filtered) if not filtered.empty else 0)
c2.metric("Totale waarde", f"€ {filtered['value'].sum():,.0f}".replace(",", ".") if not filtered.empty else "€ 0")
c3.metric("Binnen 30 dagen", len(filtered[filtered['deadline'] <= (datetime.now() + timedelta(days=30))]) if not filtered.empty else 0)

# Charts
col1, col2 = st.columns(2)
with col1:
    if not filtered.empty:
        fig = px.pie(filtered.groupby('source')['value'].sum().reset_index(), 
                     values='value', names='source', hole=0.6)
        st.plotly_chart(fig, use_container_width=True)
with col2:
    if not filtered.empty:
        cpv = filtered['cpv'].value_counts().head(6).reset_index()
        cpv.columns = ['CPV', 'Aantal']
        fig2 = px.bar(cpv, x='Aantal', y='CPV', orientation='h')
        st.plotly_chart(fig2, use_container_width=True)

# Table
st.subheader(f"Aanbestedingen ({len(filtered)})")

if not filtered.empty:
    display = filtered[['id', 'source', 'title', 'buyer', 'value', 'procedure', 'deadline']].copy()
    display['value'] = display['value'].apply(lambda x: f"€ {x:,.0f}".replace(",", "."))

    event = st.dataframe(display, use_container_width=True, hide_index=True, on_select="rerun", selection_mode="single-row")

    if event.selection.rows:
        row = filtered.iloc[event.selection.rows[0]]
        with st.expander("Details", expanded=True):
            st.write(f"**{row['title']}**")
            st.write(f"**Opdrachtgever:** {row['buyer']}")
            st.write(f"**Locatie:** {row['location']}")
            st.write(f"**Waarde:** € {row['value']:,.0f}")
            st.markdown(f"[Open tender]({row['link']})")

            if st.button("AI Samenvatting (demo)"):
                st.info("Demo: Belangrijke aandachtspunten zijn toegang, planning en telemetrie.")

st.caption("TenderVista Cloud versie • Geschikt voor Streamlit Community Cloud")