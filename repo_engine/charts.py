"""Graficos del dashboard de efectividad.

Usa Altair (que ya viene con Streamlit, sin dependencias nuevas) y SVG en linea
para el medidor. La paleta es la misma del resto de la app.
"""

from __future__ import annotations

import math
from html import escape

import altair as alt
import pandas as pd

AZUL = "#2367FF"
AZUL_OSCURO = "#17269A"
VERDE = "#0B7A3B"
AMBAR = "#B45309"
ROJO = "#B91C1C"
GRIS = "#94A3B8"

ESCALA_SEMAFORO = alt.Scale(
    domain=["Alta", "Media", "Baja", "Sin efectividad", "No evaluable"],
    range=[VERDE, AMBAR, ROJO, "#DC2626", GRIS],
)

_BASE = {"font": "Inter, Segoe UI, system-ui, sans-serif"}


def _tema(chart: alt.Chart, alto: int) -> alt.Chart:
    return (chart.properties(height=alto)
            .configure_view(strokeWidth=0)
            .configure_axis(labelColor="#475569", titleColor="#64748B",
                            labelFontSize=11, titleFontSize=11,
                            grid=True, gridColor="#EEF2F8", domainColor="#E3EAF6",
                            **{"labelFont": _BASE["font"], "titleFont": _BASE["font"]})
            .configure_legend(labelColor="#475569", titleColor="#64748B",
                              labelFontSize=11, titleFontSize=11)
            .configure_title(color="#0B1B46", fontSize=13, anchor="start"))


# ---------------------------------------------------------------------------
# medidor
# ---------------------------------------------------------------------------

def gauge(valor: float, titulo: str = "Efectividad general",
          subtitulo: str = "") -> str:
    """Medidor semicircular en SVG puro."""
    v = max(0.0, min(1.0, float(valor or 0.0)))
    color = VERDE if v >= 0.80 else AMBAR if v >= 0.50 else ROJO
    etiqueta = "Alta" if v >= 0.80 else "Media" if v >= 0.50 else "Baja"

    r, cx, cy = 120, 150, 140
    def punto(frac):
        ang = math.pi * (1 - frac)
        return cx + r * math.cos(ang), cy - r * math.sin(ang)

    x0, y0 = punto(0.0)
    x1, y1 = punto(1.0)
    xv, yv = punto(v)
    largo = 1 if v > 0.5 else 0
    marcas = "".join(
        f'<line x1="{cx + (r-16)*math.cos(math.pi*(1-f)):.1f}" '
        f'y1="{cy - (r-16)*math.sin(math.pi*(1-f)):.1f}" '
        f'x2="{cx + (r-4)*math.cos(math.pi*(1-f)):.1f}" '
        f'y2="{cy - (r-4)*math.sin(math.pi*(1-f)):.1f}" '
        f'stroke="#CBD5E1" stroke-width="2"/>' for f in (0.25, 0.5, 0.75))

    return f"""
    <div class="gauge-card">
      <svg viewBox="0 0 300 190" width="100%" height="auto" role="img"
           aria-label="{escape(titulo)}: {v:.0%}">
        <path d="M {x0:.1f} {y0:.1f} A {r} {r} 0 0 1 {x1:.1f} {y1:.1f}"
              fill="none" stroke="#EEF2F8" stroke-width="22" stroke-linecap="round"/>
        <path d="M {x0:.1f} {y0:.1f} A {r} {r} 0 {largo} 1 {xv:.1f} {yv:.1f}"
              fill="none" stroke="{color}" stroke-width="22" stroke-linecap="round"/>
        {marcas}
        <text x="{cx}" y="{cy - 22}" text-anchor="middle"
              font-size="46" font-weight="900" fill="#0B1B46">{v:.0%}</text>
        <text x="{cx}" y="{cy + 4}" text-anchor="middle"
              font-size="14" font-weight="800" fill="{color}">{etiqueta}</text>
        <text x="30" y="{cy + 26}" text-anchor="middle" font-size="11" fill="#94A3B8">0%</text>
        <text x="270" y="{cy + 26}" text-anchor="middle" font-size="11" fill="#94A3B8">100%</text>
      </svg>
      <div class="gauge-txt"><b>{escape(titulo)}</b><span>{escape(subtitulo)}</span></div>
    </div>
    """


# ---------------------------------------------------------------------------
# barras
# ---------------------------------------------------------------------------

