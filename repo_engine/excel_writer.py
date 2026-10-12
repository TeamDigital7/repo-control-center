"""Exporta la Tabla de Repo Final como **libro vivo**, no como volcado de datos.

Replica la plantilla `.xlsb` celda por celda:

* hoja `REPO` con las mismas formulas, sombreados, anchos, alturas, paneles
  inmovilizados, autofiltro y zoom;
* hojas de apoyo (`CD`, `TIENDAS2`, `LLAVES`, `TIENDAS`) para que los BUSCARV
  sigan resolviendo;
* rangos con nombre `TIENDA`, `TRSPINV26`, `CD`, `ORDEN`, `ABREV`;
* hojas nuevas `CUADRE` y `EN CAMINO` para auditar el resultado.

Formulas replicadas de la plantilla original:

    fila 1      =SUBTOTAL(9,T5:T29373)                      totales que respetan el filtro
    fila 2      =VLOOKUP(T3,TIENDA,2,0)                     codigo de tienda
    K (SKU)     =VLOOKUP(G5&"-"&H5&"-"&I5,CD!A:X,19,0)
    L (TRASP.)  =IFERROR(VLOOKUP($G5&"-"&$H5,TRSPINV26,2,0),"-")
    M (REPOS.)  =V5+Y5+AB5+...                              suma de las 69 columnas REP
    N (NVO DSP) =S5+P5-M5                                   DSP + RT - lo ya repuesto
    O..S        =IFERROR(VLOOKUP(...,CD!A:X,18|20|21|22|23,0),0)
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
import xlsxwriter

from . import config as C
from .catalogs import Catalogs

TEXT_COLUMNS = {"Marca", "Clase", "Genero", "Tipo Prenda", "Modelo", "Color",
                "Cod Modelo", "Cod Color", "Talla/Numero", "Temporada Comercial"}

#: Columnas del REPO que son formula viva (no se escriben como valor).
FORMULA_COLUMNS = ["SKU", "TRASPASOS DE TEMPORADA", "REPOSICIÓN", "NVO DSP CD",
                   "ECOM", "RT", "WS", "MM", "DSP"]


def colname(n: int) -> str:
    """1 -> A, 27 -> AA, 226 -> HR."""
    out = ""
    while n:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def _store_col(store_idx: int, metric_idx: int) -> int:
    """Indice 1-based de la columna: bloque de 3 por tienda a partir de la 20."""
    return len(C.FIXED_COLUMNS) + 1 + store_idx * 3 + metric_idx


# ---------------------------------------------------------------------------

def write_workbook(repo: pd.DataFrame,
                   catalogs: Catalogs,
                   *,
                   cd: pd.DataFrame | None = None,
                   cuadre=None,
                   en_camino: pd.DataFrame | None = None,
                   data: pd.DataFrame | None = None,
                   sku_dir: dict[str, str] | None = None,
                   meta: dict | None = None,
                   incluir_data: bool = False,
                   alerta_negativo: bool = True) -> bytes:
    meta = meta or {}
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True, "constant_memory": True})
    wb.set_calc_mode("auto")

    fmts = _formats(wb)
    _write_repo(wb, fmts, repo, catalogs, alerta_negativo)
    _write_cd(wb, fmts, cd)
    _write_skus(wb, fmts, sku_dir)
    _write_tiendas2(wb, fmts, catalogs)
    _write_llaves(wb, fmts, catalogs)
    _write_tiendas(wb, fmts, catalogs)
    _write_en_camino(wb, fmts, en_camino, catalogs)
    _write_cuadre(wb, fmts, cuadre, meta)
    if incluir_data and data is not None:
        _write_data(wb, fmts, data)

    for name, ref in C.NAMED_RANGES.items():
        wb.define_name(name, ref)

    wb.close()
    return buf.getvalue()


# ---------------------------------------------------------------------------

def _formats(wb) -> dict:
    base = {"font_name": C.FONT_NAME, "font_size": C.FONT_SIZE}
    f = {}
    f["plain"] = wb.add_format(base)
    f["txt"] = wb.add_format({**base, "align": "center"})
    f["txt_left"] = wb.add_format({**base, "align": "left"})
    f["num"] = wb.add_format({**base, "align": "center"})

    # encabezados (fila 4)
    f["head"] = wb.add_format({**base, "align": "center", "valign": "vcenter"})
    f["head_trasp"] = wb.add_format({**base, "align": "center", "valign": "vcenter",
                                     "bold": True, "bg_color": C.COLOR_TRASPASO,
                                     "text_wrap": True, "rotation": 90})
    f["head_calc"] = wb.add_format({**base, "align": "center", "valign": "vcenter",
                                    "bold": True, "bg_color": C.COLOR_CALC,
                                    "font_color": C.COLOR_REP_FONT})
    f["head_rep"] = wb.add_format({**base, "align": "center", "valign": "vcenter",
                                   "bold": True, "bg_color": C.COLOR_REP,
                                   "font_color": C.COLOR_REP_FONT})

    # fila 1 totales / fila 2 codigo / fila 3 abreviatura
    f["total"] = wb.add_format({**base, "align": "center", "valign": "vcenter"})
    f["total_calc"] = wb.add_format({**base, "align": "center", "valign": "vcenter",
                                     "bold": True, "bg_color": C.COLOR_CALC_TOP,
                                     "font_color": C.COLOR_REP_FONT})
    # La fila 2 va en rojo y negrita sobre durazno en toda la banda de tiendas.
    f["cod"] = wb.add_format({**base, "align": "center", "valign": "vcenter",
                              "bold": True, "bg_color": C.COLOR_REP,
                              "font_color": C.COLOR_REP_FONT})
    f["cod_calc"] = wb.add_format({**base, "align": "center", "valign": "vcenter",
                                   "bold": True, "bg_color": C.COLOR_CALC_TOP,
                                   "font_color": C.COLOR_REP_FONT})
    f["abrev"] = wb.add_format({**base, "align": "center", "valign": "vcenter",
                                "text_wrap": True})
    f["abrev_rep"] = wb.add_format({**base, "align": "center", "valign": "vcenter",
                                    "text_wrap": True, "bold": True,
                                    "bg_color": C.COLOR_REP,
                                    "font_color": C.COLOR_REP_FONT})
    f["abrev_calc"] = wb.add_format({**base, "align": "center", "valign": "vcenter",
                                     "text_wrap": True, "bold": True,
                                     "bg_color": C.COLOR_CALC_TOP,
                                     "font_color": C.COLOR_REP_FONT})

    # columnas de datos
    f["col_rep"] = wb.add_format({**base, "align": "center", "bold": True,
                                  "bg_color": C.COLOR_REP,
                                  "font_color": C.COLOR_REP_FONT})
    f["col_calc"] = wb.add_format({**base, "align": "center", "bold": True,
                                   "bg_color": C.COLOR_CALC,
                                   "font_color": C.COLOR_REP_FONT})
    f["col_store"] = wb.add_format({**base, "align": "center"})
    f["na"] = wb.add_format({**base, "align": "center", "font_color": "#B91C1C"})

    # hojas de apoyo
    f["sheet_head"] = wb.add_format({**base, "bold": True, "bg_color": "#17269A",
                                     "font_color": "#FFFFFF", "align": "center",
                                     "valign": "vcenter", "text_wrap": True})
    f["title"] = wb.add_format({**base, "bold": True, "font_size": 15,
                                "font_color": "#0B1B46"})
    f["key"] = wb.add_format({**base, "bold": True, "font_color": "#334155"})
    f["val_num"] = wb.add_format({**base, "num_format": "#,##0"})
    f["ok"] = wb.add_format({**base, "bold": True, "bg_color": "#E7F7EE",
                             "font_color": "#0B7A3B", "align": "center"})
    f["bad"] = wb.add_format({**base, "bold": True, "bg_color": "#FEE2E2",
                              "font_color": "#B91C1C", "align": "center"})
    return f


# ---------------------------------------------------------------------------
# hoja REPO
# ---------------------------------------------------------------------------

def _formula_simple(formula: str, expand_future_functions: bool = False) -> str:
    """Lo mismo que hace xlsxwriter, sin su revision de funciones nuevas.

    xlsxwriter pasa cada formula por ~30 expresiones regulares buscando
    funciones de Excel 365 (FILTER, XLOOKUP...). Las de esta hoja son solo
    BUSCARV, SI.ERROR, SUBTOTALES y sumas, y con ~300 000 formulas esa revision
    era casi la mitad del tiempo de generar el libro.
    """
    if formula.startswith("{"):
        formula = formula[1:]
    if formula.startswith("="):
        formula = formula[1:]
    if formula.endswith("}"):
        formula = formula[:-1]
    return formula


def _write_repo(wb, f, repo: pd.DataFrame, catalogs: Catalogs, alerta_negativo: bool) -> None:
    ws = wb.add_worksheet(C.SHEET_NAME)
    ws._prepare_formula = _formula_simple
    n_fixed = len(C.FIXED_COLUMNS)
    n_rows = len(repo)
    first, last = C.ROW_FIRST_DATA, C.ROW_FIRST_DATA + n_rows - 1
    n_cols = n_fixed + len(catalogs.tiendas) * 3

    idx = {name: i + 1 for i, name in enumerate(C.FIXED_COLUMNS)}
    L = {name: colname(i) for name, i in idx.items()}

    # ---- anchos y formato de columna (los blancos tambien quedan sombreados)
    for name, i in idx.items():
        width = C.COLUMN_WIDTHS.get(name, 10)
        fmt = f["col_calc"] if name in ("REPOSICIÓN", "NVO DSP CD") else None
        ws.set_column(i - 1, i - 1, width, fmt)
    for s in range(len(catalogs.tiendas)):
        for m in range(3):
            col = _store_col(s, m) - 1
            ws.set_column(col, col, C.STORE_COLUMN_WIDTH,
                          f["col_rep"] if m == 2 else f["col_store"])

    for r, h in C.ROW_HEIGHTS.items():
        ws.set_row(r - 1, h)
    ws.freeze_panes(C.ROW_HEADER, n_fixed)       # SplitRow=4, SplitColumn=19
    ws.autofilter(C.ROW_HEADER - 1, 0, last, n_cols - 1)
    ws.set_zoom(C.ZOOM)

    # ---- fila 1: SUBTOTAL por columna de tienda
    for s in range(len(catalogs.tiendas)):
        for m in range(3):
            c = _store_col(s, m)
            letra = colname(c)
            col_name = f"{catalogs.tiendas[s].abrev}|{C.STORE_METRICS[m]}"
            serie = repo.get(col_name)
            cached = float(np.nansum(serie.to_numpy(dtype=float))) if serie is not None else 0.0
            ws.write_formula(0, c - 1, f"=SUBTOTAL(9,{letra}{first}:{letra}{last})",
                             f["total"], cached)
    # Agregado nuestro: totales de lo repuesto y del disponible que queda.
    # Respetan el autofiltro, asi que sirven de tablero mientras se llena la repo.
    for name in ("REPOSICIÓN", "NVO DSP CD"):
        letra = L[name]
        ws.write_formula(0, idx[name] - 1,
                         f"=SUBTOTAL(9,{letra}{first}:{letra}{last})",
                         f["total_calc"], 0)

    # ---- fila 2: codigo de tienda por BUSCARV sobre la fila 3
    for s, tienda in enumerate(catalogs.tiendas):
        for m in range(3):
            c = _store_col(s, m)
            letra = colname(c)
            ws.write_formula(1, c - 1, f"=VLOOKUP({letra}3,TIENDA,2,0)", f["cod"], tienda.cod)
    for name in ("REPOSICIÓN", "NVO DSP CD"):
        ws.write_blank(1, idx[name] - 1, None, f["cod_calc"])

    # ---- fila 3: abreviatura (valor, repetida en las 3 columnas del bloque)
    for s, tienda in enumerate(catalogs.tiendas):
        for m in range(3):
            c = _store_col(s, m)
            ws.write_string(2, c - 1, tienda.abrev,
                            f["abrev_rep"] if m == 2 else f["abrev"])
    for name in ("REPOSICIÓN", "NVO DSP CD"):
        ws.write_blank(2, idx[name] - 1, None, f["abrev_calc"])

    # ---- fila 4: encabezados
    for name, i in idx.items():
        if name == "TRASPASOS DE TEMPORADA":
            fmt = f["head_trasp"]
        elif name in ("REPOSICIÓN", "NVO DSP CD"):
            fmt = f["head_calc"]
        else:
            fmt = f["head"]
        ws.write_string(C.ROW_HEADER - 1, i - 1, name, fmt)
    for s in range(len(catalogs.tiendas)):
        for m, metric in enumerate(C.STORE_METRICS):
            ws.write_string(C.ROW_HEADER - 1, _store_col(s, m) - 1, metric,
                            f["head_rep"] if m == 2 else f["head"])

    # ---- datos
    rep_letters = [colname(_store_col(s, 2)) for s in range(len(catalogs.tiendas))]
    values = {c: repo[c].to_numpy() for c in repo.columns if c != "LLAVE"}
    store_cols = [(s, m, f"{t.abrev}|{C.STORE_METRICS[m]}")
                  for s, t in enumerate(catalogs.tiendas) for m in range(3)]

    for i in range(n_rows):
        row0 = C.ROW_FIRST_DATA - 1 + i
        r = row0 + 1                                   # fila de Excel (1-based)

        for name in C.GROUP_COLUMNS:
            v = values[name][i]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                continue
            ws.write_string(row0, idx[name] - 1, str(v), f["txt"])

        llave_ref = f'{L["Cod Modelo"]}{r}&"-"&{L["Cod Color"]}{r}&"-"&{L["Talla/Numero"]}{r}'
        modcol_ref = f'${L["Cod Modelo"]}{r}&"-"&${L["Cod Color"]}{r}'

        # SKU: primero el CD del dia; si no esta, el directorio acumulado.
        # Si tampoco, queda #N/A a la vista, igual que la plantilla.
        sku = values["SKU"][i]
        ws.write_formula(
            row0, idx["SKU"] - 1,
            f"=IFERROR(VLOOKUP({llave_ref},CD!$A:$X,{C.CD_COL_INDEX['SKU']},0),"
            f"IFERROR(VLOOKUP({llave_ref},SKUS,2,0),NA()))",
            f["na"] if sku == C.NA_TOKEN else f["txt"],
            C.NA_TOKEN if sku == C.NA_TOKEN else str(sku))

        # TRASPASOS DE TEMPORADA
        ws.write_formula(row0, idx["TRASPASOS DE TEMPORADA"] - 1,
                         f'=IFERROR(VLOOKUP({modcol_ref},TRSPINV26,2,0),"-")',
                         f["txt"], str(values["TRASPASOS DE TEMPORADA"][i]))

        # REPOSICIÓN = suma de las 69 columnas REP
        ws.write_formula(row0, idx["REPOSICIÓN"] - 1,
                         "=" + "+".join(f"{c}{r}" for c in rep_letters),
                         f["col_calc"], 0)

        # NVO DSP CD = DSP + RT - REPOSICIÓN
        dsp = _num(values["DSP"][i])
        rt = _num(values["RT"][i])
        ws.write_formula(row0, idx["NVO DSP CD"] - 1,
                         f'={L["DSP"]}{r}+{L["RT"]}{r}-{L["REPOSICIÓN"]}{r}',
                         f["col_calc"], dsp + rt)

        # ECOM / RT / WS / MM / DSP contra la hoja CD
        for name in ("ECOM", "RT", "WS", "MM", "DSP"):
            ws.write_formula(
                row0, idx[name] - 1,
                f"=IFERROR(VLOOKUP({llave_ref},CD!$A:$X,{C.CD_COL_INDEX[name]},0),0)",
                f["num"], _num(values[name][i]))

        # bloques por tienda (REP se deja en blanco: es la columna de captura)
        for s, m, col_name in store_cols:
            if m == 2:
                v = values.get(col_name)
                v = v[i] if v is not None else None
                if v is None or (isinstance(v, float) and np.isnan(v)) or v == 0:
                    continue
                ws.write_number(row0, _store_col(s, m) - 1, float(v), f["col_rep"])
                continue
            v = values[col_name][i]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                continue
            ws.write_number(row0, _store_col(s, m) - 1, float(v), f["col_store"])

    # ---- aviso (agregado, no esta en la plantilla): disponible negativo
    if alerta_negativo and n_rows:
        ws.conditional_format(
            first - 1, idx["NVO DSP CD"] - 1, last, idx["NVO DSP CD"] - 1,
            {"type": "cell", "criteria": "<", "value": 0,
             "format": wb.add_format({"bg_color": C.COLOR_ALERTA,
                                      "font_color": C.COLOR_ALERTA_FONT,
                                      "bold": True, "font_name": C.FONT_NAME,
                                      "font_size": C.FONT_SIZE, "align": "center"})})


def _num(v) -> float:
    try:
        x = float(v)
        return 0.0 if np.isnan(x) else x
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# hojas de apoyo
# ---------------------------------------------------------------------------

def _write_cd(wb, f, cd: pd.DataFrame | None) -> None:
    ws = wb.add_worksheet("CD")
    cols = C.CD_SHEET_COLUMNS
    ws.set_column(0, 0, 26)
    ws.set_column(1, len(cols) - 1, 13)
    ws.set_row(0, 30)
    for j, name in enumerate(cols):
        ws.write_string(0, j, C.CD_SHEET_HEADER_ALIAS.get(name, name), f["sheet_head"])
    if cd is None or cd.empty:
        return

    src = {name: (cd[name].to_numpy() if name in cd.columns else None) for name in cols}
    llaves = cd["LLAVE"].to_numpy() if "LLAVE" in cd.columns else None
    for i in range(len(cd)):
        r = i + 2
        # A = Cod. Modelo & "-" & Cod. Color & "-" & Talla   (igual que la plantilla)
        ws.write_formula(i + 1, 0, f'=H{r}&"-"&J{r}&"-"&L{r}', f["plain"],
                         str(llaves[i]) if llaves is not None else "")
        for j, name in enumerate(cols[1:], start=1):
            arr = src[name]
            if arr is None:
                continue
            v = arr[i]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                continue
            if isinstance(v, (int, float, np.integer, np.floating)):
                ws.write_number(i + 1, j, float(v), f["plain"])
            else:
                ws.write_string(i + 1, j, str(v), f["plain"])


def _write_skus(wb, f, sku_dir: dict[str, str] | None) -> None:
    """Directorio acumulado LLAVE -> ID Producto; respalda la columna K del REPO."""
    ws = wb.add_worksheet("SKUS")
    ws.set_column(0, 0, 28)
    ws.set_column(1, 1, 14)
    ws.write_string(0, 0, "LLAVE", f["sheet_head"])
    ws.write_string(0, 1, "ID Producto", f["sheet_head"])
    if not sku_dir:
        return
    for i, (llave, valor) in enumerate(sorted(sku_dir.items()), start=1):
        ws.write_string(i, 0, str(llave), f["plain"])
        ws.write_string(i, 1, str(valor), f["plain"])
    ws.autofilter(0, 0, len(sku_dir), 1)
    ws.freeze_panes(1, 0)


def _write_tiendas2(wb, f, catalogs: Catalogs) -> None:
    """D:E es el rango con nombre TIENDA que usa la fila 2 del REPO."""
    ws = wb.add_worksheet("TIENDAS2")
    ws.set_column(0, 0, 14)
    ws.set_column(1, 1, 28)
    ws.set_column(2, 4, 12)
    for j, name in enumerate(["CADENA", "NOMBRE TIENDA", "ORDEN", "ABREV", "COD TI"]):
        ws.write_string(0, j, name, f["sheet_head"])
    for i, t in enumerate(catalogs.tiendas, start=1):
        cadena = t.abrev.split(" ")[0]
        ws.write_string(i, 0, cadena, f["plain"])
        ws.write_string(i, 1, t.nombre or t.abrev, f["plain"])
        ws.write_string(i, 2, t.cod, f["plain"])
        ws.write_string(i, 3, t.abrev, f["plain"])
        ws.write_string(i, 4, t.cod, f["plain"])


def _write_llaves(wb, f, catalogs: Catalogs) -> None:
    """Q:R es el rango con nombre TRSPINV26 que usa la columna L del REPO."""
    ws = wb.add_worksheet("LLAVES")
    ws.set_column(16, 16, 26)
    ws.set_column(17, 17, 18)
    ws.write_string(0, 16, "llave", f["sheet_head"])
    ws.write_string(0, 17, "Traspaso a INV26", f["sheet_head"])
    for i, clave in enumerate(sorted(catalogs.traspasos), start=1):
        ws.write_string(i, 16, clave, f["plain"])
        ws.write_string(i, 17, "T", f["plain"])


def _write_tiendas(wb, f, catalogs: Catalogs) -> None:
    ws = wb.add_worksheet("TIENDAS")
    headers = ["COD TDA", "ABREV", "NOMBRE TIENDA", "CADENA", "COLUMNA VNT",
               "COLUMNA STK", "COLUMNA REP"]
    widths = [10, 14, 30, 12, 13, 13, 13]
    for j, (name, w) in enumerate(zip(headers, widths)):
        ws.set_column(j, j, w)
        ws.write_string(0, j, name, f["sheet_head"])
    for i, t in enumerate(catalogs.tiendas):
        ws.write_string(i + 1, 0, t.cod, f["plain"])
        ws.write_string(i + 1, 1, t.abrev, f["plain"])
        ws.write_string(i + 1, 2, t.nombre, f["plain"])
        ws.write_string(i + 1, 3, t.abrev.split(" ")[0], f["plain"])
        for m in range(3):
            ws.write_string(i + 1, 4 + m, colname(_store_col(i, m)), f["plain"])
    ws.autofilter(0, 0, len(catalogs.tiendas), len(headers) - 1)
    ws.freeze_panes(1, 0)


def _write_en_camino(wb, f, en_camino: pd.DataFrame | None, catalogs: Catalogs) -> None:
    """Pedidos que salieron del CD y todavia no llegan, por SKU y tienda."""
    ws = wb.add_worksheet("EN CAMINO")
    headers = ["LLAVE", "Cod Modelo", "Cod Color", "Talla", "Cod Tienda", "Tienda",
               "Unidades en camino"]
    widths = [26, 20, 11, 10, 11, 14, 18]
    for j, (name, w) in enumerate(zip(headers, widths)):
        ws.set_column(j, j, w)
        ws.write_string(0, j, name, f["sheet_head"])
    if en_camino is None or en_camino.empty:
        ws.write_string(1, 0, "Sin pedidos pendientes de recepcion en el periodo.", f["plain"])
        return
    by_key = catalogs.by_key
    arr = en_camino.to_dict("records")
    for i, row in enumerate(arr, start=1):
        llave = str(row.get("LLAVE", ""))
        partes = llave.split("-")
        tienda = by_key.get(str(row.get("_tienda_key", "")))
        ws.write_string(i, 0, llave, f["plain"])
        ws.write_string(i, 1, "-".join(partes[:-2]) if len(partes) > 2 else "", f["plain"])
        ws.write_string(i, 2, partes[-2] if len(partes) > 1 else "", f["plain"])
        ws.write_string(i, 3, partes[-1] if partes else "", f["plain"])
        ws.write_string(i, 4, tienda.cod if tienda else str(row.get("_tienda_key", "")), f["plain"])
        ws.write_string(i, 5, tienda.abrev if tienda else "", f["plain"])
        ws.write_number(i, 6, float(row.get("REP", 0)), f["val_num"])
    ws.autofilter(0, 0, len(arr), len(headers) - 1)
    ws.freeze_panes(1, 0)


def _write_cuadre(wb, f, cuadre, meta: dict) -> None:
    ws = wb.add_worksheet("CUADRE")
    ws.set_column(0, 0, 30)
    ws.set_column(1, 4, 20)
    ws.set_column(5, 5, 10)
    ws.set_column(6, 6, 70)
    ws.write_string(0, 0, "Cuadre de la Tabla de Repo", f["title"])

    r = 2
    resumen = [
        ("Generado", meta.get("generado", "")),
        ("Filas (SKU)", meta.get("filas", 0)),
        ("Tiendas", meta.get("tiendas", 0)),
        ("Modo de la columna REP", C.REP_MODES.get(meta.get("rep_mode", ""), {}).get("label", "")),
    ]
    for k, v in resumen:
        ws.write_string(r, 0, k, f["key"])
        if isinstance(v, (int, float)):
            ws.write_number(r, 1, float(v), f["val_num"])
        else:
            ws.write_string(r, 1, str(v), f["plain"])
        r += 1

    if cuadre is None:
        return

    r += 1
    ws.write_string(r, 0, "Identidad: archivo = REPO + excluido por regla + sin explicar", f["key"])
    r += 1
    df = cuadre.to_frame()
    for j, name in enumerate(df.columns):
        ws.write_string(r, j, name, f["sheet_head"])
    r += 1
    for _, row in df.iterrows():
        ws.write_string(r, 0, str(row["Concepto"]), f["plain"])
        for j, name in enumerate(["Unidades en el archivo", "Unidades en el REPO",
                                  "Excluidas por regla", "Sin explicar"], start=1):
            ws.write_number(r, j, float(row[name]), f["val_num"])
        ws.write_string(r, 5, str(row["Cuadra"]), f["ok"] if row["Cuadra"] == "SI" else f["bad"])
        ws.write_string(r, 6, str(row["Detalle"]), f["plain"])
        r += 1

    des = cuadre.desglose_frame()
    if not des.empty:
        r += 2
        ws.write_string(r, 0, "Cobertura de los cruces", f["key"])
        r += 1
        for j, name in enumerate(des.columns):
            ws.write_string(r, j, str(name), f["sheet_head"])
        r += 1
        for _, row in des.iterrows():
            for j, name in enumerate(des.columns):
                v = row[name]
                if isinstance(v, (int, float, np.integer, np.floating)):
                    ws.write_number(r, j, float(v), f["val_num"])
                else:
                    ws.write_string(r, j, str(v), f["plain"])
            r += 1

    por_tienda = getattr(cuadre, "por_tienda", None)
    if por_tienda is not None and not por_tienda.empty:
        r += 2
        ws.write_string(r, 0, "Cuadre por tienda", f["key"])
        r += 1
        for j, name in enumerate(por_tienda.columns):
            ws.write_string(r, j, str(name), f["sheet_head"])
        r += 1
        for _, row in por_tienda.iterrows():
            for j, name in enumerate(por_tienda.columns):
                v = row[name]
                if isinstance(v, (int, float, np.integer, np.floating)):
                    ws.write_number(r, j, float(v), f["val_num"])
                else:
                    ws.write_string(r, j, str(v), f["plain"])
            r += 1


def _write_data(wb, f, data: pd.DataFrame) -> None:
    ws = wb.add_worksheet("DATA")
    cols = [c for c in data.columns if not c.startswith("_")] + ["_origen"]
    for j, name in enumerate(cols):
        ws.set_column(j, j, 14)
        ws.write_string(0, j, str(name), f["sheet_head"])
    arrays = [data[c].to_numpy() for c in cols]
    for i in range(len(data)):
        for j, arr in enumerate(arrays):
            v = arr[i]
            if v is None or (isinstance(v, float) and np.isnan(v)):
                continue
            if isinstance(v, (int, float, np.integer, np.floating)):
                ws.write_number(i + 1, j, float(v), f["plain"])
            else:
                ws.write_string(i + 1, j, str(v), f["plain"])
    ws.autofilter(0, 0, len(data), len(cols) - 1)
    ws.freeze_panes(1, 0)


# Compatibilidad con la version anterior del modulo.
def write_repo(repo: pd.DataFrame, catalogs: Catalogs, meta: dict | None = None) -> bytes:
    return write_workbook(repo, catalogs, meta=meta)
