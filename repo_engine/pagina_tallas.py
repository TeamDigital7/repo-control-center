"""Tabs de analisis de curva dentro de la Tabla de Repo.

Los tres comparten el mismo calculo (`tallas.analizar`) sobre la foto de stock
que ya se cargo para el REPO, asi que no hay que subir nada extra.
"""

from __future__ import annotations

import io
from datetime import datetime

import pandas as pd
import streamlit as st
import xlsxwriter

from . import tallas as motor
from .transform import build_data, build_rep_matrix, sumar_en_camino
from .catalogs import load_catalogs
from . import config as C
from .ui import chips, issue_box, kpi_row, section


def _fmt(n, dec=0) -> str:
    try:
        return f"{float(n):,.{dec}f}".replace(",", " ")
    except (TypeError, ValueError):
        return "-"


def _analisis():
    """Calcula una vez por sesion y lo reutiliza en los tres tabs."""
    cargados = st.session_state.get("loaded", {})
    if C.SRC_BODEGA not in cargados:
        return None
    fuentes = (C.SRC_BODEGA, C.SRC_VTA, C.SRC_DETALLADO, C.SRC_EVOLUCION)
    sig = tuple(sorted((s, getattr(r, "_sig", None)) for s, r in cargados.items()
                       if s in fuentes))
    enviado = st.session_state.get("enviado_en_stk", True)
    sig = (sig, st.session_state.get("tl_umbral", motor.UMBRAL_CRITICO), enviado)
    if st.session_state.get("tl_sig") == sig and st.session_state.get("tl_result") is not None:
        return st.session_state["tl_result"]

    cat = load_catalogs()
    vta = cargados[C.SRC_VTA].df if C.SRC_VTA in cargados else None
    bod = cargados[C.SRC_BODEGA].df
    with st.spinner("Analizando la curva de tallas por tienda…"):
        data, _ = build_data(vta, bod, cat)
        # Lo ya enviado a la tienda completa su curva: esa talla no esta rota.
        if enviado and C.SRC_DETALLADO in cargados:
            evo = cargados[C.SRC_EVOLUCION].df if C.SRC_EVOLUCION in cargados else None
            en_camino, _ = build_rep_matrix(cargados[C.SRC_DETALLADO].df, evo,
                                            mode="pendiente_recepcion", catalogs=cat)
            data = sumar_en_camino(data, en_camino)
        res = motor.analizar(data, cat,
                             umbral_critico=st.session_state.get("tl_umbral",
                                                                 motor.UMBRAL_CRITICO))
    st.session_state["tl_result"] = res
    st.session_state["tl_sig"] = sig
    return res


def _sin_datos(que: str) -> None:
    issue_box("info", "Falta el archivo de bodega",
              f"{que} se calcula con la foto de stock de BODEGA GESTION. "
              "Subelo en la pestana 'Generar Tabla Repo' y vuelve aqui: "
              "no hay que cargar nada mas.")


# ---------------------------------------------------------------------------

def render(vista: str) -> None:
    res = _analisis()
    if res is None or res.detalle.empty:
        _sin_datos({"tallas": "El analisis de tallas unicas",
                    "critico": "El stock critico",
                    "canales": "El control de SE / FB / DH"}[vista])
        return
    {"tallas": _tab_tallas, "critico": _tab_critico, "canales": _tab_canales}[vista](res)


# ---------------------------------------------------------------------------

