import requests
import pandas as pd
import plotly.express as px
import streamlit as st


API_URL = "https://apiliga.serteza.com/public/api/compilacion/obtenerBateo"

DEFAULT_INSCRIPCION_ID = "13490"


# -----------------------------
# Configuración visual
# -----------------------------
st.set_page_config(
    page_title="Dashboard de Bateo",
    page_icon="⚾",
    layout="wide",
)


# -----------------------------
# Utilidades
# -----------------------------
def short_name(full_name: str) -> str:
    """
    Convierte:
    'ONTIVEROS MATEY MATIAS JAVIER'
    en algo más legible:
    'Matias Javier Ontiveros'
    """
    parts = full_name.title().split()

    if len(parts) <= 2:
        return " ".join(parts)

    # En muchos registros vienen apellidos primero y nombres al final.
    # Para niños/padres suele ser más fácil leer nombre + primer apellido.
    first_names = parts[-2:]
    first_last_name = parts[0]

    return " ".join(first_names + [first_last_name])


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def avg(value: float) -> str:
    return f"{value:.3f}"


@st.cache_data(ttl=300)
def fetch_batting_stats(inscripcion_id: str) -> pd.DataFrame:
    headers = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://ligayucatan.org",
        "referer": "https://ligayucatan.org/",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
            "AppleWebKit/537.36 Chrome Safari/537.36"
        ),
    }

    response = requests.post(
        API_URL,
        headers=headers,
        json={"InscripcionID": inscripcion_id},
        timeout=20,
    )

    response.raise_for_status()

    payload = response.json()

    if not payload.get("ok"):
        raise ValueError("La API respondió, pero ok=false")

    data = payload.get("data", [])

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)

    numeric_cols = [
        "VJ",   # Juegos
        "VB",   # Veces al bat
        "TH",   # Total de hits
        "V",    # Veces totales / apariciones
        "C",    # Carreras
        "H",    # Sencillos
        "H2",   # Dobles
        "H3",   # Triples
        "HR",   # Home runs
        "B",    # Bases por bola
        "K",    # Ponches
        "R",
        "CE",   # Carreras empujadas
        "DB",   # Golpes / dead ball
        "SH",   # Sacrificios
        "PCT",  # Promedio de bateo
    ]

    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["Nombre"] = df["Jugador"].apply(short_name)

    # Métricas calculadas
    df["TB"] = df["H"] + (df["H2"] * 2) + (df["H3"] * 3) + (df["HR"] * 4)
    df["SLG"] = df.apply(lambda r: r["TB"] / r["VB"] if r["VB"] > 0 else 0, axis=1)

    df["OBP"] = df.apply(
        lambda r: (r["TH"] + r["B"] + r["DB"]) / (r["VB"] + r["B"] + r["DB"] + r["SH"])
        if (r["VB"] + r["B"] + r["DB"] + r["SH"]) > 0
        else 0,
        axis=1,
    )

    df["OPS"] = df["OBP"] + df["SLG"]
    df["K%"] = df.apply(lambda r: r["K"] / r["V"] if r["V"] > 0 else 0, axis=1)
    df["BB%"] = df.apply(lambda r: r["B"] / r["V"] if r["V"] > 0 else 0, axis=1)
    df["Contact%"] = df.apply(lambda r: 1 - (r["K"] / r["V"]) if r["V"] > 0 else 0, axis=1)

    return df


# -----------------------------
# Sidebar
# -----------------------------
st.sidebar.title("⚾ Liga de Baseball")

inscripcion_id = st.sidebar.text_input(
    "InscripcionID",
    value=DEFAULT_INSCRIPCION_ID,
)

min_vb = st.sidebar.slider(
    "Mínimo de veces al bat para rankings",
    min_value=0,
    max_value=50,
    value=0,
)

st.sidebar.caption(
    "Tip: subir el mínimo de VB ayuda a que los rankings no favorezcan a jugadores "
    "con muy pocas oportunidades."
)


# -----------------------------
# Carga de datos
# -----------------------------
try:
    df = fetch_batting_stats(inscripcion_id)
except Exception as e:
    st.error("No se pudieron cargar las estadísticas.")
    st.exception(e)
    st.stop()

if df.empty:
    st.warning("La API no regresó jugadores para ese InscripcionID.")
    st.stop()


team_name = df["Equipo"].iloc[0]
season = df["Temporada"].iloc[0]
category = df["Categoria"].iloc[0]
group = df["Grupo"].iloc[0]
classification = df["Clasificacion"].iloc[0]