def ranking_tiendas(tabla: pd.DataFrame, top: int = 15, alto: int = 380) -> alt.Chart:
    d = tabla.head(top).copy()
    d["pct"] = d["Efectividad %"]
    return _tema(alt.Chart(d).mark_bar(cornerRadiusEnd=5, height=16).encode(
        x=alt.X("pct:Q", title="Efectividad", axis=alt.Axis(format="%")),
        y=alt.Y("Tienda:N", sort="-x", title=None),
        color=alt.Color("Semaforo:N", scale=ESCALA_SEMAFORO, title="Resultado"),
        tooltip=[alt.Tooltip("Tienda:N"),
                 alt.Tooltip("pct:Q", title="Efectividad", format=".1%"),
                 alt.Tooltip("Unidades traspasadas:Q", title="Traspasadas", format=",.0f"),
                 alt.Tooltip("Unidades atribuibles:Q", title="Atribuibles", format=",.0f"),
                 alt.Tooltip("Unidades ociosas:Q", title="Ociosas", format=",.0f"),
                 alt.Tooltip("Tasa de acierto %:Q", title="Acierto", format=".0%")],
    ), alto)


def ranking_modelos(tabla: pd.DataFrame, alto: int = 380, color: str = VERDE) -> alt.Chart:
    d = tabla.copy()
    d["pct"] = d["Efectividad %"]
    d["etiqueta"] = (d["Modelo"].astype(str).str.slice(0, 26) + " · " +
                     d["Cod Modelo"].astype(str))
    return _tema(alt.Chart(d).mark_bar(cornerRadiusEnd=5, height=16, color=color).encode(
        x=alt.X("pct:Q", title="Efectividad", axis=alt.Axis(format="%")),
        y=alt.Y("etiqueta:N", sort="-x", title=None),
        tooltip=[alt.Tooltip("etiqueta:N", title="Modelo"),
                 alt.Tooltip("pct:Q", title="Efectividad", format=".1%"),
                 alt.Tooltip("Unidades traspasadas:Q", title="Traspasadas", format=",.0f"),
                 alt.Tooltip("Unidades atribuibles:Q", title="Atribuibles", format=",.0f"),
                 alt.Tooltip("Dias a 1a venta:Q", title="Dias a 1a venta", format=".0f")],
    ), alto)


def traspasado_vs_vendido(tabla: pd.DataFrame, top: int = 15, alto: int = 400) -> alt.Chart:
    d = (tabla.sort_values("Unidades traspasadas", ascending=False).head(top)
         [["Tienda", "Unidades traspasadas", "Unidades atribuibles"]]
         .melt("Tienda", var_name="Concepto", value_name="Unidades"))
    return _tema(alt.Chart(d).mark_bar(cornerRadiusEnd=3).encode(
        y=alt.Y("Tienda:N", sort="-x", title=None),
        x=alt.X("Unidades:Q", title="Unidades"),
        yOffset=alt.YOffset("Concepto:N"),
        color=alt.Color("Concepto:N", title=None,
                        scale=alt.Scale(domain=["Unidades traspasadas", "Unidades atribuibles"],
                                        range=[GRIS, AZUL])),
        tooltip=["Tienda:N", "Concepto:N", alt.Tooltip("Unidades:Q", format=",.0f")],
    ), alto)


def evolucion(tabla: pd.DataFrame, alto: int = 300) -> alt.Chart:
    if tabla.empty:
        return _tema(alt.Chart(pd.DataFrame({"x": [], "y": []})).mark_line(), alto)
    base = alt.Chart(tabla)
    area = base.mark_area(opacity=0.18, color=AZUL, interpolate="monotone").encode(
        x=alt.X("Semana:T", title="Semana de la primera venta"),
        y=alt.Y("Unidades atribuibles:Q", title="Unidades atribuibles"))
    linea = base.mark_line(color=AZUL, strokeWidth=2.5, interpolate="monotone",
                           point=alt.OverlayMarkDef(color=AZUL, size=45)).encode(
        x="Semana:T", y="Unidades atribuibles:Q",
        tooltip=[alt.Tooltip("Semana:T", format="%d/%m/%Y"),
                 alt.Tooltip("Unidades atribuibles:Q", format=",.0f"),
                 alt.Tooltip("Traspasos:Q", format=",.0f")])
    return _tema(area + linea, alto)