def _tab_tallas(res) -> None:
    k = res.kpis
    kpi_row([
        ("Modelos con una sola talla", _fmt(k["unica_talla"]),
         f"de {_fmt(k['combinaciones'])} modelo-tienda"),
        ("Modelos con 1 unidad", _fmt(k["una_unidad"]), "stock minimo"),
        ("Criticos", _fmt(k["criticos"]), "unica talla y unica unidad"),
        ("Unidades en curva rota", _fmt(k["unidades_curva_rota"]),
         f"{k['unidades_curva_rota']/max(k['unidades_total'],1):.0%} del stock"),
        ("Tiendas analizadas", _fmt(k["tiendas"]), "con stock en el REPO"),
    ])

    section("Que muestra", "Una fila por tienda, modelo-color y talla con stock", "ruler")
    st.caption(
        "Una talla suelta no vende: el cliente que entra no calza, ocupa exhibicion "
        "y termina en liquidacion. Estas son las que hay que consolidar por traspaso "
        "o bajar de exhibicion."
    )

    det = _filtros(res.detalle, "tl")
    _mostrar(det)
    _descarga(res, det, "TALLAS UNICAS")

    a, b = st.columns(2)
    with a:
        section("Por tienda", "Donde se rompio mas la curva", "store")
        st.dataframe(res.resumen_tienda, width="stretch", hide_index=True, height=340)
    with b:
        section("Por modelo", "Modelos rotos en varias tiendas a la vez", "package")
        st.dataframe(res.resumen_modelo.head(400), width="stretch", hide_index=True, height=340)


def _tab_critico(res) -> None:
    section("Stock critico", "Modelos cuyo stock total en la tienda esta al limite", "flame")
    umbral = st.slider("Umbral de unidades", 1, 10,
                       st.session_state.get("tl_umbral_critico", 2), key="tl_umbral_critico")
    critico = motor.stock_critico(res.detalle, umbral=umbral)
    if critico.empty:
        issue_box("ok", "Sin stock critico",
                  f"Ningun modelo por tienda quedo con {umbral} unidades o menos.")
        return

    kpi_row([
        ("Modelos en riesgo", _fmt(len(critico)), f"con {umbral} unidades o menos"),
        ("Unidades comprometidas", _fmt(critico["Stock total"].sum()), "stock total"),
        ("Ultima unidad", _fmt((critico["Riesgo"] == "Ultima unidad").sum()),
         "queda una sola"),
        ("Tiendas afectadas", _fmt(critico["Tienda"].nunique()), ""),
    ])

    sub = _filtros(critico, "cr")
    _mostrar(sub)
    _descarga(res, sub, "STOCK CRITICO", tabla_unica=True)


def _tab_canales(res) -> None:
    esp = res.especiales
    section("Control SE / FB / DH", "Los canales de liquidacion, vigilados aparte", "shield")
    st.caption(
        "En Saga Express, Fabrica y Duty Free la talla suelta no es una alerta de "
        "reposicion: es el destino natural de la consolidacion. Lo que importa aqui "
        "es cuanto se esta acumulando y de que modelos."
    )
    if esp.empty:
        issue_box("ok", "Sin alertas en estos canales",
                  "Ningun modelo de SE, FB o DH quedo con curva rota.")
        return

    por_canal = esp.groupby("Canal", as_index=False).agg(**{
        "Alertas": ("Tienda", "size"), "Tiendas": ("Tienda", "nunique"),
        "Modelos": ("Cod Modelo", "nunique"), "Unidades": ("Stock talla", "sum")})
    kpi_row([(f"{r['Canal']}", _fmt(r["Unidades"]),
              f"{_fmt(r['Modelos'])} modelos · {_fmt(r['Tiendas'])} tiendas")
             for _, r in por_canal.iterrows()] +
            [("Total alertas", _fmt(len(esp)), "en los tres canales")])

    chips([("warn", f"{r['Canal']}: {_fmt(r['Alertas'])} alertas")
           for _, r in por_canal.iterrows()])

    sub = _filtros(esp, "ca", con_canal=True)
    _mostrar(sub)
    _descarga(res, sub, "CONTROL SE FB DH", tabla_unica=True)


# ---------------------------------------------------------------------------

