"""Dashboard de pedidos: las cifras del BI, contra BigQuery y en vivo.

Los filtros son acumulativos y vacio significa "todas", igual que los slicers
del reporte original. Todo el tablero se alimenta de UNA consulta por rango de
fechas; filtrar despues ocurre en memoria y no vuelve a cobrar en BigQuery.
"""

from __future__ import annotations

import traceback
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from . import bq, charts, pedidos
from .catalogs import load_catalogs
from .ui import chips, hero, issue_box, kpi_row, section


def _fmt(n, dec=0) -> str:
    try:
        return f"{float(n):,.{dec}f}".replace(",", " ")
    except (TypeError, ValueError):
        return "-"


def _estado() -> None:
    hoy = date.today()
    st.session_state.setdefault("ped_desde", hoy.replace(month=1, day=1))
    st.session_state.setdefault("ped_hasta", hoy)
    st.session_state.setdefault("ped_max_gb", bq.MAX_GB_POR_DEFECTO)
    st.session_state.setdefault("ped_lineas", None)
    st.session_state.setdefault("ped_notas", [])


# ---------------------------------------------------------------------------
# mapeo de las dos tablas
# ---------------------------------------------------------------------------

def _mapa(conn, tabla: str, fuente: str) -> dict | None:
    """Mapeo guardado, o descubierto por alias contra INFORMATION_SCHEMA."""
    guardado = bq.cargar_mapeo().get(tabla)
    if guardado:
        return guardado
    try:
        cols = bq.columnas(conn, tabla)
    except Exception as exc:
        issue_box("error", f"No pude leer el esquema de {tabla.split('.')[-1]}",
                  f"{type(exc).__name__}: {exc}")
        return None
    st.session_state[f"cols_{fuente}"] = cols
    return bq.mapear(list(cols["column_name"]), bq.ALIAS_POR_FUENTE[fuente])


def _editor(conn, tabla: str, fuente: str, mapa: dict) -> dict:
    cols = st.session_state.get(f"cols_{fuente}")
    if cols is None:
        try:
            cols = bq.columnas(conn, tabla)
            st.session_state[f"cols_{fuente}"] = cols
        except Exception:
            return mapa
    opciones = ["—"] + sorted(str(c) for c in cols["column_name"])
    alias = bq.ALIAS_POR_FUENTE[fuente]
    obligatorios = (bq.OBLIG_PED_HEADER if fuente == "ped_header"
                    else bq.OBLIG_PED_DETAIL)

    st.caption(f"`{tabla}` · **{len(cols)}** columnas. Se configura una vez y "
               "queda guardado en `data/bq_mapping.json`.")
    nuevo = dict(mapa)
    grid = st.columns(3)
    for i, campo in enumerate(alias):
        actual = mapa.get(campo, "—")
        idx = opciones.index(actual) if actual in opciones else 0
        etiqueta = f"{campo}{' *' if campo in obligatorios else ''}"
        sel = grid[i % 3].selectbox(etiqueta, opciones, index=idx,
                                    key=f"map_{fuente}_{campo}")
        if sel != "—":
            nuevo[campo] = sel
        else:
            nuevo.pop(campo, None)

    if st.button("Guardar mapeo", type="primary", width="stretch",
                 key=f"guardar_{fuente}"):
        bq.guardar_mapeo(nuevo, tabla)
        st.success("Mapeo guardado.")
        st.rerun()
    with st.popover("Ver las columnas de la tabla", width="stretch"):
        st.dataframe(cols, width="stretch", hide_index=True, height=320)
    return nuevo