def efectividad_temporal(kpis: dict, cortes=(7, 14, 30), alto: int = 260) -> alt.Chart:
    filas = [{"Corte": f"{d} dias", "Efectividad": kpis.get(f"efectividad_{d}d", 0.0)}
             for d in cortes]
    filas.append({"Corte": "Final", "Efectividad": kpis.get("efectividad", 0.0)})
    d = pd.DataFrame(filas)
    barras = alt.Chart(d).mark_bar(cornerRadiusEnd=6, size=52).encode(
        x=alt.X("Corte:N", sort=None, title=None),
        y=alt.Y("Efectividad:Q", axis=alt.Axis(format="%"), title=None),
        color=alt.value(AZUL),
        tooltip=[alt.Tooltip("Corte:N"), alt.Tooltip("Efectividad:Q", format=".1%")])
    texto = alt.Chart(d).mark_text(dy=-9, fontWeight="bold", color="#0B1B46").encode(
        x=alt.X("Corte:N", sort=None), y="Efectividad:Q",
        text=alt.Text("Efectividad:Q", format=".0%"))
    return _tema(barras + texto, alto)


def semaforo_donut(detalle: pd.DataFrame, alto: int = 260) -> alt.Chart:
    d = (detalle[detalle["evaluable"]]["semaforo"].value_counts()
         .rename_axis("Resultado").reset_index(name="Traspasos"))
    return _tema(alt.Chart(d).mark_arc(innerRadius=62, cornerRadius=4).encode(
        theta=alt.Theta("Traspasos:Q", stack=True),
        color=alt.Color("Resultado:N", scale=ESCALA_SEMAFORO, title=None),
        tooltip=["Resultado:N", alt.Tooltip("Traspasos:Q", format=",.0f")],
    ), alto)


def dispersion_tiendas(tabla: pd.DataFrame, alto: int = 340) -> alt.Chart:
    """Volumen contra efectividad: donde duele mas un mal traspaso."""
    d = tabla.copy()
    d["pct"] = d["Efectividad %"]
    return _tema(alt.Chart(d).mark_circle(opacity=0.75).encode(
        x=alt.X("Unidades traspasadas:Q", title="Unidades traspasadas",
                scale=alt.Scale(type="sqrt")),
        y=alt.Y("pct:Q", title="Efectividad", axis=alt.Axis(format="%")),
        size=alt.Size("Unidades ociosas:Q", title="Ociosas",
                      scale=alt.Scale(range=[40, 900])),
        color=alt.Color("Semaforo:N", scale=ESCALA_SEMAFORO, title="Resultado"),
        tooltip=["Tienda:N", alt.Tooltip("pct:Q", title="Efectividad", format=".1%"),
                 alt.Tooltip("Unidades traspasadas:Q", format=",.0f"),
                 alt.Tooltip("Unidades ociosas:Q", format=",.0f")],
    ), alto)


def histograma_dias(detalle: pd.DataFrame, alto: int = 260, paso: int = 5,
                    tope: int = 90) -> alt.Chart:
    """Los tramos se calculan en pandas: Altair no admite mas de 5.000 filas."""
    serie = detalle.loc[detalle["evaluable"] & detalle["dias_primera_venta"].notna(),
                        "dias_primera_venta"]
    serie = serie[serie <= tope]
    if serie.empty:
        return _tema(alt.Chart(pd.DataFrame({"Tramo": [], "Traspasos": []})).mark_bar(), alto)
    bins = list(range(0, tope + paso, paso))
    tramos = pd.cut(serie, bins=bins, right=True, include_lowest=True)
    d = (tramos.value_counts().sort_index().rename_axis("_t").reset_index(name="Traspasos"))
    d["Desde"] = [int(i.left) if i.left >= 0 else 0 for i in d["_t"]]
    d["Tramo"] = [f"{max(int(i.left), 0)}-{int(i.right)}" for i in d["_t"]]
    d = d.drop(columns=["_t"])
    return _tema(alt.Chart(d).mark_bar(color=AZUL, cornerRadiusEnd=3).encode(
        x=alt.X("Tramo:N", sort=alt.SortField("Desde"), title="Dias hasta la primera venta"),
        y=alt.Y("Traspasos:Q", title="Traspasos"),
        tooltip=[alt.Tooltip("Tramo:N", title="Dias"),
                 alt.Tooltip("Traspasos:Q", format=",.0f")],
    ), alto)


# ---------------------------------------------------------------------------
# pedidos
# ---------------------------------------------------------------------------

def _largo(tabla: pd.DataFrame, dim: str) -> pd.DataFrame:
    """Pedida / despachada en formato largo, que es lo que come Altair."""
    return tabla.melt(id_vars=[dim],
                      value_vars=["Cantidad Pedida", "Cantidad Despachada"],
                      var_name="Medida", value_name="Unidades")


