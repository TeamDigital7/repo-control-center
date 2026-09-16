"""Reporte Excel del Dashboard de Pedidos, listo para enviar sin retocar.

Hojas: Resumen · Por Tienda · Por Cadena · Por Marca · Por Clasificacion ·
Tipo x Estado · Evolucion · Lineas.

Se exporta lo que hay en pantalla: si el tablero esta filtrado, el libro sale
filtrado igual. Asi lo que se manda es exactamente lo que se miro.
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import xlsxwriter

from . import pedidos

AZUL = "#17269A"
VERDE = "#0B7A3B"
VERDE_BG = "#E7F7EE"
AMBAR_BG = "#FEF3C7"
ROJO_BG = "#FEE2E2"

#: Columnas de la hoja de lineas, en orden de lectura.
COLUMNAS_LINEAS = [
    ("nro_pedido", "Nro Pedido", 14, "txt"),
    ("fecha", "Fecha", 12, "fecha"),
    ("tipo_pedido", "Tipo de Pedido", 22, "txt"),
    ("estado", "Estado", 14, "txt"),
    ("cadena", "Cadena", 12, "txt"),
    ("tienda", "Tienda", 26, "txt"),
    ("ciudad", "Ciudad", 14, "txt"),
    ("marca", "Marca", 18, "txt"),
    ("tipo_prenda", "Tipo Prenda", 18, "txt"),
    ("modcol", "Cod Mod Col", 20, "txt"),
    ("talla", "Talla", 8, "txt"),
    ("pedida", "Cantidad Pedida", 14, "int"),
    ("despachada", "Cantidad Despachada", 16, "int"),
]

#: Tope de filas de la hoja de detalle. Por encima, Excel se vuelve inmanejable
#: y el CSV es el camino correcto; el libro lo dice en la propia hoja.
MAX_LINEAS = 200_000


def _formatos(wb) -> dict:
    base = {"font_name": "Calibri", "font_size": 11}
    return {
        "titulo": wb.add_format({**base, "bold": True, "font_size": 20, "font_color": AZUL}),
        "sub": wb.add_format({**base, "font_color": "#64748B"}),
        "h2": wb.add_format({**base, "bold": True, "font_size": 13, "font_color": "#0B1B46"}),
        "head": wb.add_format({**base, "bold": True, "bg_color": AZUL, "font_color": "#FFFFFF",
                               "align": "center", "valign": "vcenter", "text_wrap": True,
                               "border": 1, "border_color": "#101B70"}),
        "kpi_lbl": wb.add_format({**base, "font_size": 10, "bold": True, "font_color": "#64748B",
                                  "align": "center", "bg_color": "#F6F8FC",
                                  "top": 1, "left": 1, "right": 1, "border_color": "#DDE6F2"}),
        "kpi_val": wb.add_format({**base, "font_size": 20, "bold": True, "font_color": "#0B1B46",
                                  "align": "center", "bg_color": "#F6F8FC",
                                  "num_format": "#,##0",
                                  "bottom": 1, "left": 1, "right": 1, "border_color": "#DDE6F2"}),
        "kpi_pct": wb.add_format({**base, "font_size": 20, "bold": True, "font_color": AZUL,
                                  "align": "center", "bg_color": "#F6F8FC",
                                  "num_format": "0.00%",
                                  "bottom": 1, "left": 1, "right": 1, "border_color": "#DDE6F2"}),
        "txt": wb.add_format(base),
        "int": wb.add_format({**base, "num_format": "#,##0"}),
        "pct": wb.add_format({**base, "num_format": "0.00"}),
        "fecha": wb.add_format({**base, "num_format": "dd/mm/yyyy"}),
        "nota": wb.add_format({**base, "font_size": 10, "font_color": "#475569",
                               "text_wrap": True, "valign": "top"}),
        "alta": wb.add_format({**base, "bg_color": VERDE_BG, "font_color": VERDE,
                               "bold": True, "num_format": "0.00"}),
        "media": wb.add_format({**base, "bg_color": AMBAR_BG, "font_color": "#92400E",
                                "bold": True, "num_format": "0.00"}),
        "baja": wb.add_format({**base, "bg_color": ROJO_BG, "font_color": "#991B1B",
                               "bold": True, "num_format": "0.00"}),
    }


def _cumpl(f: dict, valor: float):
    if valor >= 95:
        return f["alta"]
    return f["media"] if valor >= 85 else f["baja"]


def _tabla(wb, f, tabla: pd.DataFrame, hoja: str, etiqueta: str) -> None:
    """Una dimension por hoja, con el cumplimiento en semaforo."""
    ws = wb.add_worksheet(hoja[:31])
    if tabla is None or tabla.empty:
        ws.write_string(0, 0, "Sin datos para esta vista.", f["nota"])
        return
    ws.freeze_panes(1, 1)
    anchos = [30, 16, 18, 12, 14]
    titulos = [etiqueta] + list(tabla.columns[1:])
    for j, (col, ancho) in enumerate(zip(titulos, anchos)):
        ws.set_column(j, j, ancho)
        ws.write_string(0, j, str(col), f["head"])
    for i, fila in enumerate(tabla.itertuples(index=False), start=1):
        ws.write_string(i, 0, str(fila[0]), f["txt"])
        for j in (1, 2, 3):
            ws.write_number(i, j, float(fila[j]), f["int"])
        ws.write_number(i, 4, float(fila[4]), _cumpl(f, float(fila[4])))
    ws.autofilter(0, 0, len(tabla), len(tabla.columns) - 1)
    total = len(tabla) + 2
    ws.write_string(total, 0, "TOTAL", f["h2"])
    for j in (1, 2, 3):
        ws.write_formula(total, j, f"=SUM({chr(66 + j - 1)}2:{chr(66 + j - 1)}{len(tabla) + 1})",
                         f["int"])


def _resumen(wb, f, df: pd.DataFrame, meta: dict) -> None:
    ws = wb.add_worksheet("Resumen")
    ws.set_column(0, 0, 3)
    ws.set_column(1, 8, 17)
    ws.write_string(1, 1, "Dashboard de Pedidos", f["titulo"])
    ws.write_string(2, 1, meta.get("periodo", ""), f["sub"])

    k = pedidos.kpis(df)
    tarjetas = [
        ("Cantidad Pedida", k["pedida"], "int"),
        ("Cantidad Despachada", k["despachada"], "int"),
        ("Var Pedidos", k["var"], "int"),
        ("% Cumplimiento", k["cumplimiento"] / 100, "pct"),
    ]
    for i, (etiqueta, valor, tipo) in enumerate(tarjetas):
        col = 1 + i * 2
        ws.merge_range(4, col, 4, col + 1, etiqueta, f["kpi_lbl"])
        ws.merge_range(5, col, 5, col + 1, valor,
                       f["kpi_pct"] if tipo == "pct" else f["kpi_val"])

    ws.write_string(7, 1, f"{k['pedidos']:,} pedidos · {len(df):,} lineas".replace(",", " "),
                    f["sub"])
    ws.write_string(9, 1, "Como se calcula", f["h2"])
    ws.merge_range(
        10, 1, 13, 8,
        "Las cifras se calculan sobre el detalle (la linea del pedido, que es la que "
        "trae producto y tienda) y se enriquecen con la cabecera cruzando por numero "
        "de pedido. Var Pedidos = pedida menos despachada. % Cumplimiento = "
        "despachada entre pedida. Si el tablero estaba filtrado, este libro sale "
        "filtrado igual.", f["nota"])
    for i, nota in enumerate(meta.get("notas", [])[:6]):
        ws.write_string(15 + i, 1, str(nota), f["sub"])


def _matriz(wb, f, df: pd.DataFrame) -> None:
    ws = wb.add_worksheet("Tipo x Estado")
    matriz = pedidos.matriz_estado(df)
    if matriz.empty:
        ws.write_string(0, 0, "Sin datos para esta vista.", f["nota"])
        return
    ws.freeze_panes(1, 1)
    ws.set_column(0, 0, 26)
    ws.set_column(1, max(1, len(matriz.columns) - 1), 15)
    for j, col in enumerate(matriz.columns):
        ws.write_string(0, j, str(col), f["head"])
    for i, fila in enumerate(matriz.itertuples(index=False), start=1):
        ws.write_string(i, 0, str(fila[0]), f["txt"])
        for j, valor in enumerate(fila[1:], start=1):
            ws.write_number(i, j, float(valor), f["int"])


def _evolucion(wb, f, df: pd.DataFrame) -> None:
    ws = wb.add_worksheet("Evolucion")
    ws.set_column(0, 0, 14)
    ws.set_column(1, 3, 20)
    fila = 0
    for granularidad in ("Mes", "Semana"):
        serie = pedidos.por_periodo(df, granularidad)
        ws.write_string(fila, 0, f"Por {granularidad.lower()}", f["h2"])
        fila += 1
        if serie.empty:
            ws.write_string(fila, 0, "La cabecera no trajo fecha: no hay serie.", f["nota"])
            fila += 3
            continue
        for j, col in enumerate(serie.columns):
            ws.write_string(fila, j, str(col), f["head"])
        for i, reg in enumerate(serie.itertuples(index=False), start=1):
            ws.write_string(fila + i, 0, str(reg[0]), f["txt"])
            ws.write_number(fila + i, 1, float(reg[1]), f["int"])
            ws.write_number(fila + i, 2, float(reg[2]), f["int"])
        fila += len(serie) + 3


def _lineas(wb, f, df: pd.DataFrame) -> None:
    ws = wb.add_worksheet("Lineas")
    presentes = [(c, t, a, k) for c, t, a, k in COLUMNAS_LINEAS if c in df.columns]
    for j, (_c, titulo, ancho, _k) in enumerate(presentes):
        ws.set_column(j, j, ancho)
        ws.write_string(0, j, titulo, f["head"])
    ws.freeze_panes(1, 0)

    sub = df.head(MAX_LINEAS)
    for i, (_, fila) in enumerate(sub.iterrows(), start=1):
        for j, (col, _t, _a, kind) in enumerate(presentes):
            valor = fila[col]
            if pd.isna(valor):
                ws.write_blank(i, j, None, f["txt"])
            elif kind == "int":
                ws.write_number(i, j, float(valor), f["int"])
            elif kind == "fecha":
                ws.write_datetime(i, j, pd.Timestamp(valor).to_pydatetime(), f["fecha"])
            else:
                ws.write_string(i, j, str(valor), f["txt"])
    if len(sub):
        ws.autofilter(0, 0, len(sub), len(presentes) - 1)
    if len(df) > MAX_LINEAS:
        ws.write_string(len(sub) + 2, 0,
                        f"Se muestran las primeras {MAX_LINEAS:,} de {len(df):,} lineas. "
                        "Para el detalle completo usa la descarga en CSV.".replace(",", " "),
                        f["nota"])


def construir(df: pd.DataFrame, meta: dict | None = None) -> bytes:
    """Libro completo del tablero, con las vistas tal como estan en pantalla."""
    meta = meta or {}
    meta.setdefault("periodo", f"Generado el {datetime.now():%d/%m/%Y %H:%M}")
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "constant_memory": True,
                                   "default_date_format": "dd/mm/yyyy"})
    f = _formatos(wb)
    _resumen(wb, f, df, meta)
    for hoja, dim, etiqueta in (("Por Tienda", "tienda", "Tienda"),
                                ("Por Cadena", "cadena", "Cadena"),
                                ("Por Marca", "marca", "Marca"),
                                ("Por Clasificacion", "tipo_pedido", "Tipo de Pedido")):
        _tabla(wb, f, pedidos.por(df, dim), hoja, etiqueta)
    _matriz(wb, f, df)
    _evolucion(wb, f, df)
    _lineas(wb, f, df)
    wb.close()
    return buf.getvalue()