def panel_tablas(conn):
    """Devuelve (mapa_header, mapa_detail) o (None, None) si falta mapear."""
    cfg = bq.config()
    t_h, t_d = bq.tabla_ped_header(cfg), bq.tabla_ped_detail(cfg)
    chips([("ok", t_h.split(".")[-1]), ("ok", t_d.split(".")[-1])])

    m_h, m_d = _mapa(conn, t_h, "ped_header"), _mapa(conn, t_d, "ped_detail")
    if m_h is None or m_d is None:
        return None, None

    falta_h = bq.faltantes_pedidos(m_h, "ped_header")
    falta_d = bq.faltantes_pedidos(m_d, "ped_detail")
    if falta_h or falta_d:
        issue_box("warn", "Faltan columnas por mapear",
                  "Cabecera: " + (", ".join(falta_h) or "ok") +
                  " · Detalle: " + (", ".join(falta_d) or "ok") +
                  ". Completalo abajo una sola vez.")
    else:
        st.caption(f"{len(m_h)} columnas reconocidas en la cabecera y "
                   f"{len(m_d)} en el detalle.")

    with st.expander("Mapeo de columnas · cabecera", expanded=bool(falta_h)):
        m_h = _editor(conn, t_h, "ped_header", m_h)
    with st.expander("Mapeo de columnas · detalle", expanded=bool(falta_d)):
        m_d = _editor(conn, t_d, "ped_detail", m_d)

    if bq.faltantes_pedidos(m_h, "ped_header") or bq.faltantes_pedidos(m_d, "ped_detail"):
        return None, None
    return m_h, m_d


# ---------------------------------------------------------------------------
# consulta
# ---------------------------------------------------------------------------

def _traer(conn, m_h, m_d, desde, hasta, max_gb):
    cfg = bq.config()
    t_h, t_d = bq.tabla_ped_header(cfg), bq.tabla_ped_detail(cfg)
    try:
        with st.spinner("Consultando BigQuery…"):
            cab, gb1 = bq.ped_header(conn, m_h, t_h, desde, hasta, max_gb)
            det, gb2 = bq.ped_detail(conn, m_d, t_d, desde, hasta, m_h, t_h, max_gb)
    except RuntimeError as exc:
        issue_box("warn", "Consulta demasiado grande", str(exc))
        return None
    except Exception as exc:
        issue_box("error", "Fallo la consulta", f"{type(exc).__name__}: {exc}")
        with st.expander("Detalle tecnico"):
            st.code(traceback.format_exc())
        return None

    lineas, notas = pedidos.construir(det, cab, load_catalogs())
    notas.append(f"Leidos {gb1 + gb2:.2f} GB de BigQuery.")
    st.session_state["ped_lineas"] = lineas
    st.session_state["ped_notas"] = notas
    return lineas


# ---------------------------------------------------------------------------
# tablero
# ---------------------------------------------------------------------------

def _filtros(df: pd.DataFrame) -> dict[str, list[str]]:
    """Un multiselect por dimension con datos. Vacio = todas."""
    presentes = [(c, et) for c, et in pedidos.DIMENSIONES.items()
                 if c in df.columns and df[c].notna().any()]
    seleccion: dict[str, list[str]] = {}
    filas = [presentes[i:i + 4] for i in range(0, len(presentes), 4)]
    for fila in filas:
        cols = st.columns(len(fila))
        for col, (campo, etiqueta) in zip(cols, fila):
            seleccion[campo] = col.multiselect(
                etiqueta, pedidos.opciones(df, campo), default=[],
                key=f"filtro_ped_{campo}", placeholder="Todas")
    return seleccion