ESCALA_PEDIDOS = alt.Scale(domain=["Cantidad Pedida", "Cantidad Despachada"],
                           range=[AZUL, VERDE])


def pedidos_barras(tabla: pd.DataFrame, dim: str, titulo: str = "",
                   top: int = 12, alto: int = 320) -> alt.Chart:
    """Pedida vs despachada por dimension, barras agrupadas horizontales."""
    sub = tabla.head(top)
    orden = list(sub[dim])
    ch = (alt.Chart(_largo(sub, dim))
          .mark_bar(cornerRadius=2)
          .encode(
              y=alt.Y(f"{dim}:N", sort=orden, title=None),
              x=alt.X("Unidades:Q", title=None, axis=alt.Axis(format="~s")),
              yOffset=alt.YOffset("Medida:N"),
              color=alt.Color("Medida:N", scale=ESCALA_PEDIDOS, title=None),
              tooltip=[alt.Tooltip(f"{dim}:N"), "Medida:N",
                       alt.Tooltip("Unidades:Q", format=",.0f")])
          .properties(title=titulo))
    return _tema(ch, alto)


def pedidos_columnas(tabla: pd.DataFrame, dim: str, titulo: str = "",
                     alto: int = 260) -> alt.Chart:
    """La misma comparacion en vertical, para cadenas y periodos."""
    orden = list(tabla[dim])
    ch = (alt.Chart(_largo(tabla, dim))
          .mark_bar(cornerRadius=2)
          .encode(
              x=alt.X(f"{dim}:N", sort=orden, title=None,
                      axis=alt.Axis(labelAngle=0, labelLimit=90)),
              y=alt.Y("Unidades:Q", title=None, axis=alt.Axis(format="~s")),
              xOffset=alt.XOffset("Medida:N"),
              color=alt.Color("Medida:N", scale=ESCALA_PEDIDOS, title=None),
              tooltip=[alt.Tooltip(f"{dim}:N"), "Medida:N",
                       alt.Tooltip("Unidades:Q", format=",.0f")])
          .properties(title=titulo))
    return _tema(ch, alto)


def pedidos_evolucion(tabla: pd.DataFrame, titulo: str = "", alto: int = 280) -> alt.Chart:
    """Serie de pedida vs despachada en el tiempo (area suave, como el BI)."""
    ch = (alt.Chart(_largo(tabla, "periodo"))
          .mark_area(opacity=0.35, line={"strokeWidth": 2})
          .encode(
              x=alt.X("periodo:N", title=None, axis=alt.Axis(labelAngle=0)),
              y=alt.Y("Unidades:Q", stack=None, title=None,
                      axis=alt.Axis(format="~s")),
              color=alt.Color("Medida:N", scale=ESCALA_PEDIDOS, title=None),
              tooltip=["periodo:N", "Medida:N",
                       alt.Tooltip("Unidades:Q", format=",.0f")])
          .properties(title=titulo))
    return _tema(ch, alto)


def cumplimiento_barras(tabla: pd.DataFrame, dim: str, titulo: str = "",
                        top: int = 12, alto: int = 320) -> alt.Chart:
    """% de cumplimiento por dimension, con el color contando la historia."""
    sub = tabla.head(top).copy()
    # El umbral se resuelve en pandas: anidar alt.condition no es valido en Vega.
    sub["Nivel"] = pd.cut(sub["%Cumplimiento"], [-0.01, 85, 95, 100.01],
                          labels=["Bajo", "Medio", "Alto"])
    escala = alt.Scale(domain=["Alto", "Medio", "Bajo"], range=[VERDE, AMBAR, ROJO])
    ch = (alt.Chart(sub)
          .mark_bar(cornerRadius=2)
          .encode(
              y=alt.Y(f"{dim}:N", sort=list(sub[dim]), title=None),
              x=alt.X("%Cumplimiento:Q", title=None,
                      scale=alt.Scale(domain=[0, 100])),
              color=alt.Color("Nivel:N", scale=escala, title=None,
                              legend=alt.Legend(orient="bottom")),
              tooltip=[alt.Tooltip(f"{dim}:N"),
                       alt.Tooltip("%Cumplimiento:Q", format=".2f"),
                       alt.Tooltip("Cantidad Pedida:Q", format=",.0f"),
                       alt.Tooltip("Cantidad Despachada:Q", format=",.0f")])
          .properties(title=titulo))
    return _tema(ch, alto)