def _filtros(tabla: pd.DataFrame, prefijo: str, con_canal: bool = False) -> pd.DataFrame:
    section("Filtros", "", "filter")
    cols = st.columns(4 if con_canal else 4)
    m = pd.Series(True, index=tabla.index)

    if con_canal and "Canal" in tabla.columns:
        sel = cols[0].multiselect("Canal", sorted(tabla["Canal"].dropna().unique()),
                                  key=f"{prefijo}_canal")
        if sel:
            m &= tabla["Canal"].isin(sel)
    elif "Cadena" in tabla.columns:
        sel = cols[0].multiselect("Cadena", sorted(tabla["Cadena"].dropna().unique()),
                                  key=f"{prefijo}_cadena")
        if sel:
            m &= tabla["Cadena"].isin(sel)

    for i, col in enumerate(("Tienda", "Marca"), start=1):
        if col in tabla.columns:
            sel = cols[i].multiselect(col, sorted(tabla[col].dropna().unique()),
                                      key=f"{prefijo}_{col}")
            if sel:
                m &= tabla[col].isin(sel)

    if "Alerta" in tabla.columns:
        sel = cols[3].multiselect("Alerta", sorted(tabla["Alerta"].dropna().unique()),
                                  key=f"{prefijo}_alerta")
        if sel:
            m &= tabla["Alerta"].isin(sel)
    elif "Riesgo" in tabla.columns:
        sel = cols[3].multiselect("Riesgo", sorted(tabla["Riesgo"].dropna().unique()),
                                  key=f"{prefijo}_riesgo")
        if sel:
            m &= tabla["Riesgo"].isin(sel)

    texto = st.text_input("Buscar por codigo o modelo", key=f"{prefijo}_txt",
                          placeholder="RK202011301, SILVER RIDGE…")
    if texto.strip():
        q = texto.strip().upper()
        campos = [c for c in ("Cod Modelo", "Modelo", "Cod Color", "Color") if c in tabla.columns]
        if campos:
            hit = pd.Series(False, index=tabla.index)
            for c in campos:
                hit |= tabla[c].astype("string").str.upper().str.contains(q, na=False)
            m &= hit

    sub = tabla[m]
    st.caption(f"**{_fmt(len(sub))}** filas de {_fmt(len(tabla))}.")
    return sub


#: Tope de celdas que el Styler de pandas puede renderizar sin reventar.
MAX_CELDAS_ESTILO = 200_000


def _estilo(tabla: pd.DataFrame):
    num = [c for c in tabla.columns
           if any(k in c for k in ("Stock", "Unidades", "Venta", "Tallas distintas",
                                   "Tiendas", "Modelos"))
           and tabla[c].dtype.kind in "if"]
    pct = [c for c in tabla.columns if "%" in c]
    fmt = {c: "{:,.0f}" for c in num}
    fmt.update({c: "{:.0%}" for c in pct})
    return tabla.style.format(fmt, na_rep="-")


