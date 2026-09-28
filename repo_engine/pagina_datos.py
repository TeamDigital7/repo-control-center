"""Conexion a BigQuery: rango de fechas en vez de subir el archivo de venta."""

from __future__ import annotations

import json
import traceback
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from . import bq
from .ui import chips, issue_box, kpi_row, section


def _fmt(n, dec=0) -> str:
    try:
        return f"{float(n):,.{dec}f}".replace(",", " ")
    except (TypeError, ValueError):
        return "-"


def _estado():
    hoy = date.today()
    st.session_state.setdefault("bq_desde", hoy - timedelta(days=30))
    st.session_state.setdefault("bq_hasta", hoy)
    st.session_state.setdefault("bq_mapa", None)
    st.session_state.setdefault("bq_cols", None)
    st.session_state.setdefault("bq_max_gb", bq.MAX_GB_POR_DEFECTO)


# ---------------------------------------------------------------------------

def panel_conexion() -> bq.Conexion | None:
    """Estado de la conexion y descubrimiento del esquema. Devuelve la conexion."""
    _estado()
    cfg = bq.config()
    if not bq.disponible(cfg):
        issue_box("info", "BigQuery no configurado",
                  "Agrega los bloques [bigquery] y [gcp_service_account] a "
                  ".streamlit/secrets.toml (los mismos del Catalogo Control Center) "
                  "y aparecera la opcion de traer la venta por rango de fechas.")
        return None

    conn = bq.cliente(cfg)
    if not conn.ok:
        issue_box("error", "No se pudo conectar", conn.detalle)
        return None

    try:
        tabla = bq.tabla_ventas(cfg)
    except RuntimeError as exc:
        issue_box("error", "Falta configurar la tabla de venta", str(exc))
        return None
    tabla = bq.resolver_tabla(conn, tabla, "venta")
    from .pagina_pedidos import aviso_reemplazo
    aviso_reemplazo(tabla, "ventas_table")
    chips([("ok", f"Proyecto {conn.proyecto}"), ("ok", tabla.split(".")[-1])])

    mapa = (bq.cargar_mapeo().get(tabla) or st.session_state.get("bq_mapa"))
    if mapa is not None and bq.faltantes(mapa):
        # Un mapeo guardado incompleto (de antes de mejorar el detector) no
        # debe quedar congelado: lo que falte se completa con la deteccion.
        try:
            cols = st.session_state.get("bq_cols")
            if cols is None:
                cols = bq.columnas(conn, tabla)
                st.session_state["bq_cols"] = cols
            mapa = {**bq.mapear(list(cols["column_name"])), **mapa}
        except Exception:
            pass
    if mapa is None:
        with st.spinner("Leyendo el esquema de la tabla…"):
            try:
                cols = bq.columnas(conn, tabla)
            except Exception as exc:
                issue_box("error", "No pude leer el esquema", bq.explica_error(exc))
                return None
        st.session_state["bq_cols"] = cols
        mapa = bq.mapear(list(cols["column_name"]))
    # Siempre se deja en la sesion, tambien cuando vino del mapeo guardado:
    # si no, el chequeo final leia None y la pagina entera se caia.
    st.session_state["bq_mapa"] = mapa

    if st.button("Volver a detectar el mapeo", key="bq_redetectar",
                 help="Descarta el mapeo guardado de la venta y lo vuelve a "
                      "deducir de los nombres de columna."):
        guardado = bq.cargar_mapeo()
        if guardado.pop(tabla, None) is not None:
            bq.MAPPING_PATH.write_text(json.dumps(guardado, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
        for clave in ("bq_mapa", "bq_cols"):
            st.session_state[clave] = None
        st.rerun()

    problemas = bq.faltantes(mapa)
    if problemas:
        issue_box("warn", "Faltan columnas por mapear",
                  "No reconoci automaticamente: " + ", ".join(problemas) +
                  ". Completalo abajo una sola vez y queda guardado.")
        _editor_mapeo(conn, tabla, mapa)
    else:
        # El mapeo automatico basto: no se muestra el editor para no estorbar.
        st.caption(f"{len(mapa)} columnas reconocidas automaticamente.")
        with st.expander("Revisar el mapeo de columnas"):
            _editor_mapeo(conn, tabla, mapa, expandido=False)
    return conn if not bq.faltantes(st.session_state.get("bq_mapa") or mapa) else None


def _editor_mapeo(conn, tabla: str, mapa: dict, expandido: bool = True) -> None:
    cols = st.session_state.get("bq_cols")
    if cols is None:
        try:
            cols = bq.columnas(conn, tabla)
            st.session_state["bq_cols"] = cols
        except Exception:
            return
    opciones = ["—"] + sorted(str(c) for c in cols["column_name"])

    st.caption(
        f"La tabla tiene **{len(cols)}** columnas. Esto se configura una vez: "
        "el mapeo queda guardado en `data/bq_mapping.json` y se sube al repo."
    )
    nuevo = dict(mapa)
    columnas_ui = st.columns(3)
    for i, campo in enumerate(bq.ALIAS_VENTAS):
        actual = mapa.get(campo, "—")
        idx = opciones.index(actual) if actual in opciones else 0
        etiqueta = f"{campo}{' *' if campo in bq.OBLIGATORIOS else ''}"
        sel = columnas_ui[i % 3].selectbox(etiqueta, opciones, index=idx,
                                           key=f"bqmap_{campo}")
        if sel != "—":
            nuevo[campo] = sel
        else:
            nuevo.pop(campo, None)

    if st.button("Guardar mapeo", width="stretch", type="primary", key="bq_guardar_mapeo"):
        bq.guardar_mapeo(nuevo, tabla)
        st.session_state["bq_mapa"] = nuevo
        st.success("Mapeo guardado.")
        st.rerun()
    with st.popover("Ver las columnas de la tabla", width="stretch"):
        st.dataframe(cols, width="stretch", hide_index=True, height=320)


# ---------------------------------------------------------------------------

ATAJOS = {
    "7 dias": 7,
    "30 dias": 30,
    "90 dias": 90,
    "Este ano": None,
}


def selector_periodo(clave: str, etiqueta: str = "Periodo de venta"):
    """Rango de fechas. Devuelve (desde, hasta, max_gb)."""
    _estado()
    section(etiqueta, "Elige el rango y la app trae la venta ya sumada", "clock")

    # Los atajos ESCRIBEN sobre el calendario en vez de reemplazarlo por detras:
    # antes el rango mostraba una cosa y la consulta usaba otra.
    hoy = date.today()
    cols = st.columns(len(ATAJOS) + 1)
    for i, (nombre, dias) in enumerate(ATAJOS.items()):
        if cols[i].button(nombre, key=f"bq_at_{clave}_{i}", width="stretch"):
            st.session_state["bq_desde"] = (hoy.replace(month=1, day=1) if dias is None
                                            else hoy - timedelta(days=dias - 1))
            st.session_state["bq_hasta"] = hoy
            st.rerun()

    rango = st.date_input(
        "Desde / hasta",
        value=(st.session_state["bq_desde"], st.session_state["bq_hasta"]),
        key=f"bq_rango_{clave}", format="DD/MM/YYYY")
    if isinstance(rango, (tuple, list)) and len(rango) == 2:
        st.session_state["bq_desde"], st.session_state["bq_hasta"] = rango
    desde, hasta = st.session_state["bq_desde"], st.session_state["bq_hasta"]

    dias = (hasta - desde).days + 1
    st.caption(f"**{desde:%d/%m/%Y}** al **{hasta:%d/%m/%Y}** · {dias} dias.")

    with st.expander("Opciones avanzadas"):
        st.session_state["bq_max_gb"] = st.number_input(
            "Tope de lectura (GB)", 1.0, 500.0, float(st.session_state["bq_max_gb"]),
            step=5.0, key=f"bq_gb_{clave}",
            help="Freno de seguridad: si la consulta fuera a leer mas que esto, "
                 "se detiene y avisa en vez de ejecutarse.")
    return desde, hasta, st.session_state["bq_max_gb"]


def traer_ventas(conn, desde: date, hasta: date, max_gb: float,
                 diaria: bool = False):
    """Ejecuta la consulta mostrando antes cuanto va a leer."""
    cfg = bq.config()
    try:
        tabla = bq.tabla_ventas(cfg)
    except RuntimeError as exc:
        issue_box("error", "Falta configurar la tabla de venta", str(exc))
        return None
    mapa = st.session_state.get("bq_mapa") or bq.cargar_mapeo().get(tabla, {})
    if bq.faltantes(mapa):
        issue_box("error", "Mapeo incompleto",
                  "Completa el mapeo de columnas antes de consultar.")
        return None
    try:
        with st.spinner("Consultando BigQuery…"):
            df, gb = bq.ventas(conn, mapa, tabla, desde, hasta,
                               diaria=diaria, max_gb=max_gb)
    except RuntimeError as exc:
        issue_box("warn", "Consulta demasiado grande", str(exc))
        return None
    except Exception as exc:
        issue_box("error", "Fallo la consulta", bq.explica_error(exc))
        with st.expander("Detalle tecnico"):
            st.code(traceback.format_exc())
        return None

    if not len(df):
        explicar_vacio(conn, tabla, mapa, desde, hasta, "venta")
        return None
    unidades = pd.to_numeric(df.get("unidades"), errors="coerce").fillna(0).sum()
    kpi_row([
        ("Filas traidas", _fmt(len(df)), "ya agregadas en el servidor"),
        ("Unidades", _fmt(unidades), f"{desde:%d/%m} al {hasta:%d/%m}"),
        ("Leido de BigQuery", f"{gb:.2f} GB", "coste de la consulta"),
        ("Tiendas", _fmt(df["tienda_nombre"].nunique() if "tienda_nombre" in df
                         else df.get("tienda_cod", pd.Series()).nunique()), ""),
    ])
    return df


def explicar_vacio(conn, tabla: str, mapa: dict, desde: date, hasta: date,
                   etiqueta: str) -> None:
    """Dice por que una consulta por periodo volvio sin filas.

    Separa las causas: tabla vacia, columna de fecha que no se puede leer como
    fecha, o periodo que no cae donde hay datos (con el rango real al lado).
    """
    try:
        perfil = bq.perfil_tabla(conn, tabla, mapa)
    except Exception as exc:
        issue_box("warn", f"La {etiqueta} vino vacia",
                  f"No pude revisar por que: {bq.explica_error(exc)}")
        return
    nombre = tabla.split(".")[-1]
    col = perfil.get("columna_fecha") if perfil else None
    if not perfil or not perfil.get("filas"):
        issue_box("error", f"La tabla de {etiqueta} esta vacia",
                  f"`{nombre}` no tiene ninguna fila. Revisa en los secrets que "
                  "sea la tabla correcta.")
        return
    filas = f"{perfil['filas']:,}".replace(",", " ")
    d, h = perfil.get("desde"), perfil.get("hasta")
    if not perfil.get("con_fecha") or d is None or h is None:
        issue_box("error", f"La {etiqueta} no trajo filas: la fecha no se puede leer",
                  f"`{nombre}` tiene {filas} filas, pero la columna `{col}` no se "
                  "pudo leer como fecha en ninguna. Elige otra columna de fecha en "
                  "el mapeo.")
        return
    issue_box("warn", f"La {etiqueta} no tiene datos en ese periodo",
              f"`{nombre}` tiene {filas} filas, con fechas entre **{d}** y **{h}** "
              f"segun `{col}`. Tu periodo va del {desde:%d/%m/%Y} al "
              f"{hasta:%d/%m/%Y}: ajusta el rango, o revisa en el mapeo si esa es "
              "la columna de fecha que corresponde.")
