"""Tablero del Hito 2 (Streamlit): control de calidad por linea de produccion.

Muestra (1) indicadores de cada linea, (2) resultados de los tres modelos en el tiempo y
(3) el registro de recomendaciones del LLM con la decision humana.

Ejecutar:   streamlit run app.py
Registro:   URL CSV de la pestana `registro_hito2` publicada en la web (secret `registro_csv_url`
            o variable de entorno REGISTRO_CSV_URL). Sin ella, la pestana de recomendaciones avisa.
Datos de las series y textos del manual: SIMULADOS. Imagenes: dataset publico (CC BY-NC-ND 4.0).
"""
import json
import os
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import roi
from analisis_linea import META_TASA, analizar, preparar_produccion

AQUI = Path(__file__).parent / "datos"
LINEAS = ["L1", "L2", "L3"]
# Paleta validada en el Hito 1 (una tinta por linea / modelo, mismo orden siempre)
AZUL, NARANJA, VERDE, TINTA, ROJO = "#2a78d6", "#eb6834", "#1baf7a", "#667085", "#d03b3b"
NAVY = "#0b2447"
COLOR_LINEA = {"L1": AZUL, "L2": NARANJA, "L3": VERDE}
MODELOS = {  # clave del json -> (nombre visible, color)
    "promedio_movil_7d": ("Promedio móvil 7 d", AZUL),
    "holt": ("Holt", NARANJA),
    "gru": ("GRU", VERDE),
    "lstm": ("LSTM", "#8a63c9"),
    "naivo_estacional_t-7": ("Naivo estacional (t-7)", "#98a2b3"),
}
ACCIONES = {"seguir": "Seguir", "ajustar": "Ajustar", "revision_humana": "Revisión humana", "detener_linea": "Detener la línea"}
CLASE_ACCION = {"seguir": "ok", "ajustar": "warn", "revision_humana": "warn", "detener_linea": "bad"}
ESTADOS = {"estable": "Estable", "cambio_de_nivel": "Cambio de nivel", "valor_atipico": "Valor atípico"}
CLASE_ESTADO = {"estable": "ok", "cambio_de_nivel": "bad", "valor_atipico": "warn"}
DECISIONES = {"aprobada": ("Aprobada por humano", "ok"), "no_aprobada": ("No aprobada / sin respuesta", "bad"),
              "no_requerida": ("No requería aprobación", "neutral")}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
ETIQUETA_X = "date(datum.value) + ' ' + " + str(MESES) + "[month(datum.value)]"

st.set_page_config(page_title="Control de calidad · Hito 2", page_icon="📊", layout="wide")

CSS = (Path(__file__).parent / "estilo.css").read_text(encoding="utf-8")
st.markdown(f"<style>{CSS}</style>", unsafe_allow_html=True)


# ---------------------------------------------------------------- utilidades
def pct(x, d=2):
    return f"{x * 100:.{d}f}".replace(".", ",") + " %"


def fecha_es(d):
    return f"{d.day} {MESES[d.month - 1]} {d.year}"


def tarjeta(titulo, valor, sub="", clase_sub="", texto=False):
    return (f'<div class="card"><div class="t">{titulo}</div><div class="v{" txt" if texto else ""}">{valor}</div>'
            f'<div class="s {clase_sub}">{sub}</div></div>')


def rgba(hex_, a):
    h = hex_.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{a})"


def pill(texto, clase):
    return f'<span class="pill {clase}">{texto}</span>'


def seccion(titulo, sub=""):
    st.markdown(f'<div class="seccion"><h3>{titulo}</h3>' + (f"<p>{sub}</p>" if sub else "") + "</div>", unsafe_allow_html=True)


def estilo(ch, alto=330):
    return (ch.properties(height=alto).configure_view(stroke=None)
            .configure_axis(domain=False, ticks=False, gridColor="#eceff4", labelColor=TINTA, titleColor=TINTA,
                            labelFontSize=12, titleFontSize=12, labelFont="Inter", titleFont="Inter")
            .configure_axisX(grid=False)
            .configure_legend(orient="top", title=None, labelFontSize=13, labelColor="#344054", labelFont="Inter",
                              symbolStrokeWidth=3, padding=2, offset=4)
            .configure(background="transparent"))


EJE_X = alt.Axis(labelExpr=ETIQUETA_X, title=None, labelOverlap=True, tickCount=8)
LEYENDA = alt.Legend(orient="top", direction="horizontal", title=None, labelFontSize=13, labelColor="#344054",
                     symbolStrokeWidth=3, columnPadding=18, padding=2, offset=6)


@st.cache_data
def cargar():
    df = pd.read_csv(AQUI / "defectos_lineas_largo.csv", parse_dates=["fecha"])
    res = json.loads((AQUI / "resultados_series.json").read_text(encoding="utf-8"))
    img = pd.read_csv(AQUI / "metricas_imagenes.csv")
    rag = pd.read_csv(AQUI / "metricas_rag.csv")
    return df, res, img, rag


REAL, SIM = "Planta · datos del curso", "Historia simulada (730 días)"
LINEAS_REAL = ["Linea A", "Linea B", "Linea C"]
COLOR_REAL = {"Linea A": AZUL, "Linea B": NARANJA, "Linea C": VERDE}


