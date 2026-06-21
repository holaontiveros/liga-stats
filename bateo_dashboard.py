import requests
import pandas as pd
import plotly.express as px
import streamlit as st
import re
import unicodedata
from rapidfuzz import fuzz


TEMPORADA_ACTUAL_API_URL = "https://apiliga.serteza.com/public/api/temporadaActual"
EQUIPOS_API_URL = "https://apiliga.serteza.com/public/api/roljuegos/obtenerEquipos"
BATEO_API_URL = "https://apiliga.serteza.com/public/api/compilacion/obtenerBateo"
PITCHEO_API_URL = "https://apiliga.serteza.com/public/api/compilacion/obtenerPitcheo"


st.set_page_config(
    page_title="Dashboard Baseball Local",
    page_icon="⚾",
    layout="wide",
)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def normalize_text(value: str) -> str:
    value = str(value).lower().strip()

    value = unicodedata.normalize("NFD", value)
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")

    # Keep letters and numbers, turn punctuation into spaces
    value = re.sub(r"[^a-z0-9]+", " ", value)

    return " ".join(value.split())


def tokenize(value: str) -> list[str]:
    return normalize_text(value).split()


def team_search_score(query: str, search_text: str) -> dict:
    """
    Search made specifically for team names.

    Priority:
    1. Exact word match
    2. Word starts with the query
    3. Query is contained inside a word
    4. General fuzzy similarity
    """
    query_norm = normalize_text(query)
    text_norm = normalize_text(search_text)

    query_tokens = tokenize(query)
    text_tokens = tokenize(search_text)

    if not query_tokens:
        return {
            "FinalScore": 100,
            "ExactTokenScore": 0,
            "PrefixScore": 0,
            "ContainsScore": 0,
            "FuzzyScore": 100,
        }

    exact_token_score = 0
    prefix_score = 0
    contains_score = 0

    for query_token in query_tokens:
        if query_token in text_tokens:
            exact_token_score += 1

        if any(text_token.startswith(query_token) for text_token in text_tokens):
            prefix_score += 1

        if any(query_token in text_token for text_token in text_tokens):
            contains_score += 1

    fuzzy_score = fuzz.token_set_ratio(query_norm, text_norm)

    # The big weights make exact/prefix matches dominate fuzzy similarity.
    final_score = (
        exact_token_score * 1000
        + prefix_score * 500
        + contains_score * 250
        + fuzzy_score
    )

    return {
        "FinalScore": final_score,
        "ExactTokenScore": exact_token_score,
        "PrefixScore": prefix_score,
        "ContainsScore": contains_score,
        "FuzzyScore": fuzzy_score,
    }


def fuzzy_filter_teams(
    df: pd.DataFrame,
    query: str,
    limit: int = 80,
    score_cutoff: int = 35,
) -> pd.DataFrame:
    query = query.strip()

    if not query:
        return df.copy()

    scored_rows = []

    for index, row in df.iterrows():
        scores = team_search_score(query, row["SearchText"])

        # Use fuzzy score only as the cutoff, but not as the only ranking.
        if scores["FuzzyScore"] >= score_cutoff or scores["ContainsScore"] > 0:
            scored_rows.append(
                {
                    "index": index,
                    **scores,
                }
            )

    if not scored_rows:
        return df.iloc[0:0].copy()

    scores_df = pd.DataFrame(scored_rows)

    result = df.loc[scores_df["index"]].copy()

    result["FinalScore"] = scores_df["FinalScore"].values
    result["ExactTokenScore"] = scores_df["ExactTokenScore"].values
    result["PrefixScore"] = scores_df["PrefixScore"].values
    result["ContainsScore"] = scores_df["ContainsScore"].values
    result["FuzzyScore"] = scores_df["FuzzyScore"].values

    result = result.sort_values(
        [
            "ExactTokenScore",
            "PrefixScore",
            "ContainsScore",
            "FuzzyScore",
            "Equipo",
        ],
        ascending=[False, False, False, False, True],
    )

    return result.head(limit)

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


def api_headers(include_content_type: bool = True) -> dict:
    headers = {
        "accept": "application/json, text/plain, */*",
        "origin": "https://ligayucatan.org",
        "referer": "https://ligayucatan.org/",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X) "
            "AppleWebKit/537.36 Chrome Safari/537.36"
        ),
    }

    if include_content_type:
        headers["content-type"] = "application/json"

    return headers