filtered = df[df["VB"] >= min_vb].copy()


# -----------------------------
# Header
# -----------------------------
st.title(f"Dashboard de Bateo — {team_name}")

st.caption(
    f"{season} · Categoría {category} · Clasificación {classification} · Grupo {group}"
)

logo_url = df["Logo"].iloc[0] if "Logo" in df.columns else None

if logo_url:
    st.image(logo_url, width=110)


# -----------------------------
# Métricas principales del equipo
# -----------------------------
team_vb = df["VB"].sum()
team_hits = df["TH"].sum()
team_walks = df["B"].sum()
team_runs = df["C"].sum()
team_rbi = df["CE"].sum()
team_strikeouts = df["K"].sum()
team_plate_appearances = df["V"].sum()

team_avg = team_hits / team_vb if team_vb > 0 else 0
team_obp = (
    (df["TH"].sum() + df["B"].sum() + df["DB"].sum())
    / (df["VB"].sum() + df["B"].sum() + df["DB"].sum() + df["SH"].sum())
    if (df["VB"].sum() + df["B"].sum() + df["DB"].sum() + df["SH"].sum()) > 0
    else 0
)

c1, c2, c3, c4, c5 = st.columns(5)

c1.metric("Promedio del equipo", avg(team_avg))
c2.metric("OBP estimado", avg(team_obp))
c3.metric("Hits totales", int(team_hits))
c4.metric("Carreras", int(team_runs))
c5.metric("Carreras empujadas", int(team_rbi))


# -----------------------------
# Explicación simple
# -----------------------------
with st.expander("¿Qué significan las métricas?"):
    st.markdown(
        """
        - **PCT / AVG**: Promedio de bateo. Se calcula como `TH / VB`.
        - **OBP estimado**: Qué tanto se embasa el jugador. Se calcula como `(TH + B + DB) / (VB + B + DB + SH)`.
        - **SLG**: Poder de bateo. Da más valor a dobles, triples y home runs.
        - **OPS**: Suma de OBP + SLG. Sirve como métrica general ofensiva.
        - **K%**: Porcentaje de ponches. Mientras más bajo, mejor.
        - **BB%**: Porcentaje de bases por bola.
        - **Contact%**: Porcentaje estimado de apariciones sin ponche.
        """
    )


# -----------------------------
# Rankings
# -----------------------------
st.header("🏆 Rankings principales")

r1, r2, r3 = st.columns(3)

with r1:
    st.subheader("Mejor promedio")
    top_avg = filtered.sort_values(["PCT", "VB"], ascending=[False, False]).head(5)

    fig = px.bar(
        top_avg,
        x="PCT",
        y="Nombre",
        orientation="h",
        text=top_avg["PCT"].map(avg),
        labels={"PCT": "Promedio", "Nombre": "Jugador"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

with r2:
    st.subheader("Más hits")
    top_hits = filtered.sort_values(["TH", "PCT"], ascending=[False, False]).head(5)

    fig = px.bar(
        top_hits,
        x="TH",
        y="Nombre",
        orientation="h",
        text="TH",
        labels={"TH": "Hits totales", "Nombre": "Jugador"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

with r3:
    st.subheader("Más carreras")
    top_runs = filtered.sort_values(["C", "PCT"], ascending=[False, False]).head(5)

    fig = px.bar(
        top_runs,
        x="C",
        y="Nombre",
        orientation="h",
        text="C",
        labels={"C": "Carreras", "Nombre": "Jugador"},
    )
    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)


# -----------------------------
# Gráficas comparativas
# -----------------------------
st.header("📊 Comparación visual")

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "Bateo general",
        "Tipo de hit",
        "Disciplina en el plato",
        "Tabla completa",
    ]
)


with tab1:
    st.subheader("Promedio vs oportunidades")

    fig = px.scatter(
        filtered,
        x="VB",
        y="PCT",
        size="TH",
        hover_name="Nombre",
        hover_data={
            "Jugador": True,
            "VB": True,
            "TH": True,
            "PCT": ":.3f",
            "OBP": ":.3f",
            "SLG": ":.3f",
            "OPS": ":.3f",
        },
        labels={
            "VB": "Veces al bat",
            "PCT": "Promedio de bateo",
            "TH": "Hits",
        },
    )

    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "Cada punto es un jugador. Más a la derecha significa más turnos; más arriba significa mejor promedio."
    )


