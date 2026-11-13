"""Modelo de negocio del Hito 2: beneficio, costo, ROI y sensibilidad del sistema de control de calidad.

IMPORTANTE: casi todas las cifras son SUPUESTOS del equipo (no hay datos de una planta real). Estan declaradas
una a una en SUPUESTOS y se pueden cambiar. Lo unico MEDIDO con el propio sistema es la demora de deteccion
(3 dias) y las falsas alarmas (ver negocio/medir_deteccion.py y datos/deteccion_medida.json).

Logica del beneficio:
  A. Deteccion temprana de un cambio de nivel: se evita producir piezas defectuosas durante los dias en que
     el sistema detecta antes que la revision manual. Cada pieza defectuosa evitada ahorra su costo de
     desecho y, con probabilidad p_escape, el costo mucho mayor de que llegue al cliente.
  B. Paradas innecesarias evitadas: ante un valor atipico aislado el sistema pide revision humana en vez
     de detener la linea.
Costos: inversion inicial (implementacion y camaras), operacion anual (servidor, API del LLM, mantenimiento)
y tiempo humano para revisar alarmas falsas.
"""
import json
from copy import deepcopy
from pathlib import Path

AQUI = Path(__file__).parent
try:
    MEDIDO = json.loads((AQUI / "datos" / "deteccion_medida.json").read_text(encoding="utf-8"))
except FileNotFoundError:  # el modelo funciona igual con valores por defecto
    MEDIDO = {"demora_deteccion_dias": 3, "falsas_alarmas_por_anio_planta": {"cambio_de_nivel": 5.5, "valor_atipico": 2.75}}

DEMORA_SISTEMA = MEDIDO["demora_deteccion_dias"]                      # medido
FALSAS_POR_ANIO = sum(MEDIDO["falsas_alarmas_por_anio_planta"][k] for k in ("cambio_de_nivel", "valor_atipico"))  # medido

# nombre -> (valor base, unidad, descripcion, origen)
SUPUESTOS = {
    "piezas_dia_linea":      (1000,  "piezas/día",  "Producción diaria de cada línea", "simulación del Hito 1"),
    "lineas":                (3,     "líneas",      "Líneas de la planta", "caso A"),
    "dias_anio":             (330,   "días/año",    "Días de operación por año", "supuesto"),
    "costo_desecho":         (20,    "USD/pieza",   "Costo de una pieza defectuosa detectada en planta (material y proceso)", "supuesto"),
    "razon_escape":          (10,    "veces",       "Cuántas veces más cuesta una pieza defectuosa que llega al cliente", "supuesto (el mismo 10:1 del modelo de imágenes)"),
    "prob_escape":           (0.15,  "fracción",    "Fracción de defectuosas extra que pasa la inspección final", "supuesto"),
    "cambios_por_anio":      (2.0,   "eventos/año", "Cambios de nivel sostenidos en la planta", "supuesto (la simulación tiene 0,5/año)"),
    "aumento_tasa":          (0.016, "fracción",    "Aumento de la tasa de defectos durante un cambio de nivel (L2: 2,2 % a 3,8 %)", "simulación"),
    "demora_manual":         (10,    "días",        "Días que tarda la revisión manual de planillas en detectar el cambio", "supuesto"),
    "atipicos_por_anio":     (1.5,   "eventos/año", "Valores atípicos reales en la planta", "medido en la simulación (3 en 2 años)"),
    "prob_parada_sin_sis":   (0.5,   "fracción",    "Probabilidad de que, sin el sistema, un atípico termine en parada de línea", "supuesto"),
    "horas_parada":          (2,     "horas",       "Duración de una parada innecesaria", "supuesto"),
    "costo_hora_parada":     (1250,  "USD/hora",    "Costo de una hora de línea detenida (62,5 piezas/h × 20 USD de margen)", "supuesto"),
    "horas_implementacion":  (120,   "horas",       "Horas de implementación del sistema", "supuesto"),
    "costo_hora_tecnico":    (25,    "USD/hora",    "Costo de una hora de trabajo técnico", "supuesto"),
    "costo_camara":          (400,   "USD/línea",   "Cámara e iluminación por línea", "supuesto"),
    "servidor_mensual":      (30,    "USD/mes",     "Servidor o equipo donde corre el sistema", "supuesto"),
    "api_llm_anual":         (100,   "USD/año",     "Consumo de la API del LLM", "supuesto"),
    "horas_mantencion_mes":  (6,     "horas/mes",   "Mantención y ajuste del sistema", "supuesto"),
    "horas_revision_alarma": (0.5,   "horas",       "Tiempo humano para revisar una alarma falsa", "supuesto"),
    "costo_hora_analista":   (30,    "USD/hora",    "Costo de una hora del responsable de calidad", "supuesto"),
}
BASE = {k: v[0] for k, v in SUPUESTOS.items()}

