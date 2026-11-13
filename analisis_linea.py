"""Analisis de la serie temporal de defectos de UNA linea (Caso A).

Entrada: filas de la hoja `datos` de una linea, en orden cronologico.
Salida: indicadores, comparacion Holt vs promedio movil y estado de la linea.
Solo biblioteca estandar. Lo usa servicio_analisis.py, que n8n llama por HTTP.
"""

META_TASA = 0.025       # meta de calidad: tasa de defectos <= 2,5 %
BASE_DIAS = 60          # fase I del grafico de control: primeros 60 dias
VENTANA = 7             # dias para promedio movil y mediana reciente
EVAL_DIAS = 30          # dias sobre los que se mide el error de cada modelo
ALPHA, BETA = 0.3, 0.1  # parametros de Holt


def media(v):
    return sum(v) / len(v)


def desv(v):
    m = media(v)
    return (sum((x - m) ** 2 for x in v) / (len(v) - 1)) ** 0.5


def mediana(v):
    s = sorted(v)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def _num(v):
    """Numero o None. Acepta texto con coma decimal y trata vacio/NaN como dato faltante."""
    if v is None:
        return None
    try:
        x = float(str(v).replace(",", ".").strip())
    except ValueError:
        return None
    return None if x != x else x


def preparar_produccion(filas):
    """Limpia y agrega por dia la planilla `produccion_planta` (una fila por fecha, linea y turno).

    Columnas: fecha, linea, turno, unidades_producidas, unidades_defectuosas, minutos_detencion.
    Descarta filas sin fecha, sin linea, con unidades vacias o <= 0, defectos negativos o mayores que las unidades.
    Devuelve (filas_diarias, informe): las filas diarias (suma de los turnos) alimentan a `analizar`;
    el informe documenta la limpieza y resume la tasa de defectos y la detencion por turno.
    """
    descartadas = {"sin_fecha": 0, "sin_linea": 0, "sin_unidades": 0, "incoherentes": 0}
    validas = []
    for f in filas:
        fecha = str(f.get("fecha") or "").strip()[:10]
        linea = str(f.get("linea") or "").strip()
        if linea.lower() in ("", "nan", "none"):
            linea = ""
        u, d = _num(f.get("unidades_producidas")), _num(f.get("unidades_defectuosas"))
        if not fecha:
            descartadas["sin_fecha"] += 1
        elif not linea:
            descartadas["sin_linea"] += 1
        elif u is None or u <= 0:
            descartadas["sin_unidades"] += 1
        elif d is None or d < 0 or d > u:
            descartadas["incoherentes"] += 1
        else:
            validas.append({"fecha": fecha, "linea": linea, "turno": str(f.get("turno") or "sin turno").strip(),
                            "u": u, "d": d, "m": _num(f.get("minutos_detencion")) or 0.0})

    dias = {}
    for v in validas:
        dia = dias.setdefault((v["linea"], v["fecha"]), {"unidades": 0.0, "defectos": 0.0, "minutos_detencion": 0.0})
        dia["unidades"] += v["u"]
        dia["defectos"] += v["d"]
        dia["minutos_detencion"] += v["m"]
    diarias = [{"fecha": fe, "linea": li, "unidades": int(x["unidades"]), "defectos": int(x["defectos"]),
                "minutos_detencion": int(x["minutos_detencion"])}
               # orden de aparicion (la hoja es cronologica); solo se agrupa por linea. No se ordena por el texto de la fecha:
               # segun la configuracion regional Google Sheets la entrega como "5/1/2026" y se desordenaria la serie
               for (li, fe), x in sorted(dias.items(), key=lambda k: k[0][0])]

    turnos = {}
    for v in validas:
        t = turnos.setdefault(v["turno"], {"unidades": 0.0, "defectos": 0.0, "minutos": 0.0, "turnos": 0})
        t["unidades"] += v["u"]
        t["defectos"] += v["d"]
        t["minutos"] += v["m"]
        t["turnos"] += 1
    resumen_turnos = {n: {"tasa_defectos": round(t["defectos"] / t["unidades"], 5), "detencion_media_min": round(t["minutos"] / t["turnos"], 1),
                          "turnos_registrados": t["turnos"]} for n, t in turnos.items()}
    informe = {"filas_entrada": len(filas), "filas_validas": len(validas), "filas_descartadas": sum(descartadas.values()),
               "descartadas": descartadas, "dias": len(diarias), "turnos": resumen_turnos}
    return diarias, informe


