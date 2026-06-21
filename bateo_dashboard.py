import requests
import pandas as pd
import plotly.express as px
import streamlit as st


BATEO_API_URL = "https://apiliga.serteza.com/public/api/compilacion/obtenerBateo"
PITCHEO_API_URL = "https://apiliga.serteza.com/public/api/compilacion/obtenerPitcheo"

DEFAULT_INSCRIPCION_ID = "13490"


st.set_page_config(
    page_title="Dashboard Baseball Local",
    page_icon="⚾",
    layout="wide",
)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def short_name(full_name: str) -> str:
    parts = str(full_name).title().split()

    if len(parts) <= 2:
        return " ".join(parts)

    first_names = parts[-2:]
    first_last_name = parts[0]

    return " ".join(first_names + [first_last_name])


def to_number(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    return df


def avg(value: float) -> str:
    return f"{value:.3f}"


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def per_game(value: float) -> str:
    return f"{value:.2f}"


def safe_div(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0

    return numerator / denominator


def api_headers() -> dict:
    return {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "origin": "https://ligayucatan.org",
        "referer": "https://ligayucatan.org/",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
            "AppleWebKit/537.36 Chrome Safari/537.36"
        ),
    }


@st.cache_data(ttl=300)
def fetch_api(url: str, inscripcion_id: str) -> pd.DataFrame:
    response = requests.post(
        url,
        headers=api_headers(),
        json={"InscripcionID": inscripcion_id},
        timeout=20,
    )

    response.raise_for_status()

    payload = response.json()

    if not payload.get("ok"):
        raise ValueError("La API respondió con ok=false")

    data = payload.get("data", [])

    if not data:
        return pd.DataFrame()

    return pd.DataFrame(data)


@st.cache_data(ttl=300)
def fetch_batting_stats(inscripcion_id: str) -> pd.DataFrame:
    df = fetch_api(BATEO_API_URL, inscripcion_id)

    if df.empty:
        return df

    numeric_cols = [
        "VJ",
        "VB",
        "TH",
        "V",
        "C",
        "H",
        "H2",
        "H3",
        "HR",
        "B",
        "K",
        "R",
        "CE",
        "DB",
        "SH",
        "PCT",
    ]

    df = to_number(df, numeric_cols)

    df["Nombre"] = df["Jugador"].apply(short_name)

    # Bases totales estimadas:
    # H = sencillos, H2 = dobles, H3 = triples, HR = home runs
    df["TB"] = df["H"] + (df["H2"] * 2) + (df["H3"] * 3) + (df["HR"] * 4)

    df["SLG"] = df.apply(lambda r: safe_div(r["TB"], r["VB"]), axis=1)

    df["OBP"] = df.apply(
        lambda r: safe_div(
            r["TH"] + r["B"] + r["DB"],
            r["VB"] + r["B"] + r["DB"] + r["SH"],
        ),
        axis=1,
    )

    df["OPS"] = df["OBP"] + df["SLG"]
    df["K%"] = df.apply(lambda r: safe_div(r["K"], r["V"]), axis=1)
    df["BB%"] = df.apply(lambda r: safe_div(r["B"], r["V"]), axis=1)
    df["Contact%"] = df.apply(lambda r: 1 - safe_div(r["K"], r["V"]), axis=1)

    return df


@st.cache_data(ttl=300)
def fetch_pitching_stats(inscripcion_id: str) -> pd.DataFrame:
    df = fetch_api(PITCHEO_API_URL, inscripcion_id)

    if df.empty:
        return df

    numeric_cols = [
        "TopeCL",
        "Jugo",
        "Ganados",
        "Perdidos",
        "IP",
        "JE",
        "BK",
        "DB",
        "WP",
        "BB",
        "K",
        "TC",
        "CL",
        "HA",
        "PCT",
        "PCL",
    ]

    df = to_number(df, numeric_cols)

    df["Nombre"] = df["Jugador"].apply(short_name)

    # La liga parece calcular PCL usando juegos de 6 entradas:
    # PCL = CL * 6 / IP
    df["PCL_calc"] = df.apply(lambda r: safe_div(r["CL"] * 6, r["IP"]), axis=1)

    # WHIP tradicional: bases por bola + hits permitidos por entrada
    df["WHIP"] = df.apply(lambda r: safe_div(r["BB"] + r["HA"], r["IP"]), axis=1)

    # Métricas fáciles para coaches/papás
    df["K/IP"] = df.apply(lambda r: safe_div(r["K"], r["IP"]), axis=1)
    df["BB/IP"] = df.apply(lambda r: safe_div(r["BB"], r["IP"]), axis=1)
    df["HA/IP"] = df.apply(lambda r: safe_div(r["HA"], r["IP"]), axis=1)
    df["CL/IP"] = df.apply(lambda r: safe_div(r["CL"], r["IP"]), axis=1)
    df["K/BB"] = df.apply(lambda r: safe_div(r["K"], r["BB"]), axis=1)
    df["Control"] = df.apply(lambda r: safe_div(r["K"], r["BB"] + r["DB"]), axis=1)
    df["BasesGratis/IP"] = df.apply(lambda r: safe_div(r["BB"] + r["DB"], r["IP"]), axis=1)

    return df


# ---------------------------------------------------------
# Sidebar
# ---------------------------------------------------------
st.sidebar.title("⚾ Liga de Baseball")

inscripcion_id = st.sidebar.text_input(
    "InscripcionID",
    value=DEFAULT_INSCRIPCION_ID,
)

min_vb = st.sidebar.slider(
    "Mínimo VB para rankings de bateo",
    min_value=0,
    max_value=50,
    value=0,
)

min_ip = st.sidebar.slider(
    "Mínimo IP para rankings de pitcheo",
    min_value=0.0,
    max_value=20.0,
    value=1.0,
    step=0.5,
)

st.sidebar.caption(
    "Subir los mínimos ayuda a que los rankings no favorezcan a jugadores con muy pocas oportunidades."
)


# ---------------------------------------------------------
# Load data
# ---------------------------------------------------------
try:
    batting_df = fetch_batting_stats(inscripcion_id)
    pitching_df = fetch_pitching_stats(inscripcion_id)
except Exception as e:
    st.error("No se pudieron cargar las estadísticas.")
    st.exception(e)
    st.stop()


if batting_df.empty and pitching_df.empty:
    st.warning("La API no regresó datos para ese InscripcionID.")
    st.stop()


# ---------------------------------------------------------
# Header
# ---------------------------------------------------------
if not batting_df.empty:
    team_name = batting_df["Equipo"].iloc[0]
    season = batting_df["Temporada"].iloc[0]
    category = batting_df["Categoria"].iloc[0]
    group = batting_df["Grupo"].iloc[0]
    classification = batting_df["Clasificacion"].iloc[0]
    logo_url = batting_df["Logo"].iloc[0] if "Logo" in batting_df.columns else None
else:
    team_name = "Equipo"
    season = ""
    category = ""
    group = ""
    classification = ""
    logo_url = None

st.title(f"Dashboard del Equipo — {team_name}")

if season:
    st.caption(
        f"{season} · Categoría {category} · Clasificación {classification} · Grupo {group}"
    )

if logo_url:
    st.image(logo_url, width=110)


# ---------------------------------------------------------
# Main tabs
# ---------------------------------------------------------
main_tab1, main_tab2, main_tab3 = st.tabs(
    [
        "⚾ Bateo",
        "🧢 Pitcheo",
        "📋 Resumen del equipo",
    ]
)


# ---------------------------------------------------------
# Bateo
# ---------------------------------------------------------
with main_tab1:
    if batting_df.empty:
        st.warning("No hay estadísticas de bateo.")
    else:
        filtered_batting = batting_df[batting_df["VB"] >= min_vb].copy()

        st.header("⚾ Estadísticas de Bateo")

        team_vb = batting_df["VB"].sum()
        team_hits = batting_df["TH"].sum()
        team_walks = batting_df["B"].sum()
        team_runs = batting_df["C"].sum()
        team_rbi = batting_df["CE"].sum()
        team_strikeouts = batting_df["K"].sum()
        team_plate_appearances = batting_df["V"].sum()

        team_avg = safe_div(team_hits, team_vb)

        team_obp = safe_div(
            batting_df["TH"].sum() + batting_df["B"].sum() + batting_df["DB"].sum(),
            batting_df["VB"].sum()
            + batting_df["B"].sum()
            + batting_df["DB"].sum()
            + batting_df["SH"].sum(),
        )

        c1, c2, c3, c4, c5 = st.columns(5)

        c1.metric("Promedio equipo", avg(team_avg))
        c2.metric("OBP estimado", avg(team_obp))
        c3.metric("Hits", int(team_hits))
        c4.metric("Carreras", int(team_runs))
        c5.metric("CE", int(team_rbi))

        with st.expander("¿Qué significan las métricas de bateo?"):
            st.markdown(
                """
                - **PCT / AVG**: Promedio de bateo.
                - **OBP estimado**: Qué tanto se embasa el jugador.
                - **SLG**: Poder de bateo. Da más valor a dobles, triples y home runs.
                - **OPS**: OBP + SLG. Métrica general ofensiva.
                - **K%**: Porcentaje de ponches. Más bajo suele ser mejor.
                - **BB%**: Porcentaje de bases por bola.
                - **Contact%**: Porcentaje estimado de apariciones sin ponche.
                """
            )

        st.subheader("🏆 Rankings de bateo")

        b1, b2, b3 = st.columns(3)

        with b1:
            st.markdown("#### Mejor promedio")
            top_avg = filtered_batting.sort_values(
                ["PCT", "VB"], ascending=[False, False]
            ).head(5)

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

        with b2:
            st.markdown("#### Más hits")
            top_hits = filtered_batting.sort_values(
                ["TH", "PCT"], ascending=[False, False]
            ).head(5)

            fig = px.bar(
                top_hits,
                x="TH",
                y="Nombre",
                orientation="h",
                text="TH",
                labels={"TH": "Hits", "Nombre": "Jugador"},
            )
            fig.update_layout(yaxis={"categoryorder": "total ascending"})
            st.plotly_chart(fig, use_container_width=True)

        with b3:
            st.markdown("#### Más carreras")
            top_runs = filtered_batting.sort_values(
                ["C", "PCT"], ascending=[False, False]
            ).head(5)

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

        st.subheader("📊 Comparación de bateo")

        bateo_tab1, bateo_tab2, bateo_tab3, bateo_tab4 = st.tabs(
            [
                "Promedio vs oportunidades",
                "Tipo de hit",
                "Disciplina",
                "Tabla completa",
            ]
        )

        with bateo_tab1:
            fig = px.scatter(
                filtered_batting,
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
                    "PCT": "Promedio",
                    "TH": "Hits",
                },
            )

            st.plotly_chart(fig, use_container_width=True)

            st.caption(
                "Más a la derecha significa más turnos. Más arriba significa mejor promedio."
            )

        with bateo_tab2:
            hit_cols = ["H", "H2", "H3", "HR"]

            hits_long = filtered_batting.melt(
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

        with bateo_tab3:
            metric_choice = st.radio(
                "Métrica de bateo",
                ["BB%", "K%", "Contact%"],
                horizontal=True,
                key="batting_metric",
            )

            sorted_metric = filtered_batting.sort_values(metric_choice, ascending=False)

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
                st.caption("En BB%, más alto significa que recibe más bases por bola.")
            else:
                st.caption("Contact% estima qué tanto evita poncharse el jugador.")

        with bateo_tab4:
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

            table = filtered_batting[display_cols].copy()

            for col in ["PCT", "OBP", "SLG", "OPS"]:
                table[col] = table[col].map(avg)

            for col in ["K%", "BB%", "Contact%"]:
                table[col] = table[col].map(pct)

            st.dataframe(table, use_container_width=True, hide_index=True)


# ---------------------------------------------------------
# Pitcheo
# ---------------------------------------------------------
with main_tab2:
    if pitching_df.empty:
        st.warning("No hay estadísticas de pitcheo.")
    else:
        filtered_pitching = pitching_df[pitching_df["IP"] >= min_ip].copy()

        st.header("🧢 Estadísticas de Pitcheo")

        team_ip = pitching_df["IP"].sum()
        team_cl = pitching_df["CL"].sum()
        team_bb = pitching_df["BB"].sum()
        team_k = pitching_df["K"].sum()
        team_ha = pitching_df["HA"].sum()
        team_db = pitching_df["DB"].sum()
        team_wins = pitching_df["Ganados"].sum()
        team_losses = pitching_df["Perdidos"].sum()

        team_pcl = safe_div(team_cl * 6, team_ip)
        team_whip = safe_div(team_bb + team_ha, team_ip)
        team_k_ip = safe_div(team_k, team_ip)
        team_bb_ip = safe_div(team_bb, team_ip)

        p1, p2, p3, p4, p5 = st.columns(5)

        p1.metric("PCL equipo", per_game(team_pcl))
        p2.metric("WHIP equipo", per_game(team_whip))
        p3.metric("K/IP", per_game(team_k_ip))
        p4.metric("BB/IP", per_game(team_bb_ip))
        p5.metric("Récord", f"{int(team_wins)}-{int(team_losses)}")

        with st.expander("¿Qué significan las métricas de pitcheo?"):
            st.markdown(
                """
                - **IP**: Entradas lanzadas.
                - **PCL**: Promedio de carreras limpias. En esta liga parece calcularse a base de **6 entradas**: `CL * 6 / IP`.
                - **WHIP**: Hits permitidos + bases por bola por entrada. Más bajo es mejor.
                - **K/IP**: Ponches por entrada. Más alto indica más dominio.
                - **BB/IP**: Bases por bola por entrada. Más bajo indica mejor control.
                - **K/BB**: Relación de ponches contra bases por bola. Más alto es mejor.
                - **BasesGratis/IP**: Bases por bola + golpeados por entrada. Más bajo es mejor.
                """
            )

        st.subheader("🏆 Rankings de pitcheo")

        if filtered_pitching.empty:
            st.warning("No hay pitchers que cumplan el mínimo de IP seleccionado.")
        else:
            pcol1, pcol2, pcol3 = st.columns(3)

            with pcol1:
                st.markdown("#### Mejor PCL")
                top_pcl = filtered_pitching.sort_values(
                    ["PCL", "IP"], ascending=[True, False]
                ).head(5)

                fig = px.bar(
                    top_pcl,
                    x="PCL",
                    y="Nombre",
                    orientation="h",
                    text=top_pcl["PCL"].map(per_game),
                    labels={"PCL": "PCL", "Nombre": "Pitcher"},
                )
                fig.update_layout(yaxis={"categoryorder": "total descending"})
                st.plotly_chart(fig, use_container_width=True)

            with pcol2:
                st.markdown("#### Más ponches")
                top_k = filtered_pitching.sort_values(
                    ["K", "IP"], ascending=[False, False]
                ).head(5)

                fig = px.bar(
                    top_k,
                    x="K",
                    y="Nombre",
                    orientation="h",
                    text="K",
                    labels={"K": "Ponches", "Nombre": "Pitcher"},
                )
                fig.update_layout(yaxis={"categoryorder": "total ascending"})
                st.plotly_chart(fig, use_container_width=True)

            with pcol3:
                st.markdown("#### Mejor WHIP")
                top_whip = filtered_pitching.sort_values(
                    ["WHIP", "IP"], ascending=[True, False]
                ).head(5)

                fig = px.bar(
                    top_whip,
                    x="WHIP",
                    y="Nombre",
                    orientation="h",
                    text=top_whip["WHIP"].map(per_game),
                    labels={"WHIP": "WHIP", "Nombre": "Pitcher"},
                )
                fig.update_layout(yaxis={"categoryorder": "total descending"})
                st.plotly_chart(fig, use_container_width=True)

        st.subheader("📊 Comparación de pitcheo")

        pitcheo_tab1, pitcheo_tab2, pitcheo_tab3, pitcheo_tab4 = st.tabs(
            [
                "Control vs dominio",
                "Carga de pitcheo",
                "Métricas clave",
                "Tabla completa",
            ]
        )

        with pitcheo_tab1:
            fig = px.scatter(
                pitching_df,
                x="BB/IP",
                y="K/IP",
                size="IP",
                hover_name="Nombre",
                hover_data={
                    "Jugador": True,
                    "IP": ":.2f",
                    "K": True,
                    "BB": True,
                    "DB": True,
                    "PCL": ":.2f",
                    "WHIP": ":.2f",
                    "K/BB": ":.2f",
                },
                labels={
                    "BB/IP": "Bases por bola por entrada",
                    "K/IP": "Ponches por entrada",
                    "IP": "Entradas lanzadas",
                },
            )

            st.plotly_chart(fig, use_container_width=True)

            st.caption(
                "Idealmente, un pitcher aparece más arriba y más a la izquierda: más ponches y menos bases por bola."
            )

        with pitcheo_tab2:
            workload = pitching_df.sort_values("IP", ascending=False)

            fig = px.bar(
                workload,
                x="Nombre",
                y="IP",
                text=workload["IP"].map(lambda v: f"{v:.2f}"),
                labels={
                    "Nombre": "Pitcher",
                    "IP": "Entradas lanzadas",
                },
            )

            fig.update_layout(xaxis_tickangle=-35)
            st.plotly_chart(fig, use_container_width=True)

            st.caption(
                "Esta gráfica muestra quién ha cargado más entradas durante la temporada."
            )

        with pitcheo_tab3:
            metric_choice = st.radio(
                "Métrica de pitcheo",
                ["PCL", "WHIP", "K/IP", "BB/IP", "K/BB", "BasesGratis/IP"],
                horizontal=True,
                key="pitching_metric",
            )

            ascending_metrics = ["PCL", "WHIP", "BB/IP", "BasesGratis/IP"]
            ascending = metric_choice in ascending_metrics

            sorted_metric = filtered_pitching.sort_values(
                [metric_choice, "IP"],
                ascending=[ascending, False],
            )

            fig = px.bar(
                sorted_metric,
                x=metric_choice,
                y="Nombre",
                orientation="h",
                text=sorted_metric[metric_choice].map(per_game),
                labels={
                    metric_choice: metric_choice,
                    "Nombre": "Pitcher",
                },
            )

            if ascending:
                fig.update_layout(yaxis={"categoryorder": "total descending"})
            else:
                fig.update_layout(yaxis={"categoryorder": "total ascending"})

            st.plotly_chart(fig, use_container_width=True)

            if metric_choice in ["PCL", "WHIP", "BB/IP", "BasesGratis/IP"]:
                st.caption("En esta métrica, más bajo normalmente es mejor.")
            else:
                st.caption("En esta métrica, más alto normalmente es mejor.")

        with pitcheo_tab4:
            display_cols = [
                "Nombre",
                "Jugo",
                "Ganados",
                "Perdidos",
                "IP",
                "PCL",
                "WHIP",
                "K",
                "BB",
                "DB",
                "HA",
                "CL",
                "TC",
                "K/IP",
                "BB/IP",
                "HA/IP",
                "K/BB",
                "BasesGratis/IP",
            ]

            table = pitching_df[display_cols].copy()

            for col in [
                "IP",
                "PCL",
                "WHIP",
                "K/IP",
                "BB/IP",
                "HA/IP",
                "K/BB",
                "BasesGratis/IP",
            ]:
                table[col] = table[col].map(per_game)

            st.dataframe(table, use_container_width=True, hide_index=True)


# ---------------------------------------------------------
# Resumen general
# ---------------------------------------------------------
with main_tab3:
    st.header("📋 Resumen fácil de leer")

    if not batting_df.empty:
        filtered_batting = batting_df[batting_df["VB"] >= min_vb].copy()

        if not filtered_batting.empty:
            leader_avg = filtered_batting.sort_values(
                ["PCT", "VB"], ascending=[False, False]
            ).iloc[0]

            leader_hits = filtered_batting.sort_values(
                ["TH", "PCT"], ascending=[False, False]
            ).iloc[0]

            leader_runs = filtered_batting.sort_values(
                ["C", "PCT"], ascending=[False, False]
            ).iloc[0]

            leader_rbi = filtered_batting.sort_values(
                ["CE", "PCT"], ascending=[False, False]
            ).iloc[0]

            leader_contact = filtered_batting.sort_values(
                ["Contact%", "V"], ascending=[False, False]
            ).iloc[0]

            st.subheader("⚾ Bateo")

            st.markdown(
                f"""
                - **Mejor promedio:** {leader_avg["Nombre"]} con **{avg(leader_avg["PCT"])}**.
                - **Más hits:** {leader_hits["Nombre"]} con **{int(leader_hits["TH"])}** hits.
                - **Más carreras anotadas:** {leader_runs["Nombre"]} con **{int(leader_runs["C"])}** carreras.
                - **Más carreras empujadas:** {leader_rbi["Nombre"]} con **{int(leader_rbi["CE"])}** CE.
                - **Mejor contacto estimado:** {leader_contact["Nombre"]} con **{pct(leader_contact["Contact%"])}**.
                """
            )

    if not pitching_df.empty:
        filtered_pitching = pitching_df[pitching_df["IP"] >= min_ip].copy()

        if not filtered_pitching.empty:
            best_pcl = filtered_pitching.sort_values(
                ["PCL", "IP"], ascending=[True, False]
            ).iloc[0]

            most_k = filtered_pitching.sort_values(
                ["K", "IP"], ascending=[False, False]
            ).iloc[0]

            best_whip = filtered_pitching.sort_values(
                ["WHIP", "IP"], ascending=[True, False]
            ).iloc[0]

            best_control = filtered_pitching.sort_values(
                ["K/BB", "IP"], ascending=[False, False]
            ).iloc[0]

            most_ip = filtered_pitching.sort_values(
                ["IP", "PCL"], ascending=[False, True]
            ).iloc[0]

            st.subheader("🧢 Pitcheo")

            st.markdown(
                f"""
                - **Mejor PCL:** {best_pcl["Nombre"]} con **{per_game(best_pcl["PCL"])}**.
                - **Más ponches:** {most_k["Nombre"]} con **{int(most_k["K"])}** K.
                - **Mejor WHIP:** {best_whip["Nombre"]} con **{per_game(best_whip["WHIP"])}**.
                - **Mejor relación K/BB:** {best_control["Nombre"]} con **{per_game(best_control["K/BB"])}**.
                - **Más entradas lanzadas:** {most_ip["Nombre"]} con **{per_game(most_ip["IP"])}** IP.
                """
            )

    st.divider()

    if not batting_df.empty:
        batting_csv = batting_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="Descargar bateo CSV",
            data=batting_csv,
            file_name=f"bateo_{inscripcion_id}.csv",
            mime="text/csv",
        )

    if not pitching_df.empty:
        pitching_csv = pitching_df.to_csv(index=False).encode("utf-8")

        st.download_button(
            label="Descargar pitcheo CSV",
            data=pitching_csv,
            file_name=f"pitcheo_{inscripcion_id}.csv",
            mime="text/csv",
        )


st.divider()

st.caption(
    "Dashboard generado desde la API pública de compilación. "
    "Las métricas adicionales son calculadas localmente para hacer las estadísticas más fáciles de entender."
)