with tab2:
    st.subheader("Composición de hits")

    hit_cols = ["H", "H2", "H3", "HR"]

    hits_long = filtered.melt(
        id_vars=["Nombre"],
        value_vars=hit_cols,
        var_name="Tipo",
        value_name="Cantidad",
    )

    tipo_map = {
        "H": "Sencillos",
        "H2": "Dobles",
        "H3": "Triples",
        "HR": "Home runs",
    }

    hits_long["Tipo"] = hits_long["Tipo"].map(tipo_map)

    fig = px.bar(
        hits_long,
        x="Nombre",
        y="Cantidad",
        color="Tipo",
        labels={
            "Nombre": "Jugador",
            "Cantidad": "Cantidad",
            "Tipo": "Tipo de hit",
        },
    )

    fig.update_layout(xaxis_tickangle=-35)
    st.plotly_chart(fig, use_container_width=True)

    st.caption(
        "Esta gráfica ayuda a ver si los hits son principalmente sencillos, dobles o triples."
    )


with tab3:
    st.subheader("Bases por bola, ponches y contacto")

    metric_choice = st.radio(
        "Métrica",
        ["BB%", "K%", "Contact%"],
        horizontal=True,
    )

    sorted_metric = filtered.sort_values(metric_choice, ascending=False)

    fig = px.bar(
        sorted_metric,
        x=metric_choice,
        y="Nombre",
        orientation="h",
        text=sorted_metric[metric_choice].map(pct),
        labels={
            metric_choice: metric_choice,
            "Nombre": "Jugador",
        },
    )

    fig.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig, use_container_width=True)

    if metric_choice == "K%":
        st.caption("En K%, más bajo normalmente es mejor.")
    elif metric_choice == "BB%":
        st.caption("En BB%, más alto significa que el jugador recibe más bases por bola.")
    else:
        st.caption("Contact% estima qué tanto evita poncharse el jugador.")


with tab4:
    st.subheader("Datos completos")

    display_cols = [
        "Nombre",
        "VJ",
        "V",
        "VB",
        "TH",
        "H",
        "H2",
        "H3",
        "HR",
        "B",
        "K",
        "C",
        "CE",
        "DB",
        "PCT",
        "OBP",
        "SLG",
        "OPS",
        "K%",
        "BB%",
        "Contact%",
    ]

    table = filtered[display_cols].copy()

    for col in ["PCT", "OBP", "SLG", "OPS"]:
        table[col] = table[col].map(avg)

    for col in ["K%", "BB%", "Contact%"]:
        table[col] = table[col].map(pct)

    st.dataframe(
        table,
        use_container_width=True,
        hide_index=True,
    )

    csv = filtered.to_csv(index=False).encode("utf-8")

    st.download_button(
        label="Descargar CSV",
        data=csv,
        file_name=f"bateo_{inscripcion_id}.csv",
        mime="text/csv",
    )


# -----------------------------
# Resumen automático
# -----------------------------
st.header("🧠 Resumen fácil de leer")

leader_avg = filtered.sort_values(["PCT", "VB"], ascending=[False, False]).iloc[0]
leader_hits = filtered.sort_values(["TH", "PCT"], ascending=[False, False]).iloc[0]
leader_runs = filtered.sort_values(["C", "PCT"], ascending=[False, False]).iloc[0]
leader_rbi = filtered.sort_values(["CE", "PCT"], ascending=[False, False]).iloc[0]
leader_contact = filtered.sort_values(["Contact%", "V"], ascending=[False, False]).iloc[0]

st.markdown(
    f"""
    - **Mejor promedio:** {leader_avg["Nombre"]} con **{avg(leader_avg["PCT"])}**.
    - **Más hits:** {leader_hits["Nombre"]} con **{int(leader_hits["TH"])}** hits.
    - **Más carreras anotadas:** {leader_runs["Nombre"]} con **{int(leader_runs["C"])}** carreras.
    - **Más carreras empujadas:** {leader_rbi["Nombre"]} con **{int(leader_rbi["CE"])}** CE.
    - **Mejor contacto estimado:** {leader_contact["Nombre"]} con **{pct(leader_contact["Contact%"])}**.
    """
)


# -----------------------------
# Footer
# -----------------------------
st.divider()

st.caption(
    "Dashboard generado desde la API pública de compilación de bateo. "
    "Las métricas OBP, SLG, OPS, K%, BB% y Contact% son calculadas localmente a partir de los campos disponibles."
)