@st.cache_data
def cargar_real():
    """Planilla `produccion_planta` (datos del curso): se limpia y agrega por dia con la misma funcion que usa el servicio."""
    crudo = pd.read_csv(AQUI / "produccion_planta.csv")
    diarias, informe = preparar_produccion(crudo.where(crudo.notna(), None).to_dict("records"))
    dia = pd.DataFrame(diarias)
    dia["fecha"] = pd.to_datetime(dia["fecha"])
    valido = crudo.dropna(subset=["unidades_producidas", "linea"]).copy()
    valido["tasa"] = valido["unidades_defectuosas"] / valido["unidades_producidas"]
    turnos = valido.groupby(["linea", "turno"]).agg(defectos=("unidades_defectuosas", "sum"), unidades=("unidades_producidas", "sum"),
                                                    detencion=("minutos_detencion", "mean")).reset_index()
    turnos["tasa"] = turnos["defectos"] / turnos["unidades"]
    return dia, informe, turnos


def etiqueta_linea(l):
    return "Línea " + (l[6:] if l.startswith("Linea ") else l)


@st.cache_data
def resumen_linea(df, linea):
    d = df[df["linea"] == linea].sort_values("fecha")
    return analizar(d.assign(fecha=d["fecha"].dt.strftime("%Y-%m-%d")).to_dict("records"))


def url_registro():
    try:
        u = st.secrets.get("registro_csv_url", "")
    except Exception:
        u = ""
    if not u:  # streamlit solo busca secrets.toml en la carpeta desde donde se ejecuta: se busca tambien junto a app.py
        archivo = Path(__file__).parent / ".streamlit" / "secrets.toml"
        if archivo.exists():
            import tomllib
            u = tomllib.loads(archivo.read_text(encoding="utf-8-sig")).get("registro_csv_url", "")
    return u or os.environ.get("REGISTRO_CSV_URL", "")


@st.cache_data(ttl=60)
def cargar_registro(url):
    r = pd.read_csv(url)
    r["fecha_ejecucion"] = pd.to_datetime(r["fecha_ejecucion"], errors="coerce")
    return r.sort_values("fecha_ejecucion", ascending=False)


df, res, img, rag = cargar()

# Los avisos de n8n enlazan al tablero con ?linea=L2 para abrirlo en la linea de la alerta
LINEA_URL = st.query_params.get("linea", "Linea B")
FUENTE_URL = SIM if LINEA_URL in LINEAS else REAL
if LINEA_URL not in LINEAS and LINEA_URL not in LINEAS_REAL:
    LINEA_URL = "Linea B"
DF_REAL, INFORME_REAL, TURNOS_REAL = cargar_real()

# ---------------------------------------------------------------- encabezado
dias_real = int(DF_REAL["fecha"].nunique())
fila_r18 = img[img["modelo"] == "resnet18"].iloc[0]
n_imagenes = int(fila_r18[["verdaderos_pos", "verdaderos_neg", "falsos_negativos", "falsos_positivos"]].sum())
st.markdown(
    '<div class="hero"><div class="kicker"><i></i>IA Generativa para la gestión industrial · Hito 2</div>'
    "<h1>Control de calidad por línea de producción</h1>"
    "<p>Un sistema que vigila la tasa de defectos, inspecciona piezas con visión por computador y recomienda una acción "
    "citando el manual, con aprobación humana antes de detener una línea.</p>"
    '<div class="chips"><span>Series de tiempo</span><span>Reconocimiento de imágenes</span><span>Búsqueda en manual (RAG)</span>'
    "<span>LLM con control humano</span><span>Planilla del curso + series y manual simulados</span></div>"
    f'<div class="stats"><div><b>3</b><span>modelos integrados</span></div><div><b>{dias_real}</b><span>días de datos de la planta (3 líneas, 2 turnos)</span></div>'
    f'<div><b>{n_imagenes}</b><span>imágenes de prueba</span></div><div><b>Humano</b><span>aprueba antes de detener la línea</span></div></div></div>',
    unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["Indicadores por línea", "Modelos en el tiempo", "Recomendaciones del LLM", "Negocio y ROI"])

