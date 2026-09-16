"""Dashboard de pedidos: las cifras del BI, contra BigQuery y en vivo.

Los filtros son acumulativos y vacio significa "todas", igual que los slicers
del reporte original. Todo el tablero se alimenta de UNA consulta por rango de
fechas; filtrar despues ocurre en memoria y no vuelve a cobrar en BigQuery.
"""

from __future__ import annotations

import traceback
from datetime import date, datetime, timedelta

import pandas as pd
import streamlit as st

from . import bq, charts, pedidos, pedidos_excel
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
                  bq.explica_error(exc))
        return None
    if not len(cols):
        _no_existe(conn, tabla)
        return None
    st.session_state[f"cols_{fuente}"] = cols
    return bq.mapear(list(cols["column_name"]), bq.ALIAS_POR_FUENTE[fuente])


def _no_existe(conn, tabla: str) -> None:
    """La consulta corrio pero el dataset no tiene esa tabla: hay que ubicarla.

    Que INFORMATION_SCHEMA devuelva cero filas sin error significa que el
    dataset existe y hay permiso; lo que no existe es la tabla con ese nombre
    exacto. Se busca donde si esta en vez de dejar al usuario adivinando.
    """
    proyecto, dataset, nombre = tabla.split(".")
    issue_box("error", f"No existe la tabla {nombre}",
              f"El dataset `{dataset}` responde y tienes permiso, pero no tiene "
              f"ninguna tabla que se llame exactamente `{nombre}`. "
              "Puede estar en otro dataset, o el nombre no coincide "
              "(INFORMATION_SCHEMA distingue mayusculas de minusculas).")
    with st.spinner("Buscando donde esta esa tabla…"):
        try:
            encontradas = bq.buscar_tablas(conn, tabla, "pedido")
        except Exception:
            encontradas = None
    if encontradas is None or not len(encontradas):
        st.caption("Tampoco encontre tablas con 'pedido' en el nombre dentro del "
                   "proyecto. Confirma con el equipo de datos el nombre completo.")
        return
    st.caption(f"Tablas del proyecto `{proyecto}` con **pedido** en el nombre. "
               "Copia el nombre completo de la que corresponda y ponla en los "
               "secrets como `pedidos_header_table` / `pedidos_detail_table`:")
    vista = encontradas.copy()
    vista.insert(0, "nombre completo",
                 proyecto + "." + vista["table_schema"] + "." + vista["table_name"])
    st.dataframe(vista, width="stretch", hide_index=True, height=260)


def _editor(conn, tabla: str, fuente: str, mapa: dict) -> dict:
    cols = st.session_state.get(f"cols_{fuente}")
    if cols is None:
        try:
            cols = bq.columnas(conn, tabla)
            st.session_state[f"cols_{fuente}"] = cols
        except Exception:
            return mapa
    if not len(cols):
        st.caption("Sin columnas que mapear: primero hay que dar con la tabla "
                   "correcta (ver el aviso de arriba).")
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
    try:
        t_h, t_d = bq.tabla_ped_header(cfg), bq.tabla_ped_detail(cfg)
    except RuntimeError as exc:
        issue_box("error", "Revisa el nombre de las tablas en los secrets", str(exc))
        return None, None
    # En gris hasta saber que existen: un check verde sobre una tabla que no
    # esta seria mentir en la parte que mas rapido se mira.
    chips([("idle", t_h.split(".")[-1]), ("idle", t_d.split(".")[-1])])

    m_h, m_d = _mapa(conn, t_h, "ped_header"), _mapa(conn, t_d, "ped_detail")
    if m_h is None or m_d is None:
        return None, None
    chips([("ok", "cabecera conectada"), ("ok", "detalle conectado")])

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

    if st.button("Volver a detectar el mapeo", key="redetectar",
                 help="Descarta el mapeo guardado y lo vuelve a deducir de los "
                      "nombres de columna. Util despues de una mejora del "
                      "detector o si se guardo uno incompleto."):
        for t in (t_h, t_d):
            guardado = bq.cargar_mapeo()
            guardado.pop(t, None)
            bq.MAPPING_PATH.write_text(__import__("json").dumps(guardado, indent=1),
                                       encoding="utf-8")
        for clave in ("cols_ped_header", "cols_ped_detail"):
            st.session_state.pop(clave, None)
        st.rerun()

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
        issue_box("error", "Fallo la consulta", bq.explica_error(exc))
        with st.expander("Detalle tecnico"):
            st.code(traceback.format_exc())
        return None

    notas_previas = [f"Cabecera: {len(cab):,} filas · Detalle: {len(det):,} filas."
                     .replace(",", " ")]
    if not len(det) or not len(cab):
        _porque_vacio(conn, m_h, m_d, desde, hasta, len(cab), len(det))

    lineas, notas = pedidos.construir(det, cab, load_catalogs())
    notas = notas_previas + notas
    notas.append(f"Leidos {gb1 + gb2:.2f} GB de BigQuery.")
    st.session_state["ped_lineas"] = lineas
    st.session_state["ped_notas"] = notas
    return lineas