def analizar(filas):
    # Limpieza y validacion: se descartan filas incompletas o incoherentes
    limpias = []
    descartadas = 0
    for f in filas:
        try:
            u = int(float(str(f["unidades"]).replace(",", ".")))
            d = int(float(str(f["defectos"]).replace(",", ".")))
        except (KeyError, ValueError):
            descartadas += 1
            continue
        if u <= 0 or d < 0 or d > u:
            descartadas += 1
            continue
        limpias.append({"fecha": str(f.get("fecha", "")), "linea": f.get("linea"), "u": u, "d": d})

    if len(limpias) < BASE_DIAS + VENTANA:
        raise ValueError("Datos insuficientes: %d filas validas" % len(limpias))

    y = [r["d"] / r["u"] for r in limpias]  # tasa diaria de defectos
    n = len(y)

    # Modelo 1: Holt (suavizamiento exponencial doble), pronostico a un paso
    nivel, tend = y[0], y[1] - y[0]
    f_holt = {}
    for t in range(1, n):
        f_holt[t] = nivel + tend
        nuevo = ALPHA * y[t] + (1 - ALPHA) * (nivel + tend)
        tend = BETA * (nuevo - nivel) + (1 - BETA) * tend
        nivel = nuevo
    prox_holt = nivel + tend

    # Modelo base simple: promedio movil de 7 dias
    f_mm = {t: media(y[t - VENTANA:t]) for t in range(VENTANA, n)}
    prox_mm = media(y[-VENTANA:])

    # Error absoluto medio de cada modelo en los ultimos 30 dias
    ts = range(n - EVAL_DIAS, n)
    mae_holt = media([abs(y[t] - f_holt[t]) for t in ts])
    mae_mm = media([abs(y[t] - f_mm[t]) for t in ts])

    # Grafico de control (fase I) con los primeros 60 dias
    base = y[:BASE_DIAS]
    mu, sd = media(base), desv(base)
    lcs = mu + 3 * sd

    # Cambio de nivel: mediana de los ultimos 7 dias, robusta a un dia aislado
    med7 = mediana(y[-VENTANA:])
    z_nivel = (med7 - mu) / (sd / VENTANA ** 0.5)
    cambio_nivel = z_nivel > 3

    # Valor atipico: algun punto de los ultimos 3 dias sobre el limite de control
    max3 = max(y[-3:])
    atipico = max3 > lcs and not cambio_nivel

    if cambio_nivel:
        estado = "cambio_de_nivel"
    elif atipico:
        estado = "valor_atipico"
    else:
        estado = "estable"

    return {
        "linea": limpias[-1]["linea"],
        "fecha_ultima": limpias[-1]["fecha"],
        "dias_analizados": n,
        "filas_descartadas": descartadas,
        "estado": estado,
        "tasa_ultima": round(y[-1], 5),
        "tasa_media_7d": round(media(y[-VENTANA:]), 5),
        "tasa_mediana_7d": round(med7, 5),
        "max_tasa_ultimos_3d": round(max3, 5),
        "media_base": round(mu, 5),
        "desv_base": round(sd, 5),
        "limite_control_sup": round(lcs, 5),
        "z_nivel": round(z_nivel, 2),
        "meta_tasa": META_TASA,
        "razon_meta": round(med7 / META_TASA, 2),  # tasa mediana 7d / meta
        "pronostico_holt": round(prox_holt, 5),
        "pronostico_promedio_movil": round(prox_mm, 5),
        "mae_holt": round(mae_holt, 5),
        "mae_promedio_movil": round(mae_mm, 5),
        "mejor_modelo": "holt" if mae_holt < mae_mm else "promedio_movil",
    }