# ---------------------------------------------------------------- 1. indicadores
with tab1:
    fuente = st.segmented_control("Datos", [REAL, SIM], default=FUENTE_URL, key="fuente") or REAL
    es_real = fuente == REAL
    df_act, lineas_act, colores_act = (DF_REAL, LINEAS_REAL, COLOR_REAL) if es_real else (df, LINEAS, COLOR_LINEA)
    seccion("Estado de las tres líneas", ("Planilla de producción del curso (datos limpiados y agregados por día): el mismo análisis que usa el flujo de n8n."
                                          if es_real else "Historia simulada de 730 días, usada para comparar modelos de deep learning."))
    cols = st.columns(3)
    for c, l in zip(cols, lineas_act):
        a = resumen_linea(df_act, l)
        razon = f"{a['razon_meta']:.2f}".replace(".", ",")
        c.markdown(
            f'<div class="card linea" style="--c:{colores_act[l]}"><div style="display:flex;justify-content:space-between;align-items:center">'
            f'<span class="nombre">{etiqueta_linea(l)}</span>{pill(ESTADOS[a["estado"]], CLASE_ESTADO[a["estado"]])}</div>'
            f'<div class="fila"><span>Defectos último día</span><b>{pct(a["tasa_ultima"])}</b></div>'
            f'<div class="fila"><span>Promedio 7 días</span><b>{pct(a["tasa_media_7d"])}</b></div>'
            f'<div class="fila"><span>Veces la meta (mediana 7 d)</span><b>{razon}</b></div></div>',
            unsafe_allow_html=True)

    seccion("Detalle de una línea")
    f1, f2 = st.columns([1, 2])
    por_defecto = LINEA_URL if LINEA_URL in lineas_act else lineas_act[1]
    linea = f1.segmented_control("Línea", lineas_act, default=por_defecto, key=f"linea1_{es_real}", format_func=etiqueta_linea) or por_defecto
    ventana = f2.segmented_control("Período", ["Últimos 30 días", "Últimos 90 días", "Todo el período"],
                                   default="Todo el período", key="vent") or "Todo el período"
    d = df_act[df_act["linea"] == linea].sort_values("fecha").reset_index(drop=True)
    d["tasa"] = d["defectos"] / d["unidades"]
    a = resumen_linea(df_act, linea)
    dif = (a["tasa_ultima"] - META_TASA) * 100
    sub = (f"▼ {abs(dif):.2f} pp bajo la meta".replace(".", ","), "ok") if dif <= 0 else (f"▲ {dif:.2f} pp sobre la meta".replace(".", ","), "bad")
    k = st.columns(4)
    k[0].markdown(tarjeta("Defectos último día", pct(a["tasa_ultima"]), *sub), unsafe_allow_html=True)
    k[1].markdown(tarjeta("Promedio 7 días", pct(a["tasa_media_7d"]), f"Meta de calidad {pct(META_TASA, 1)}"), unsafe_allow_html=True)
    k[2].markdown(tarjeta("Veces la meta", f"{a['razon_meta']:.2f}".replace(".", ","), "mediana de 7 días ÷ meta"), unsafe_allow_html=True)
    k[3].markdown(tarjeta("Estado de la línea", pill(ESTADOS[a["estado"]], CLASE_ESTADO[a["estado"]]),
                          f"z = {a['z_nivel']:.1f}".replace(".", ",") + " sobre la referencia"), unsafe_allow_html=True)

    n = {"Últimos 30 días": 30, "Últimos 90 días": 90}.get(ventana, len(d))
    v = d.tail(n).copy()
    v["Promedio móvil 7 d"] = d["tasa"].rolling(7).mean().tail(n).values
    largo = v.rename(columns={"tasa": "Tasa diaria"})[["fecha", "Tasa diaria", "Promedio móvil 7 d"]].melt("fecha", var_name="serie", value_name="valor")
    for nombre, val in (("Meta (2,5 %)", META_TASA), ("Límite de control", a["limite_control_sup"])):
        largo = pd.concat([largo, pd.DataFrame({"fecha": v["fecha"], "serie": nombre, "valor": val})])
    largo["fecha_txt"] = largo["fecha"].map(fecha_es)
    dominio = ["Tasa diaria", "Promedio móvil 7 d", "Meta (2,5 %)", "Límite de control"]
    graf = alt.Chart(largo).mark_line(interpolate="monotone").encode(
        x=alt.X("fecha:T", axis=EJE_X),
        y=alt.Y("valor:Q", title="Tasa de defectos", axis=alt.Axis(format=".1%"), scale=alt.Scale(zero=True)),
        color=alt.Color("serie:N", legend=LEYENDA, scale=alt.Scale(domain=dominio, range=["#b0b7c3", colores_act[linea], ROJO, "#98a2b3"])),
        strokeDash=alt.StrokeDash("serie:N", legend=LEYENDA, scale=alt.Scale(domain=dominio, range=[[1, 0], [1, 0], [6, 4], [2, 3]])),
        strokeWidth=alt.StrokeWidth("serie:N", legend=LEYENDA, scale=alt.Scale(domain=dominio, range=[1.2, 3, 1.6, 1.6])),
        tooltip=[alt.Tooltip("fecha_txt:N", title="Fecha"), alt.Tooltip("serie:N", title="Serie"), alt.Tooltip("valor:Q", title="Valor", format=".2%")],
    )
    v["ma7"] = v["Promedio móvil 7 d"]
    degradado = alt.Gradient(gradient="linear", x1=1, x2=1, y1=1, y2=0, stops=[
        alt.GradientStop(color=rgba(colores_act[linea], 0), offset=0), alt.GradientStop(color=rgba(colores_act[linea], 0.32), offset=1)])
    area = alt.Chart(v).mark_area(interpolate="monotone", color=degradado).encode(
        x=alt.X("fecha:T", axis=EJE_X), y=alt.Y("ma7:Q", title="Tasa de defectos", axis=alt.Axis(format=".1%")))
    ultimo = v.tail(1).assign(fecha_txt=lambda x: x["fecha"].map(fecha_es))
    punto = alt.Chart(ultimo).mark_point(filled=True, size=130, color=colores_act[linea], stroke="white", strokeWidth=2.5, opacity=1).encode(
        x="fecha:T", y="ma7:Q", tooltip=[alt.Tooltip("fecha_txt:N", title="Último día"), alt.Tooltip("ma7:Q", title="Promedio móvil 7 d", format=".2%")])
    with st.container(border=True):
        st.altair_chart(estilo(alt.layer(area, graf, punto), 360), theme=None, width="stretch")
        st.markdown(f'<div class="nota">Referencia del gráfico de control: primeros 60 días (límite = media + 3 desviaciones). '
                    f"{'Datos de la planilla del curso' if es_real else 'Datos simulados'}: {len(d)} días por línea.</div>", unsafe_allow_html=True)
    with st.expander("Ver datos del período"):
        st.dataframe(v[["fecha", "unidades", "defectos", "tasa"]].rename(columns={"tasa": "tasa_defectos"}), width="stretch", hide_index=True)

    if es_real:
        seccion("Efecto del turno", "Tasa de defectos de cada turno en el período completo. La tarde produce más defectos en las tres líneas.")
        tt = TURNOS_REAL.copy()
        tt["Línea"] = tt["linea"].map(etiqueta_linea)
        tt["Turno"] = tt["turno"].map({"Manana": "Mañana", "Tarde": "Tarde"}).fillna(tt["turno"])
        gtu = alt.Chart(tt).mark_bar(cornerRadiusEnd=4, size=26).encode(
            y=alt.Y("Línea:N", title=None, sort=None), x=alt.X("tasa:Q", title="Tasa de defectos", axis=alt.Axis(format=".1%")),
            yOffset="Turno:N", color=alt.Color("Turno:N", legend=LEYENDA, scale=alt.Scale(domain=["Mañana", "Tarde"], range=["#7fb2ec", NAVY])),
            tooltip=[alt.Tooltip("Línea:N"), alt.Tooltip("Turno:N"), alt.Tooltip("tasa:Q", title="Tasa", format=".2%"),
                     alt.Tooltip("detencion:Q", title="Detención media (min)", format=".0f")])
        with st.container(border=True):
            st.altair_chart(estilo(gtu, 230), theme=None, width="stretch")
        seccion("Calidad de los datos", "Origen, limpieza y validación de la planilla (requisito de datos).")
        inf = INFORME_REAL
        desc = inf["descartadas"]
        q = st.columns(4)
        q[0].markdown(tarjeta("Filas de entrada", f"{inf['filas_entrada']}", "una por fecha, línea y turno"), unsafe_allow_html=True)
        q[1].markdown(tarjeta("Filas válidas", f"{inf['filas_validas']}", f"{DF_REAL['fecha'].nunique()} días × {len(LINEAS_REAL)} líneas"), unsafe_allow_html=True)
        q[2].markdown(tarjeta("Descartadas", f"{inf['filas_descartadas']}", f"{desc['sin_linea']} sin línea · {desc['sin_unidades']} sin unidades", "bad" if inf["filas_descartadas"] else ""), unsafe_allow_html=True)
        q[3].markdown(tarjeta("Reglas de validación", "5", "fecha, línea, unidades > 0, defectos ≥ 0 y ≤ unidades"), unsafe_allow_html=True)