def parse_team_parts(team_name: str) -> dict:
    """
    Intenta separar el nombre largo del equipo en:
    - nombre base
    - categoría
    - clasificación
    - grupo

    Ejemplo:
    VENADOS KINDER 7-8 A II
    """
    categories = [
        "TEE-BALL 3-4",
        "INICIACION 5-6",
        "KINDER 7-8",
        "DIVISION INFANTIL MENOR 09-10",
        "DIVISION INFANTIL MAYOR 11-12",
        "DIVISION JUVENIL MENOR 13-14",
        "DIVISION JUVENIL MAYOR 15-16-17",
    ]

    result = {
        "EquipoBase": team_name,
        "Categoria": "Sin categoría",
        "Clasificacion": "",
        "Grupo": "",
    }

    for category in categories:
        if category in team_name:
            before, after = team_name.split(category, 1)

            tokens = after.strip().split()

            result["EquipoBase"] = before.strip()
            result["Categoria"] = category

            if len(tokens) >= 1:
                result["Clasificacion"] = tokens[0]

            if len(tokens) >= 2:
                result["Grupo"] = tokens[1]

            return result

    return result


# ---------------------------------------------------------
# API
# ---------------------------------------------------------
@st.cache_data(ttl=300)
def fetch_current_season() -> dict:
    response = requests.get(
        TEMPORADA_ACTUAL_API_URL,
        headers=api_headers(include_content_type=False),
        timeout=20,
    )

    response.raise_for_status()

    payload = response.json()

    if not payload.get("ok"):
        raise ValueError("La API de temporada actual respondió con ok=false")

    return payload["data"]


@st.cache_data(ttl=300)
def fetch_teams(temporada_id: str) -> pd.DataFrame:
    response = requests.post(
        EQUIPOS_API_URL,
        headers=api_headers(),
        json={"TemporadaID": temporada_id},
        timeout=20,
    )

    response.raise_for_status()

    payload = response.json()

    if not payload.get("ok"):
        raise ValueError("La API de equipos respondió con ok=false")

    data = payload.get("data", [])

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)

    parsed = df["Equipo"].apply(parse_team_parts).apply(pd.Series)
    df = pd.concat([df, parsed], axis=1)

    df["Selector"] = df.apply(
        lambda r: f'{r["Equipo"]} — ID {r["InscripcionID"]}',
        axis=1,
    )

    df["SearchText"] = df.apply(
    lambda r: " ".join(
        [
            str(r["Equipo"]),
            str(r["EquipoBase"]),
            str(r["Categoria"]),
            str(r["Clasificacion"]),
            str(r["Grupo"]),
            str(r["InscripcionID"]),
        ]
    ),
    axis=1,
)

    return df


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

    df["PCL_calc"] = df.apply(lambda r: safe_div(r["CL"] * 6, r["IP"]), axis=1)

    df["WHIP"] = df.apply(lambda r: safe_div(r["BB"] + r["HA"], r["IP"]), axis=1)
    df["K/IP"] = df.apply(lambda r: safe_div(r["K"], r["IP"]), axis=1)
    df["BB/IP"] = df.apply(lambda r: safe_div(r["BB"], r["IP"]), axis=1)
    df["HA/IP"] = df.apply(lambda r: safe_div(r["HA"], r["IP"]), axis=1)
    df["CL/IP"] = df.apply(lambda r: safe_div(r["CL"], r["IP"]), axis=1)
    df["K/BB"] = df.apply(lambda r: safe_div(r["K"], r["BB"]), axis=1)
    df["Control"] = df.apply(lambda r: safe_div(r["K"], r["BB"] + r["DB"]), axis=1)
    df["BasesGratis/IP"] = df.apply(lambda r: safe_div(r["BB"] + r["DB"], r["IP"]), axis=1)

    return df


# ---------------------------------------------------------
# Load season and teams
# ---------------------------------------------------------
try:
    current_season = fetch_current_season()
    temporada_id = current_season["TemporadaID"]
    temporada_nombre = current_season["Temporada"]

    teams_df = fetch_teams(temporada_id)
except Exception as e:
    st.error("No se pudo cargar la temporada actual o la lista de equipos.")
    st.exception(e)
    st.stop()


if teams_df.empty:
    st.warning("No se encontraron equipos para la temporada actual.")
    st.stop()


# ---------------------------------------------------------
# Sidebar
# ---------------------------------------------------------
st.sidebar.title("⚾ Liga de Baseball")