def _tablero(df: pd.DataFrame) -> None:
    k = pedidos.kpis(df)
    kpi_row([
        ("Cantidad Pedida", _fmt(k["pedida"]), f"{k['pedidos']:,} pedidos".replace(",", " ")),
        ("Cantidad Despachada", _fmt(k["despachada"]), "lo que salio del CD"),
        ("Var Pedidos", _fmt(k["var"]), "pedido menos despachado"),
        ("% Cumplimiento", f"{k['cumplimiento']:.2f} %", "despachado / pedido"),
    ])
    if df.empty:
        issue_box("info", "Sin datos", "Ningun pedido cumple los filtros elegidos.")
        return

    izq, der = st.columns(2)
    with izq:
        section("Pedidos por tienda", "Pedido contra despachado", "store")
        t_tienda = pedidos.por(df, "tienda")
        st.altair_chart(charts.pedidos_barras(t_tienda, "tienda", top=12),
                        use_container_width=True)
    with der:
        section("Cumplimiento por tienda", "Donde se queda corto el despacho", "target")
        st.altair_chart(
            charts.cumplimiento_barras(t_tienda.sort_values("%Cumplimiento"),
                                       "tienda", top=12),
            use_container_width=True)

    izq, der = st.columns(2)
    with izq:
        section("Por cadena", "", "layers")
        st.altair_chart(charts.pedidos_columnas(pedidos.por(df, "cadena"), "cadena"),
                        use_container_width=True)
    with der:
        section("Por marca", "", "package")
        st.altair_chart(charts.pedidos_barras(pedidos.por(df, "marca"), "marca", top=10),
                        use_container_width=True)

    section("Evolucion", "Pedido contra despachado en el tiempo", "clock")
    gran = st.radio("Granularidad", list(pedidos.PERIODOS), horizontal=True,
                    key="ped_gran", label_visibility="collapsed")
    serie = pedidos.por_periodo(df, gran)
    if serie.empty:
        issue_box("info", "Sin fechas",
                  "La cabecera no trajo fecha mapeada: no hay serie temporal.")
    else:
        st.altair_chart(charts.pedidos_evolucion(serie), use_container_width=True)

    izq, der = st.columns(2)
    with izq:
        section("Tipo de pedido por estado", "Unidades pedidas", "grid")
        matriz = pedidos.matriz_estado(df)
        if not matriz.empty:
            st.dataframe(matriz, width="stretch", hide_index=True)
    with der:
        section("Por clasificacion", "", "filter")
        st.altair_chart(
            charts.pedidos_barras(pedidos.por(df, "tipo_pedido"), "tipo_pedido", top=10),
            use_container_width=True)

    section("Detalle por tienda", "La tabla del BI, descargable", "table")
    tabla = t_tienda.copy()
    for c in ("Cantidad Pedida", "Cantidad Despachada", "Var"):
        tabla[c] = tabla[c].round(0).astype(int)
    tabla["%Cumplimiento"] = tabla["%Cumplimiento"].round(2)
    st.dataframe(tabla, width="stretch", hide_index=True)
    st.download_button("Descargar (.csv)", tabla.to_csv(index=False).encode("utf-8"),
                       "pedidos_por_tienda.csv", "text/csv", width="stretch")


# ---------------------------------------------------------------------------

def render() -> None:
    _estado()
    hero("Dashboard de Pedidos",
         "Pedido contra despachado, en vivo desde BigQuery",
         "Planeamiento y reposicion")

    cfg = bq.config()
    if not bq.disponible(cfg):
        issue_box("info", "BigQuery no configurado",
                  "Agrega los bloques [bigquery] y [gcp_service_account] a "
                  ".streamlit/secrets.toml para habilitar este modulo.")
        return
    conn = bq.cliente(cfg)
    if not conn.ok:
        issue_box("error", "No se pudo conectar", conn.detalle)
        return

    section("Origen", "Cabecera y detalle de pedidos", "layers")
    m_h, m_d = panel_tablas(conn)
    if m_h is None:
        return

    section("Periodo", "El rango acota la consulta y el costo", "clock")
    cols = st.columns([3, 1])
    rango = cols[0].date_input(
        "Desde / hasta",
        value=(st.session_state["ped_desde"], st.session_state["ped_hasta"]),
        key="ped_rango", format="DD/MM/YYYY")
    if isinstance(rango, (tuple, list)) and len(rango) == 2:
        st.session_state["ped_desde"], st.session_state["ped_hasta"] = rango
    st.session_state["ped_max_gb"] = cols[1].number_input(
        "Tope (GB)", 1.0, 500.0, float(st.session_state["ped_max_gb"]), step=5.0,
        key="ped_gb", help="Si la consulta fuera a leer mas que esto, se detiene.")

    if st.button("Traer pedidos", type="primary", width="stretch", key="ped_traer"):
        _traer(conn, m_h, m_d, st.session_state["ped_desde"],
               st.session_state["ped_hasta"], st.session_state["ped_max_gb"])

    lineas = st.session_state.get("ped_lineas")
    if lineas is None:
        issue_box("info", "Elige el periodo y trae los pedidos",
                  "Se consulta una sola vez: los filtros de abajo trabajan en "
                  "memoria y no vuelven a cobrar en BigQuery.")
        return

    for nota in st.session_state.get("ped_notas", []):
        st.caption(nota)

    section("Filtros", "Vacio = todas, igual que el BI", "filter")
    seleccion = _filtros(lineas)
    _tablero(pedidos.filtrar(lineas, seleccion))