def _porque_vacio(conn, m_h, m_d, desde, hasta, n_cab: int, n_det: int) -> None:
    """Separa las tres causas de un resultado vacio en vez de dejarlas juntas."""
    cfg = bq.config()
    for etiqueta, mapa, tabla, filas in (
            ("cabecera", m_h, bq.tabla_ped_header(cfg), n_cab),
            ("detalle", m_d, bq.tabla_ped_detail(cfg), n_det)):
        if filas:
            continue
        try:
            perfil = bq.perfil_tabla(conn, tabla, mapa)
        except Exception as exc:
            issue_box("warn", f"La {etiqueta} vino vacia",
                      f"No pude revisar por que: {bq.explica_error(exc)}")
            continue
        if not perfil or not perfil.get("filas"):
            issue_box("error", f"La tabla de {etiqueta} esta vacia",
                      f"`{tabla}` no tiene ninguna fila. Revisa que sea la tabla "
                      "correcta: puede que los datos esten en otra.")
            continue
        d, h = perfil.get("desde"), perfil.get("hasta")
        col = perfil.get("columna_fecha")
        if d is None or h is None:
            issue_box("warn", f"La {etiqueta} no trajo filas en el periodo",
                      f"La tabla tiene {perfil['filas']:,} filas pero la columna de "
                      f"fecha (`{col}`) esta vacia o no se pudo leer como fecha. "
                      "Revisa en el mapeo que sea la columna correcta."
                      .replace(",", " "))
            continue
        issue_box("warn", f"La {etiqueta} no tiene datos en ese periodo",
                  f"`{tabla}` tiene {perfil['filas']:,} filas, con fechas entre "
                  f"**{d}** y **{h}** segun la columna `{col}`. Tu periodo va del "
                  f"{desde:%d/%m/%Y} al {hasta:%d/%m/%Y}: ajusta el rango, o "
                  "revisa en el mapeo si esa es la columna de fecha que "
                  "corresponde.".replace(",", " "))


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
    tabla = t_tienda.rename(columns={"tienda": "Tienda"}).copy()
    for c in ("Cantidad Pedida", "Cantidad Despachada", "Var"):
        tabla[c] = tabla[c].round(0).astype(int)
    tabla["%Cumplimiento"] = tabla["%Cumplimiento"].round(2)
    st.dataframe(tabla, width="stretch", hide_index=True)

    _descargas(df)


VISTAS_CSV = {
    "Por tienda": "tienda",
    "Por cadena": "cadena",
    "Por marca": "marca",
    "Por clasificacion": "tipo_pedido",
    "Por estado": "estado",
    "Por tipo de prenda": "tipo_prenda",
    "Por ciudad": "ciudad",
}


def _descargas(df: pd.DataFrame) -> None:
    """Lo que se baja es lo que esta en pantalla: si hay filtros, van aplicados."""
    section("Descargar", "Se exporta con los filtros que tengas puestos", "download")
    sello = datetime.now().strftime("%Y-%m-%d_%H%M")

    izq, der = st.columns([2, 1])
    with izq:
        st.caption("**Libro completo** · resumen, una hoja por vista, la matriz "
                   "tipo x estado, la evolucion y el detalle linea a linea.")
        try:
            libro = pedidos_excel.construir(
                df, {"periodo": _periodo_texto(),
                     "notas": st.session_state.get("ped_notas", [])})
        except Exception as exc:                      # nunca tumbar el tablero
            issue_box("warn", "No se pudo armar el Excel",
                      f"{type(exc).__name__}: {exc}. Usa las descargas en CSV.")
        else:
            st.download_button(
                f"Descargar Excel ({len(libro) / 1e6:.1f} MB)", libro,
                f"dashboard_pedidos_{sello}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch", type="primary", key="ped_xlsx")
    with der:
        st.caption("**Una vista en CSV**")
        vista = st.selectbox("Vista", list(VISTAS_CSV) + ["Lineas (detalle)"],
                             key="ped_vista_csv", label_visibility="collapsed")
        if vista == "Lineas (detalle)":
            datos, nombre = df, "lineas"
        else:
            campo = VISTAS_CSV[vista]
            datos = pedidos.por(df, campo)
            nombre = campo
        st.download_button(
            f"Descargar CSV ({len(datos):,} filas)".replace(",", " "),
            datos.to_csv(index=False).encode("utf-8-sig"),
            f"pedidos_{nombre}_{sello}.csv", "text/csv",
            width="stretch", key="ped_csv")


def _periodo_texto() -> str:
    desde = st.session_state.get("ped_desde")
    hasta = st.session_state.get("ped_hasta")
    if desde and hasta:
        return f"Del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"
    return f"Generado el {datetime.now():%d/%m/%Y %H:%M}"


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