st.sidebar.success(f"Temporada actual: {temporada_nombre}")

search_text = st.sidebar.text_input(
    "Buscar equipo",
    value="VENADOS KINDER 7-8",
    help="Puedes buscar por nombre, categoría, grupo o parte del texto del equipo.",
)

with st.sidebar.expander("Opciones de búsqueda"):
    fuzzy_score = st.slider(
        "Qué tan estricta debe ser la búsqueda",
        min_value=20,
        max_value=90,
        value=45,
        step=5,
        help=(
            "Más bajo encuentra más resultados, aunque sean menos exactos. "
            "Más alto exige coincidencias más cercanas."
        ),
    )

visible_teams = fuzzy_filter_teams(
    teams_df,
    search_text,
    limit=80,
    score_cutoff=fuzzy_score,
)

if "FuzzyScore" in visible_teams.columns:
    visible_teams["SelectorVisible"] = visible_teams.apply(
        lambda r: f'{r["Equipo"]} — match {r["FuzzyScore"]:.0f}% — ID {r["InscripcionID"]}',
        axis=1,
    )
else:
    visible_teams["SelectorVisible"] = visible_teams["Selector"]

if visible_teams.empty:
    st.sidebar.warning("No hay equipos que coincidan con la búsqueda.")
    st.stop()


default_index = 0

venados_match = visible_teams[
    visible_teams["Equipo"].str.contains("VENADOS KINDER 7-8 A II", case=False, na=False)
]

if not venados_match.empty:
    default_index = visible_teams.index.get_loc(venados_match.index[0])


selected_label = st.sidebar.selectbox(
    "Equipo",
    options=visible_teams["SelectorVisible"].tolist(),
    index=0,
)

selected_team = visible_teams[visible_teams["SelectorVisible"] == selected_label].iloc[0]

inscripcion_id = str(selected_team["InscripcionID"])

st.sidebar.caption(f"InscripcionID seleccionado: {inscripcion_id}")

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


# ---------------------------------------------------------
# Load stats
# ---------------------------------------------------------
try:
    batting_df = fetch_batting_stats(inscripcion_id)
    pitching_df = fetch_pitching_stats(inscripcion_id)
except Exception as e:
    st.error("No se pudieron cargar las estadísticas del equipo seleccionado.")
    st.exception(e)
    st.stop()


if batting_df.empty and pitching_df.empty:
    st.warning("La API no regresó estadísticas para ese equipo.")
    st.stop()


# ---------------------------------------------------------
# Header
# ---------------------------------------------------------
team_name = selected_team["EquipoBase"]
category = selected_team["Categoria"]
classification = selected_team["Clasificacion"]
group = selected_team["Grupo"]

logo_url = None

if not batting_df.empty and "Logo" in batting_df.columns:
    logo_url = batting_df["Logo"].iloc[0]

st.title(f"Dashboard del Equipo — {team_name}")

st.caption(
    f"{temporada_nombre} · {category} · Clasificación {classification} · Grupo {group} · Inscripción {inscripcion_id}"
)

if logo_url:
    st.image(logo_url, width=110)


# ---------------------------------------------------------
# Main tabs
# ---------------------------------------------------------
main_tab1, main_tab2, main_tab3, main_tab4 = st.tabs(
    [
        "⚾ Bateo",
        "🧢 Pitcheo",
        "📋 Resumen del equipo",
        "🏟️ Equipos",
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
        team_runs = batting_df["C"].sum()
        team_rbi = batting_df["CE"].sum()

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
                - **PCL**: Promedio de carreras limpias. En esta liga parece calcularse a base de 6 entradas: `CL * 6 / IP`.
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


# ---------------------------------------------------------
# Equipos
# ---------------------------------------------------------
with main_tab4:
    st.header("🏟️ Equipos de la temporada")

    st.caption(
        "Esta tabla viene de la API de equipos y permite encontrar rápidamente el InscripcionID correcto."
    )

    display_teams = teams_df[
        [
            "InscripcionID",
            "Inscripcion",
            "Equipo",
            "EquipoBase",
            "Categoria",
            "Clasificacion",
            "Grupo",
        ]
    ].copy()

    st.dataframe(
        display_teams,
        use_container_width=True,
        hide_index=True,
    )


st.divider()

st.caption(
    "Dashboard generado desde la API pública de compilación. "
    "La temporada y los equipos se cargan automáticamente para evitar escribir manualmente el InscripcionID."
)