ESCENARIOS = {  # solo se listan los supuestos que cambian respecto del caso base
    "Pesimista": {"cambios_por_anio": 0.5, "demora_manual": 5, "prob_escape": 0.10, "prob_parada_sin_sis": 0.3,
                  "horas_implementacion": 160, "costo_camara": 600},
    "Base": {},
    "Optimista": {"cambios_por_anio": 4.0, "demora_manual": 14, "prob_escape": 0.20, "prob_parada_sin_sis": 0.7},
}
ANIOS = 3


def calcular(s=None, anios=ANIOS):
    s = {**BASE, **(s or {})}
    costo_defecto = s["costo_desecho"] * (1 - s["prob_escape"]) + s["costo_desecho"] * s["razon_escape"] * s["prob_escape"]
    dias_ganados = max(s["demora_manual"] - DEMORA_SISTEMA, 0)
    defectos_evitados = s["cambios_por_anio"] * s["aumento_tasa"] * s["piezas_dia_linea"] * dias_ganados
    beneficio_a = defectos_evitados * costo_defecto
    beneficio_b = s["atipicos_por_anio"] * s["prob_parada_sin_sis"] * s["horas_parada"] * s["costo_hora_parada"]
    beneficio = beneficio_a + beneficio_b

    inversion = s["horas_implementacion"] * s["costo_hora_tecnico"] + s["costo_camara"] * s["lineas"]
    operacion = (s["servidor_mensual"] * 12 + s["api_llm_anual"] + s["horas_mantencion_mes"] * 12 * s["costo_hora_tecnico"]
                 + FALSAS_POR_ANIO * s["horas_revision_alarma"] * s["costo_hora_analista"])
    neto_anual = beneficio - operacion

    flujo, acum = [], -inversion
    for _ in range(anios):
        acum += neto_anual
        flujo.append(acum)
    costo_total = inversion + operacion * anios
    roi = (beneficio * anios - costo_total) / costo_total
    payback_meses = inversion / neto_anual * 12 if neto_anual > 0 else None
    return {
        "beneficio_a": beneficio_a, "beneficio_b": beneficio_b, "beneficio_anual": beneficio, "defectos_evitados": defectos_evitados,
        "inversion": inversion, "operacion_anual": operacion, "neto_anual": neto_anual, "flujo_acumulado": flujo,
        "costo_total": costo_total, "roi": roi, "payback_meses": payback_meses, "costo_medio_defecto": costo_defecto,
    }


def escenario(nombre):
    return calcular(ESCENARIOS[nombre])


def sensibilidad(variacion=0.3):
    """Cambio del beneficio neto a 3 anios al mover cada supuesto +-30 % (el resto en el caso base)."""
    base = calcular()["flujo_acumulado"][-1]
    filas = []
    for k, v in BASE.items():
        if k in ("lineas", "dias_anio"):
            continue
        abajo = calcular({k: v * (1 - variacion)})["flujo_acumulado"][-1] - base
        arriba = calcular({k: v * (1 + variacion)})["flujo_acumulado"][-1] - base
        if abs(abajo) > 1e-9 or abs(arriba) > 1e-9:
            filas.append({"supuesto": k, "baja": abajo, "sube": arriba, "rango": abs(arriba - abajo)})
    return sorted(filas, key=lambda f: -f["rango"])


def cambios_para_equilibrio(s=None):
    """Cambios de nivel por anio con los que el ROI a 3 anios es cero (incluye la inversion inicial)."""
    s = {**BASE, **(s or {})}
    r0 = calcular({**s, "cambios_por_anio": 0})
    por_cambio = calcular({**s, "cambios_por_anio": 1})["beneficio_a"]
    if por_cambio <= 0:
        return None
    beneficio_necesario = r0["costo_total"] / ANIOS          # beneficio anual que iguala el costo total a 3 anios
    return max((beneficio_necesario - r0["beneficio_b"]) / por_cambio, 0)


if __name__ == "__main__":
    for n in ESCENARIOS:
        r = escenario(n)
        print(f"{n:10s} beneficio/año {r['beneficio_anual']:9,.0f}  operación {r['operacion_anual']:7,.0f}  inversión {r['inversion']:7,.0f}  "
              f"ROI 3 años {r['roi']*100:6.0f} %  recuperación {('%.1f meses' % r['payback_meses']) if r['payback_meses'] else 'no se recupera'}")
    print("equilibrio (cambios de nivel/año, caso base):", round(cambios_para_equilibrio(), 2))
    for f in sensibilidad()[:6]:
        print(f"  {f['supuesto']:22s} {f['baja']:9,.0f}  {f['sube']:9,.0f}")