# ---------------------------------------------------------------- 2. modelos
with tab2:
    glob = pd.DataFrame([{"Modelo": MODELOS[m][0], "MAE global (pp)": res["mae"][m]["global"] * 100} for m in MODELOS]).sort_values("MAE global (pp)")
    elegido_img = img[img["modelo"] != "simple (reg. logística)"].sort_values("costo_total").iloc[0]
    elegido_rag = rag[rag["metodo"].str.contains("elegido")].iloc[0]
    c1, c2, c3 = st.columns(3)
    c1.markdown(tarjeta("Series de tiempo", glob.iloc[0]["Modelo"], f"menor error global ({glob.iloc[0]['MAE global (pp)']:.3f} pp)".replace(".", ","), texto=True), unsafe_allow_html=True)
    c2.markdown(tarjeta("Imágenes", {"resnet18": "ResNet18", "mobilenet_v2": "MobileNetV2"}[elegido_img["modelo"]],
                        f"{int(elegido_img['falsos_negativos'])} defectuosas que pasan · {int(elegido_img['falsos_positivos'])} buenas descartadas", texto=True), unsafe_allow_html=True)
    c3.markdown(tarjeta("Búsqueda en el manual", "Embeddings e5", f"acierta en el top 3 el {elegido_rag['hit@3'] * 100:.0f} % de las consultas", texto=True), unsafe_allow_html=True)

    seccion("Series de tiempo (historia simulada)", "El deep learning necesita muchos datos: se comparan los modelos sobre 730 días simulados, con 120 días de prueba nunca vistos al entrenar.")
    ctrl1, ctrl2 = st.columns([1, 2])
    lin2 = ctrl1.segmented_control("Línea", LINEAS, default="L2", key="linea2") or "L2"
    elegidos = ctrl2.multiselect("Modelos a comparar (máximo 3)", list(MODELOS), default=["promedio_movil_7d", "holt", "gru"],
                                 format_func=lambda m: MODELOS[m][0], max_selections=3)
    fechas = pd.to_datetime(res["fechas_prueba"])
    filas = [pd.DataFrame({"fecha": fechas, "serie": "Real", "valor": res["real"][lin2]})]
    for m in elegidos:
        filas.append(pd.DataFrame({"fecha": fechas, "serie": MODELOS[m][0], "valor": res["pronosticos"][m][lin2]}))
    largo = pd.concat(filas)
    largo["fecha_txt"] = largo["fecha"].map(fecha_es)
    dom = ["Real"] + [MODELOS[m][0] for m in elegidos]
    rng = ["#b0b7c3"] + [MODELOS[m][1] for m in elegidos]
    g = alt.Chart(largo).mark_line(interpolate="monotone").encode(
        x=alt.X("fecha:T", axis=EJE_X),
        y=alt.Y("valor:Q", title="Tasa de defectos", axis=alt.Axis(format=".1%")),
        color=alt.Color("serie:N", legend=LEYENDA, scale=alt.Scale(domain=dom, range=rng)),
        strokeWidth=alt.StrokeWidth("serie:N", legend=LEYENDA, scale=alt.Scale(domain=dom, range=[1.2] + [2.6] * len(elegidos))),
        tooltip=[alt.Tooltip("fecha_txt:N", title="Fecha"), alt.Tooltip("serie:N", title="Serie"), alt.Tooltip("valor:Q", title="Valor", format=".2%")],
    )
    with st.container(border=True):
        st.altair_chart(estilo(g, 320), theme=None, width="stretch")

    mae = pd.DataFrame([{"Modelo": MODELOS[m][0], "MAE (pp)": res["mae"][m][lin2] * 100} for m in MODELOS]).sort_values("MAE (pp)")
    m1, m2 = st.columns(2)
    m1.markdown(f"**Error medio absoluto en {lin2}** · menor es mejor")
    m1.dataframe(mae.style.format({"MAE (pp)": "{:.3f}"}).highlight_min(subset=["MAE (pp)"], color="#e6f4ea"), hide_index=True, width="stretch")
    m2.markdown("**Promedio de las tres líneas**")
    m2.dataframe(glob.style.format({"MAE global (pp)": "{:.3f}"}).highlight_min(subset=["MAE global (pp)"], color="#e6f4ea"), hide_index=True, width="stretch")
    st.info(f"En {lin2} el menor error lo tiene **{mae.iloc[0]['Modelo']}**; en el promedio de las tres líneas, **{glob.iloc[0]['Modelo']}**. "
            "El período de prueba incluye el cambio de nivel de L2 y un valor atípico de L3 que ningún modelo vio al entrenar. "
            "Una sola partición cronológica y 5 semillas por red: las diferencias pequeñas no son concluyentes.")

    seccion("Imágenes", "Detección de pieza defectuosa en el conjunto de prueba (715 imágenes de fundición).")
    i = img.copy()
    i["modelo"] = i["modelo"].replace({"simple (reg. logística)": "Alternativa simple (reg. logística)", "resnet18": "ResNet18", "mobilenet_v2": "MobileNetV2"})
    tabla = i[["modelo", "recall_defecto", "precision", "f1", "falsos_negativos", "falsos_positivos", "costo_total", "ms_por_imagen_cpu", "tamano_MB"]]
    tabla.columns = ["Modelo", "Recall defecto", "Precisión", "F1", "Defectuosas que pasan (FN)", "Buenas descartadas (FP)", "Costo", "ms/imagen CPU", "MB"]
    # Streamlit muestra "None" en celdas vacias: las dos columnas del modelo simple pasan a texto con un guion
    tabla = tabla.assign(**{"ms/imagen CPU": pd.to_numeric(tabla["ms/imagen CPU"], errors="coerce").map(lambda x: "–" if pd.isna(x) else f"{x:.0f}"),
                            "MB": pd.to_numeric(tabla["MB"], errors="coerce").map(lambda x: "–" if pd.isna(x) else f"{x:.1f}")})
    st.dataframe(tabla.style.format({"Recall defecto": "{:.1%}", "Precisión": "{:.1%}", "F1": "{:.3f}"}),
                 hide_index=True, width="stretch")
    err = i.melt(id_vars="modelo", value_vars=["falsos_negativos", "falsos_positivos"], var_name="tipo", value_name="piezas")
    err["tipo"] = err["tipo"].map({"falsos_negativos": "Defectuosas que pasan (FN)", "falsos_positivos": "Buenas descartadas (FP)"})
    ge = alt.Chart(err).mark_bar(cornerRadiusEnd=4, size=16).encode(
        y=alt.Y("modelo:N", title=None, sort=None, axis=alt.Axis(labelLimit=300)), x=alt.X("piezas:Q", title="Piezas mal clasificadas"),
        yOffset="tipo:N", color=alt.Color("tipo:N", legend=LEYENDA, scale=alt.Scale(domain=["Defectuosas que pasan (FN)", "Buenas descartadas (FP)"], range=[ROJO, AZUL])),
        tooltip=[alt.Tooltip("modelo:N", title="Modelo"), alt.Tooltip("tipo:N", title="Tipo"), alt.Tooltip("piezas:Q", title="Piezas")])
    with st.container(border=True):
        st.altair_chart(estilo(ge, 200), theme=None, width="stretch")
    st.markdown('<div class="nota">Umbral elegido en validación minimizando costo (un falso negativo cuesta 10 veces un falso positivo: supuesto del equipo). '
                "Dataset <i>Casting product image data</i> (Kaggle, CC BY-NC-ND 4.0), uso académico; las imágenes no se redistribuyen. "
                "El resultado es casi perfecto porque el dataset es homogéneo: no se espera igual rendimiento con otra cámara o producto.</div>", unsafe_allow_html=True)

    seccion("Búsqueda en el manual (RAG)", "Qué tan arriba queda el fragmento correcto del manual para cada consulta.")
    r = rag.copy()
    r.columns = ["Método", "Acierta en 1.º", "Acierta en top 3", "MRR", "Consultas"]
    st.dataframe(r.style.format({"Acierta en 1.º": "{:.1%}", "Acierta en top 3": "{:.1%}", "MRR": "{:.3f}"}), hide_index=True, width="stretch")
    st.markdown('<div class="nota">26 consultas escritas por el mismo autor del manual (simulado): la evaluación es optimista y la ventaja de los '
                "embeddings sobre TF-IDF es de pocas consultas.</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------- 3. registro del LLM
with tab3:
    url = url_registro()
    if not url:
        st.warning("Falta conectar el registro. Publica en la web la pestaña `registro_hito2` de la hoja de Google como CSV "
                   "y define su enlace en el secret `registro_csv_url` (o en la variable REGISTRO_CSV_URL).")
    else:
        try:
            reg = cargar_registro(url)
        except Exception as e:  # noqa: BLE001 - se muestra el motivo al usuario
            st.error(f"No se pudo leer el registro: {e}")
            reg = None
        if reg is not None and reg.empty:
            st.info("El registro aún no tiene filas.")
        elif reg is not None:
            seccion("Recomendaciones", "Elige cualquiera para verla completa; la más reciente aparece primero.")
            f1, f2 = st.columns(2)
            lineas_reg = sorted(reg["linea"].dropna().astype(str).unique())
            sel_l = f1.multiselect("Línea", lineas_reg, default=lineas_reg, format_func=etiqueta_linea)
            sel_a = f2.multiselect("Acción", list(ACCIONES), default=list(ACCIONES), format_func=lambda m: ACCIONES[m])
            r = reg[reg["linea"].isin(sel_l) & reg["accion"].isin(sel_a)]
            if r.empty:
                st.info("No hay recomendaciones con esos filtros.")
            else:
                def etiqueta(i):
                    f = r.loc[i]
                    return f'{f["fecha_ejecucion"]:%d-%m-%Y %H:%M}  ·  {etiqueta_linea(f["linea"])}  ·  {ACCIONES.get(f["accion"], f["accion"])}' + ("   (más reciente)" if i == reg.index[0] else "")
                elegida = st.selectbox("Ver recomendación", list(r.index), format_func=etiqueta)
                u = r.loc[elegida]
                txt_dec, cls_dec = DECISIONES.get(u["estado_decision"], (u["estado_decision"], "neutral"))
                citas = "".join(f'<span class="cita">{c.strip()}</span>' for c in str(u["citas"]).split(",") if c.strip() and c.strip() != "nan")
                prob = pd.to_numeric(u["prob_defecto"], errors="coerce")
                foto = f'{u["clasificacion_imagen"]}' + (f" (prob. de defecto {pct(prob, 1)})" if pd.notna(prob) else "")
                st.markdown(
                    f'<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">'
                    f'<div><span class="nombre">{etiqueta_linea(u["linea"])}</span> <span style="color:#667085;font-size:13px">· {u["fecha_ejecucion"]:%d-%m-%Y %H:%M}</span></div>'
                    f'<div>{pill(ACCIONES.get(u["accion"], u["accion"]), CLASE_ACCION.get(u["accion"], "neutral"))} {pill(txt_dec, cls_dec)}</div></div>'
                    f'<div class="fila"><span>Estado de la serie</span><b>{ESTADOS.get(u["estado_serie"], u["estado_serie"])}</b></div>'
                    f'<div class="fila"><span>Foto de la pieza</span><b>{foto}</b></div>'
                    f'<p style="margin:12px 0 4px;color:#101828">{u["diagnostico"]}</p>'
                    f'<p style="margin:0 0 6px;color:#475467;font-style:italic;font-size:14px">{u["justificacion"]}</p>{citas}</div>',
                    unsafe_allow_html=True)

                seccion("Resumen del historial")
                k = st.columns(4)
                k[0].markdown(tarjeta("Recomendaciones", str(len(r))), unsafe_allow_html=True)
                k[1].markdown(tarjeta("Propuestas de detener", str(int((r["accion"] == "detener_linea").sum())), "acción crítica"), unsafe_allow_html=True)
                k[2].markdown(tarjeta("Aprobadas por humano", str(int((r["estado_decision"] == "aprobada").sum()))), unsafe_allow_html=True)
                k[3].markdown(tarjeta("No aprobadas / sin respuesta", str(int((r["estado_decision"] == "no_aprobada").sum()))), unsafe_allow_html=True)
                c = r.groupby("accion").size().reset_index(name="n")
                c["accion"] = c["accion"].map(ACCIONES).fillna(c["accion"])
                gb = alt.Chart(c).mark_bar(cornerRadiusEnd=4, color=AZUL, size=18).encode(
                    x=alt.X("n:Q", title="Recomendaciones", axis=alt.Axis(tickMinStep=1)), y=alt.Y("accion:N", title=None, sort="-x"),
                    tooltip=[alt.Tooltip("accion:N", title="Acción"), alt.Tooltip("n:Q", title="Recomendaciones")])
                with st.container(border=True):
                    st.altair_chart(estilo(gb, 40 + 38 * len(c)), theme=None, width="stretch")

                with st.expander("Ver todas las ejecuciones en una tabla"):
                    vista = r[["fecha_ejecucion", "linea", "estado_serie", "clasificacion_imagen", "prob_defecto", "accion", "prioridad",
                               "estado_decision", "citas", "diagnostico", "justificacion"]].copy()
                    vista["accion"] = vista["accion"].map(ACCIONES).fillna(vista["accion"])
                    st.dataframe(vista, hide_index=True, width="stretch")
                st.markdown('<div class="nota">La acción la fija una regla del manual; el LLM la explica y cita los fragmentos (MAN-xx). '
                            "La detención de línea solo se ejecuta si un humano la aprueba.</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------- 4. negocio y ROI
def usd(x):
    return ("−" if x < 0 else "") + "US$ " + f"{abs(x):,.0f}".replace(",", ".")


MILES = "replace(format(datum.value, ',.0f'), ',', '.')"  # miles con punto, como se escribe en español
ETIQ = {"demora_manual": "Días que tarda la revisión manual", "cambios_por_anio": "Cambios de nivel por año",
        "aumento_tasa": "Aumento de defectos en un cambio", "costo_desecho": "Costo de una pieza desechada",
        "piezas_dia_linea": "Piezas por día y línea", "razon_escape": "Sobrecosto si llega al cliente",
        "prob_escape": "Defectos que pasan la inspección final", "costo_hora_parada": "Costo de una hora detenida",
        "horas_implementacion": "Horas de implementación", "horas_mantencion_mes": "Horas de mantención al mes",
        "costo_hora_tecnico": "Costo hora técnico", "prob_parada_sin_sis": "Paradas evitadas (prob.)",
        "atipicos_por_anio": "Valores atípicos por año", "horas_parada": "Horas por parada innecesaria",
        "costo_camara": "Costo de cámara por línea", "servidor_mensual": "Servidor al mes"}
COLOR_ESC = {"Pesimista": ROJO, "Base": AZUL, "Optimista": VERDE}

with tab4:
    st.markdown('<div class="nota" style="margin-bottom:6px"><b>Cifras supuestas.</b> No hay datos de una planta real: los costos y frecuencias son '
                "supuestos del equipo, declarados y editables. Solo la demora de detección y las falsas alarmas están <b>medidas</b> con el propio sistema.</div>",
                unsafe_allow_html=True)
    seccion("Resultado económico", "Beneficio de detectar antes un cambio de nivel y de evitar paradas innecesarias, frente al costo del sistema (3 años).")
    nombre_esc = st.segmented_control("Escenario", list(roi.ESCENARIOS), default="Base", key="esc") or "Base"
    base_esc = {**roi.BASE, **roi.ESCENARIOS[nombre_esc]}
    with st.expander("Editar supuestos principales"):
        e1, e2, e3 = st.columns(3)
        ajuste = {
            "cambios_por_anio": e1.slider("Cambios de nivel por año", 0.0, 6.0, float(base_esc["cambios_por_anio"]), 0.25, key=f"{nombre_esc}_c"),
            "demora_manual": e2.slider("Días que tarda la revisión manual", 3, 21, int(base_esc["demora_manual"]), key=f"{nombre_esc}_d"),
            "costo_desecho": e3.slider("Costo de una pieza desechada (US$)", 5, 80, int(base_esc["costo_desecho"]), key=f"{nombre_esc}_s"),
            "razon_escape": e1.slider("Sobrecosto si llega al cliente (veces)", 2, 30, int(base_esc["razon_escape"]), key=f"{nombre_esc}_r"),
            "prob_escape": e2.slider("Defectos que pasan la inspección final", 0.0, 0.5, float(base_esc["prob_escape"]), 0.01, key=f"{nombre_esc}_p"),
            "costo_hora_parada": e3.slider("Costo de una hora detenida (US$)", 200, 3000, int(base_esc["costo_hora_parada"]), 50, key=f"{nombre_esc}_h"),
        }
    r = roi.calcular({**roi.ESCENARIOS[nombre_esc], **ajuste})
    k = st.columns(4)
    k[0].markdown(tarjeta("Beneficio anual", usd(r["beneficio_anual"]), f"detección temprana {usd(r['beneficio_a'])} · paradas evitadas {usd(r['beneficio_b'])}"), unsafe_allow_html=True)
    k[1].markdown(tarjeta("Inversión inicial", usd(r["inversion"]), f"operación anual {usd(r['operacion_anual'])}"), unsafe_allow_html=True)
    k[2].markdown(tarjeta("ROI a 3 años", f"{r['roi'] * 100:.0f} %".replace(".", ","), "sobre el costo total del período",
                          "ok" if r["roi"] > 0 else "bad"), unsafe_allow_html=True)
    k[3].markdown(tarjeta("Recuperación de la inversión", (f"{r['payback_meses']:.1f} meses".replace(".", ",") if r["payback_meses"] else "No se recupera"),
                          "con el beneficio neto anual", "ok" if r["payback_meses"] else "bad"), unsafe_allow_html=True)

    flujo = []
    for n in roi.ESCENARIOS:
        rr = roi.calcular(roi.ESCENARIOS[n]) if n != nombre_esc else r
        acum = [-rr["inversion"]] + rr["flujo_acumulado"]
        flujo += [{"Año": a, "Escenario": n, "Beneficio neto acumulado (US$)": v} for a, v in enumerate(acum)]
    gf = alt.Chart(pd.DataFrame(flujo)).mark_line(point=alt.OverlayMarkDef(size=70, filled=True), strokeWidth=3).encode(
        x=alt.X("Año:O", title="Año", axis=alt.Axis(labelAngle=0)),
        y=alt.Y("Beneficio neto acumulado (US$):Q", axis=alt.Axis(labelExpr=MILES)),
        color=alt.Color("Escenario:N", legend=LEYENDA, scale=alt.Scale(domain=list(COLOR_ESC), range=list(COLOR_ESC.values()))),
        tooltip=["Escenario", "Año", alt.Tooltip("Beneficio neto acumulado (US$):Q", format=",.0f")])
    cero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#98a2b3", strokeDash=[4, 4]).encode(
        y=alt.Y("y:Q", title="Beneficio neto acumulado (US$)"))
    with st.container(border=True):
        st.altair_chart(estilo(alt.layer(cero, gf), 320), theme=None, width="stretch")
        st.markdown('<div class="nota">El año 0 es la inversión inicial; la línea cruza el cero cuando el sistema se ha pagado. '
                    "El escenario optimista es un techo, no una expectativa.</div>", unsafe_allow_html=True)

    eq = roi.cambios_para_equilibrio({**roi.ESCENARIOS[nombre_esc], **ajuste})
    medidos = roi.MEDIDO["falsas_alarmas_por_anio_planta"]
    m = st.columns(3)
    m[0].markdown(tarjeta("Demora de detección (medida)", f"{roi.DEMORA_SISTEMA} días", f"contra {ajuste['demora_manual']} días de la revisión manual supuesta"), unsafe_allow_html=True)
    m[1].markdown(tarjeta("Falsas alarmas (medidas)", f"{roi.FALSAS_POR_ANIO:.1f} por año".replace(".", ","),
                          "ninguna propuso detener la línea: costaron revisión, no paradas"), unsafe_allow_html=True)
    m[2].markdown(tarjeta("Punto de equilibrio", (f"{eq:.2f} cambios/año".replace(".", ",") if eq is not None else "–"),
                          "cambios de nivel por año con los que el ROI a 3 años es cero"), unsafe_allow_html=True)

    seccion("¿Qué supuestos mueven más el resultado?", "Cambio en el beneficio neto a 3 años al subir o bajar cada supuesto un 30 %, con los demás en el caso base.")
    sens = pd.DataFrame(roi.sensibilidad()).head(8)
    sens["Supuesto"] = sens["supuesto"].map(ETIQ).fillna(sens["supuesto"])
    largo = sens.melt(id_vars=["Supuesto"], value_vars=["baja", "sube"], var_name="Cambio", value_name="Efecto")
    largo["Cambio"] = largo["Cambio"].map({"baja": "Supuesto −30 %", "sube": "Supuesto +30 %"})
    gt = alt.Chart(largo).mark_bar(cornerRadius=3, size=14).encode(
        y=alt.Y("Supuesto:N", sort=list(sens["Supuesto"]), title=None, axis=alt.Axis(labelLimit=320)),
        x=alt.X("Efecto:Q", title="Efecto en el beneficio neto a 3 años (US$)", axis=alt.Axis(labelExpr=MILES)),
        yOffset="Cambio:N", color=alt.Color("Cambio:N", legend=LEYENDA, scale=alt.Scale(domain=["Supuesto −30 %", "Supuesto +30 %"], range=[NARANJA, AZUL])),
        tooltip=["Supuesto", "Cambio", alt.Tooltip("Efecto:Q", format=",.0f")])
    with st.container(border=True):
        st.altair_chart(estilo(gt, 40 + 46 * len(sens)), theme=None, width="stretch")

    seccion("Riesgos y sesgos", "Lo que podría hacer que estas cifras o el sistema fallen, y cómo se mitiga.")
    riesgos = [
        ("Datos simulados", "Las series y el manual son inventados; el ROI no se puede extrapolar a una planta real sin sus datos.", "Declarado en todo el sistema; calibrar con datos reales antes de decidir."),
        ("Una sola pieza y cámara", "El modelo de imágenes se entrenó con un tipo de pieza y encuadre. Con otra cámara, luz o producto puede fallar sin avisar (probó 100 % de probabilidad con una imagen de ruido).", "Validar con fotos de la planta; la foto solo confirma, no decide sola."),
        ("Falsas alarmas por referencia fija", "El gráfico de control usa los primeros 60 días como referencia. Con una deriva lenta aparecen alertas falsas (unas 8 por año), aunque ninguna propuso detener.", "Recalcular la referencia periódicamente; el humano revisa cada alerta."),
        ("Falso negativo", "Una pieza defectuosa que pasa como buena es el error más caro (10 veces el de un falso positivo, supuesto).", "Umbral bajo (0,16) elegido por costo; recall del 100 % en prueba, no garantizado en planta."),
        ("Sesgo de automatización", "Una persona puede aprobar por inercia lo que el sistema recomienda.", "El mensaje muestra la evidencia y la cita del manual; rechazar es igual de fácil."),
        ("Errores del LLM", "Puede redactar mal o inventar. Ya escribió mal “línea” y confundió “superar la meta” con estar bajo ella.", "La acción la fija una regla; solo se aceptan citas de fragmentos recuperados; se corrige la ortografía."),
        ("Evaluaciones optimistas", "El manual y las preguntas de prueba del RAG las escribió la misma persona; el conjunto de imágenes es homogéneo.", "Declarado; ampliar con preguntas de otros integrantes y datos reales."),
        ("Dependencia de servicios", "Gemini, Gmail, WhatsApp (número de prueba) y Google Sheets pueden caer o cambiar; las credenciales de Google caducan a los 7 días.", "Flujo de errores con alerta por correo; plan de contingencia y reconexión programada."),
    ]
    cols = st.columns(2)
    for i, (tit, riesgo, mitig) in enumerate(riesgos):
        cols[i % 2].markdown(f'<div class="card" style="margin-bottom:14px"><div class="nombre" style="font-size:16px">{tit}</div>'
                             f'<p style="margin:8px 0 6px;color:#344054;font-size:14px">{riesgo}</p>'
                             f'<p style="margin:0;color:#137333;font-size:13px"><b>Mitigación:</b> {mitig}</p></div>', unsafe_allow_html=True)

    with st.expander("Ver todos los supuestos del modelo"):
        sup = pd.DataFrame([{"Supuesto": ETIQ.get(k, v[2]), "Valor base": v[0], "Unidad": v[1], "Descripción": v[2], "Origen": v[3]} for k, v in roi.SUPUESTOS.items()])
        st.dataframe(sup, hide_index=True, width="stretch")

st.markdown('<div class="pie">Felipe Alonso · Sofia Fariña · Vicente Lagunas · IA Generativa para la gestión industrial · '
            "Series y manual simulados: análisis de ejemplo, no una planta real.</div>", unsafe_allow_html=True)