def _mostrar(tabla: pd.DataFrame, height: int = 460) -> None:
    """Muestra la tabla. El Styler solo se usa si el volumen lo permite."""
    if tabla.empty:
        issue_box("info", "Sin resultados", "Ningun registro cumple los filtros.")
        return
    celdas = tabla.shape[0] * tabla.shape[1]
    if celdas <= MAX_CELDAS_ESTILO:
        st.dataframe(_estilo(tabla), width="stretch", hide_index=True, height=height)
        return
    tope = max(1, MAX_CELDAS_ESTILO // max(tabla.shape[1], 1))
    st.dataframe(tabla.head(tope), width="stretch", hide_index=True, height=height)
    st.caption(
        f"Vista limitada a las primeras **{_fmt(tope)}** filas de {_fmt(len(tabla))}. "
        "Afina los filtros o descarga el Excel: el archivo trae todo."
    )


def _descarga(res, filtrado: pd.DataFrame, nombre: str, tabla_unica: bool = False) -> None:
    section("Descargar", "", "download")
    c1, c2 = st.columns([1, 1])
    if c1.button(f"Generar Excel · {nombre.title()}", key=f"btn_{nombre}",
                 width="stretch", type="primary"):
        hojas = {"Filtrado": filtrado}
        if not tabla_unica:
            hojas.update({"Detalle completo": res.detalle,
                          "Por tienda": res.resumen_tienda,
                          "Por modelo": res.resumen_modelo,
                          "SE FB DH": res.especiales})
        st.session_state[f"xl_{nombre}"] = _excel(hojas, nombre, res.kpis)
    data = st.session_state.get(f"xl_{nombre}")
    if data:
        c2.download_button(f"⬇  Descargar {nombre.title()} (.xlsx)", data=data,
                           file_name=f"{nombre} {datetime.now():%d-%m-%Y}.xlsx",
                           mime="application/vnd.openxmlformats-officedocument."
                                "spreadsheetml.sheet",
                           width="stretch", key=f"dl_{nombre}")


def _excel(hojas: dict, titulo: str, kpis: dict) -> bytes:
    buf = io.BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    base = {"font_name": "Calibri", "font_size": 11}
    f_head = wb.add_format({**base, "bold": True, "bg_color": "#17269A",
                            "font_color": "#FFFFFF", "align": "center",
                            "valign": "vcenter", "text_wrap": True, "border": 1,
                            "border_color": "#101B70"})
    f_txt = wb.add_format(base)
    f_num = wb.add_format({**base, "num_format": "#,##0"})
    f_pct = wb.add_format({**base, "num_format": "0%"})
    f_tit = wb.add_format({**base, "bold": True, "font_size": 18, "font_color": "#17269A"})
    f_key = wb.add_format({**base, "bold": True, "font_color": "#334155"})
    f_si = wb.add_format({**base, "bold": True, "bg_color": "#FEE2E2",
                          "font_color": "#B91C1C", "align": "center"})

    ws = wb.add_worksheet("Resumen")
    ws.hide_gridlines(2)
    ws.set_column(0, 0, 36)
    ws.set_column(1, 1, 18)
    ws.write(1, 0, titulo.title(), f_tit)
    ws.write(2, 0, f"Generado el {datetime.now():%d/%m/%Y %H:%M}", f_txt)
    etiquetas = {
        "combinaciones": "Combinaciones modelo-tienda",
        "unica_talla": "Modelos con una sola talla",
        "una_unidad": "Modelos con 1 unidad",
        "criticos": "Criticos (unica talla y unica unidad)",
        "unidades_curva_rota": "Unidades en curva rota",
        "unidades_total": "Unidades totales analizadas",
        "tiendas": "Tiendas analizadas",
        "especiales_alertas": "Alertas en SE / FB / DH",
        "especiales_unidades": "Unidades en SE / FB / DH",
    }
    fila = 4
    for clave, etiqueta in etiquetas.items():
        if clave in kpis:
            ws.write_string(fila, 0, etiqueta, f_key)
            ws.write_number(fila, 1, float(kpis[clave]), f_num)
            fila += 1

    for nombre, tabla in hojas.items():
        if tabla is None or tabla.empty:
            continue
        hoja = wb.add_worksheet(nombre[:31])
        cols = list(tabla.columns)
        for j, c in enumerate(cols):
            ancho = 26 if str(c) in ("Modelo", "Color", "Tienda", "Tallas") else 14
            hoja.set_column(j, j, ancho)
            hoja.write_string(0, j, str(c), f_head)
        hoja.set_row(0, 32)
        hoja.freeze_panes(1, 1)
        hoja.autofilter(0, 0, len(tabla), len(cols) - 1)
        arrays = [tabla[c].to_numpy() for c in cols]
        for i in range(len(tabla)):
            for j, (c, arr) in enumerate(zip(cols, arrays)):
                v = arr[i]
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                if isinstance(v, (bool,)):
                    hoja.write_string(i + 1, j, "SI" if v else "NO",
                                      f_si if v else f_txt)
                elif isinstance(v, (int, float)):
                    hoja.write_number(i + 1, j, float(v),
                                      f_pct if "%" in str(c) else f_num)
                else:
                    hoja.write_string(i + 1, j, str(v), f_txt)
    wb.close()
    return buf.getvalue()
