"""Repo Control Center - Tabla de Repo Final automatizada.

Flujo: Subir -> Validar -> Procesar -> Revisar -> Descargar.
"""

from __future__ import annotations

import time
import traceback
from datetime import datetime

import pandas as pd
import streamlit as st

from repo_engine import config as C
from repo_engine.auth import logout, require_login
from repo_engine.catalogs import load_catalogs
from repo_engine.excel_writer import write_workbook
from repo_engine import (bq, pagina_datos, pagina_efectividad, pagina_inicio,
                         pagina_llenado, pagina_pedidos, pagina_tallas,
                         sku_directory)
from repo_engine.readers import detect_source, read_any, read_source
from repo_engine.transform import build
from repo_engine.ui import (app_styles, hero, html, issue_box, kpi_row, nav, section,
                            sidebar_brand, sidebar_footer, sidebar_section, slot_row,
                            stepper)
from repo_engine.validation import cross_validate, validate_source

st.set_page_config(page_title="Repo Control Center",
                   page_icon="📦", layout="wide",
                   initial_sidebar_state="expanded")

STEPS = ["Subir archivos", "Validar", "Procesar cruces", "Revisar errores", "Descargar Excel"]


def fmt(n) -> str:
    try:
        return f"{float(n):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return str(n)


# ---------------------------------------------------------------------------
# estado
# ---------------------------------------------------------------------------

def _state():
    st.session_state.setdefault("modulo", "inicio")
    st.session_state.setdefault("tl_result", None)
    st.session_state.setdefault("tl_sig", None)
    st.session_state.setdefault("loaded", {})     # source -> LoadResult
    st.session_state.setdefault("reports", {})    # source -> ValidationReport
    st.session_state.setdefault("result", None)   # BuildResult
    st.session_state.setdefault("excel", None)
    st.session_state.setdefault("rep_mode", C.DEFAULT_REP_MODE)
    st.session_state.setdefault("incluir_data", False)
    st.session_state.setdefault("alerta_negativo", True)


def reset_downstream():
    st.session_state["result"] = None
    st.session_state["excel"] = None


# ---------------------------------------------------------------------------
# paso 1 y 2: carga + validacion
# ---------------------------------------------------------------------------

def render_venta_bigquery():
    """La venta se puede traer del datalake en vez de subir el TXT."""
    conn = pagina_datos.panel_conexion()
    if conn is None:
        return False
    desde, hasta, max_gb = pagina_datos.selector_periodo("repo")
    if st.button("Traer venta de BigQuery", type="primary", width="stretch",
                 key="bq_traer_repo"):
        df = pagina_datos.traer_ventas(conn, desde, hasta, max_gb, diaria=False)
        if df is not None:
            from repo_engine.readers import LoadResult
            vta = bq.a_formato_vta(df)
            res = LoadResult(source=C.SRC_VTA, df=vta, rows_raw=len(vta),
                             notes=[f"Venta traida de BigQuery del {desde:%d/%m/%Y} "
                                    f"al {hasta:%d/%m/%Y}."])
            res._sig = ("bigquery", desde, hasta)
            res._filename = f"BigQuery {desde:%d-%m-%Y} a {hasta:%d-%m-%Y}"
            st.session_state["loaded"][C.SRC_VTA] = res
            st.session_state["reports"][C.SRC_VTA] = validate_source(C.SRC_VTA, vta)
            reset_downstream()
            st.rerun()
    _feedback_bigquery(C.SRC_VTA)
    return True


def _feedback_bigquery(source: str) -> None:
    """Lo traido de BigQuery se muestra igual que un archivo subido.

    Sin esto, despues del rerun no quedaba nada en pantalla y parecia que el
    boton no habia hecho nada.
    """
    res = st.session_state["loaded"].get(source)
    if res is None or getattr(res, "_sig", (None,))[0] != "bigquery":
        return
    st.markdown(f"**{C.SOURCE_META[source]['label']}** · {res._filename}")
    _render_slot_feedback(source)


def render_pedidos_bigquery():
    """El Detallado y la Evolucion tambien salen del datalake.

    Son las dos fuentes que alimentan la columna REP: la cabecera aporta el
    estado del pedido y el detalle las unidades por SKU y tienda.
    """
    from repo_engine.readers import LoadResult

    conn = bq.cliente(bq.config())
    if not conn.ok:
        issue_box("error", "No se pudo conectar", conn.detalle)
        return False
    m_h, m_d = pagina_pedidos.panel_tablas(conn)
    if m_h is None:
        return True

    desde, hasta, max_gb = pagina_datos.selector_periodo(
        "pedidos", "Periodo de pedidos")
    if st.button("Traer pedidos de BigQuery", type="primary", width="stretch",
                 key="bq_traer_pedidos"):
        cfg = bq.config()
        try:
            with st.spinner("Consultando BigQuery…"):
                cab, gb1 = bq.ped_header(conn, m_h, bq.tabla_ped_header(cfg),
                                         desde, hasta, max_gb)
                det, gb2 = bq.ped_detail(conn, m_d, bq.tabla_ped_detail(cfg),
                                         desde, hasta, m_h,
                                         bq.tabla_ped_header(cfg), max_gb)
        except RuntimeError as exc:
            issue_box("warn", "Consulta demasiado grande", str(exc))
            return True
        except Exception as exc:
            issue_box("error", "Fallo la consulta", bq.explica_error(exc))
            with st.expander("Detalle tecnico"):
                st.code(traceback.format_exc())
            return True

        st.session_state["gb_pedidos"] = gb1 + gb2
        if not len(cab) or not len(det):
            # Sin rerun: el aviso de por que vino vacio tiene que quedar a la vista.
            pagina_pedidos._porque_vacio(conn, m_h, m_d, desde, hasta,
                                         len(cab), len(det))
            return True

        periodo = f"del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"
        for source, frame, nota in (
            (C.SRC_EVOLUCION, bq.a_formato_evolucion(cab),
             f"Cabecera de pedidos traida de BigQuery {periodo}."),
            (C.SRC_DETALLADO, bq.a_formato_detallado(det),
             f"Detalle de pedidos traido de BigQuery {periodo}."),
        ):
            notas = [nota]
            if source == C.SRC_DETALLADO and "LLAVE" in frame and \
                    frame["LLAVE"].astype("string").str.fullmatch(r"-*-").all():
                notas.append("El detalle no trae modelo, color ni talla y no se pudo "
                             "completar con el maestro de productos: la LLAVE queda "
                             "vacia. Configura `product_master_table` en los secrets.")
            res = LoadResult(source=source, df=frame, rows_raw=len(frame),
                             notes=notas)
            res._sig = ("bigquery", desde, hasta)
            res._filename = f"BigQuery {desde:%d-%m-%Y} a {hasta:%d-%m-%Y}"
            st.session_state["loaded"][source] = res
            st.session_state["reports"][source] = validate_source(source, frame)
        reset_downstream()
        st.rerun()

    if st.session_state.get("gb_pedidos"):
        st.caption(f"Ultima consulta: {st.session_state['gb_pedidos']:.2f} GB leidos.")
    for source in (C.SRC_EVOLUCION, C.SRC_DETALLADO):
        _feedback_bigquery(source)
    return True


def render_uploads():
    section("Carga los archivos fuente", "Se validan al vuelo; si subes uno en la "
            "casilla equivocada la app lo detecta por su estructura", "upload")

    origen = st.session_state.get("origen_venta", "archivo")
    if bq.disponible():
        origen = st.radio(
            "Origen de la venta", ["archivo", "bigquery"],
            format_func=lambda o: ("Subir el TXT de venta" if o == "archivo"
                                   else "Traer de BigQuery por rango de fechas"),
            horizontal=True, key="origen_venta", label_visibility="collapsed")
    if origen == "bigquery":
        with st.container(border=True):
            render_venta_bigquery()

    origen_ped = st.session_state.get("origen_pedidos", "archivo")
    if bq.disponible():
        origen_ped = st.radio(
            "Origen de los pedidos", ["archivo", "bigquery"],
            format_func=lambda o: ("Subir el Detallado y la Evolucion"
                                   if o == "archivo"
                                   else "Traer de BigQuery por rango de fechas"),
            horizontal=True, key="origen_pedidos", label_visibility="collapsed")
    if origen_ped == "bigquery":
        with st.container(border=True):
            render_pedidos_bigquery()

    desde_bq = {C.SRC_VTA} if origen == "bigquery" else set()
    if origen_ped == "bigquery":
        desde_bq |= {C.SRC_DETALLADO, C.SRC_EVOLUCION}
    fuentes = [s for s in C.SOURCE_ORDER if s not in desde_bq]
    slots = []
    for start in range(0, len(fuentes), 2):
        pair = fuentes[start:start + 2]
        cols = st.columns(2)
        slots.extend(zip(pair, cols))

    for source, column in slots:
        meta = C.SOURCE_META[source]
        with column:
            up = st.file_uploader(
                f"{meta['icon']} · {meta['label']}",
                type=meta["types"],
                key=f"up_{source}",
                help=f"{meta['desc']}  Ejemplo: {meta['hint']}",
            )
            if up is None:
                st.session_state["loaded"].pop(source, None)
                st.session_state["reports"].pop(source, None)
                continue

            sig = (up.name, up.size)
            cached = st.session_state["loaded"].get(source)
            if cached is None or getattr(cached, "_sig", None) != sig:
                try:
                    with st.spinner(f"Leyendo {up.name}…"):
                        res = read_source(source, up, up.name)
                    res._sig = sig
                    res._filename = up.name
                    st.session_state["loaded"][source] = res
                    st.session_state["reports"][source] = validate_source(source, res.df)
                    reset_downstream()
                except Exception as exc:  # pragma: no cover - feedback al usuario
                    st.session_state["loaded"].pop(source, None)
                    st.error(f"No se pudo leer **{up.name}**: {exc}")
                    guess = _guess(up)
                    if guess and guess != source:
                        st.info(f"Parece el archivo de **{C.SOURCE_META[guess]['label']}**.")
                    continue

            _render_slot_feedback(source)


def _guess(up):
    try:
        return detect_source(read_any(up, up.name))
    except Exception:
        return None


def _render_slot_feedback(source: str):
    res = st.session_state["loaded"][source]
    rep = st.session_state["reports"][source]
    for check in rep.errors:
        issue_box("error", check.title, check.detail)
    for check in rep.warnings:
        issue_box("warn", check.title, check.detail)
    ok_checks = [c for c in rep.checks if c.level == "ok"]
    resumen = " · ".join(c.detail for c in ok_checks[:3])
    st.caption(f"**{fmt(res.rows)}** filas utiles de {fmt(res.rows_raw)} leidas.  {resumen}")
    for note in res.notes:
        st.caption(f"↳ {note}")


def missing_sources() -> list[str]:
    return [s for s in C.SOURCE_ORDER if s not in st.session_state["loaded"]]


def blocking_errors() -> list[str]:
    return [s for s, r in st.session_state["reports"].items() if not r.ok]


# ---------------------------------------------------------------------------
# paso 3: proceso
# ---------------------------------------------------------------------------

def render_process():
    faltan, malos = missing_sources(), blocking_errors()
    html('<div class="card"><h3>2 · Validacion cruzada y proceso</h3>'
         '<p class="sub">Los cruces ya estan programados: no hay que configurar mapeos.</p></div>')

    if faltan:
        issue_box("info", "Faltan archivos",
                  "Pendiente: " + ", ".join(C.SOURCE_META[s]["label"] for s in faltan))
        return
    if malos:
        issue_box("error", "Hay archivos con errores de estructura",
                  "Corrige: " + ", ".join(C.SOURCE_META[s]["label"] for s in malos))
        return

    dfs = {s: r.df for s, r in st.session_state["loaded"].items()}
    for check in cross_validate(dfs):
        issue_box(check.level if check.level != "ok" else "ok", check.title, check.detail)

    if st.button("Procesar cruces y generar Tabla de Repo", type="primary", width="stretch"):
        t0 = time.perf_counter()
        try:
            with st.spinner("Cruzando venta, stock, CD y pedidos…"):
                result = build(dfs, rep_mode=st.session_state["rep_mode"])
            with st.spinner("Escribiendo el libro final con formulas y hojas de apoyo…"):
                meta = dict(result.stats)
                meta["generado"] = datetime.now().strftime("%d/%m/%Y %H:%M")
                meta["archivos"] = {
                    C.SOURCE_META[s]["label"]: getattr(r, "_filename", "")
                    for s, r in st.session_state["loaded"].items()
                }
                st.session_state["excel"] = write_workbook(
                    result.repo, result.catalogs,
                    cd=result.cd, cuadre=result.cuadre, en_camino=result.en_camino,
                    data=result.data, sku_dir=result.sku_dir, meta=meta,
                    incluir_data=st.session_state["incluir_data"],
                    alerta_negativo=st.session_state["alerta_negativo"],
                )
            if result.sku_dir:
                sku_directory.save(result.sku_dir)
            result.stats["segundos"] = time.perf_counter() - t0
            st.session_state["result"] = result
            st.rerun()
        except Exception as exc:  # pragma: no cover - feedback al usuario
            st.error(f"Fallo el proceso: {exc}")
            with st.expander("Detalle tecnico"):
                st.code(traceback.format_exc())


# ---------------------------------------------------------------------------
# pasos 4 y 5: revision + descarga
# ---------------------------------------------------------------------------

def render_result():
    result = st.session_state["result"]
    s = result.stats

    kpi_row([
        ("Cuadre", "OK" if s.get("cuadra") else "REVISAR",
         "toda unidad esta en el REPO o explicada"),
        ("Filas del REPO", fmt(s["filas"]), "SKU unicos (Modelo-Color-Talla)"),
        ("SKU resueltos", f"{s.get('sku_cobertura', 0):.0%}",
         f"{fmt(s.get('sku_desde_cd', 0))} del CD + {fmt(s.get('sku_desde_directorio', 0))} del directorio"),
        ("Stock en tienda", fmt(s["unidades_stk"]), "columnas STK"),
        ("En camino", fmt(s.get("en_camino_total", 0)), "pedidos que aun no llegan"),
    ])

    st.download_button(
        "⬇  Descargar Tabla de Repo Final (.xlsx)",
        data=st.session_state["excel"],
        file_name=f"TABLA DE REPO {datetime.now():%d-%m-%Y}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        type="primary",
    )
    st.caption(
        f"Generado en {s.get('segundos', 0):.1f} s · libro vivo con formulas "
        f"({len(C.FIXED_COLUMNS)} columnas fijas + {s['tiendas']}×3 de tienda) "
        "y hojas CD, TIENDAS2, LLAVES, TIENDAS, EN CAMINO y CUADRE."
    )

    tab_cuadre, tab_err, tab_prev, tab_notes = st.tabs(
        ["Cuadre", "Errores relevantes", "Vista previa", "Que se aplico"])

    with tab_cuadre:
        _render_cuadre(result)

    with tab_err:
        criticos = [i for i in result.issues if i.severity in ("error", "warn")]
        if not criticos:
            issue_box("ok", "Sin incidencias criticas", "Todos los cruces resolvieron correctamente.")
        for issue in result.issues:
            issue_box(issue.severity, f"{issue.title} · {fmt(issue.count)}", issue.detail)
            if issue.sample is not None and len(issue.sample):
                with st.expander(f"Ver detalle — {issue.title}"):
                    st.dataframe(issue.sample, width="stretch", hide_index=True)

    with tab_prev:
        cat = result.catalogs
        elegidas = st.multiselect(
            "Tiendas a mostrar", options=[t.abrev for t in cat.tiendas],
            default=[t.abrev for t in cat.tiendas[:6]],
        )
        marcas = st.multiselect("Marcas", options=sorted(result.repo["Marca"].dropna().unique()))
        view = result.repo
        if marcas:
            view = view[view["Marca"].isin(marcas)]
        cols = list(C.FIXED_COLUMNS) + [f"{a}|{m}" for a in elegidas for m in C.STORE_METRICS]
        st.dataframe(view[cols].head(1000), width="stretch", hide_index=True)
        st.caption(f"Mostrando {min(len(view), 1000):,} de {len(view):,} filas.")

    with tab_notes:
        st.markdown("**Formulas que quedan vivas en la hoja REPO**")
        st.code(
            'fila 1   =SUBTOTAL(9,T5:T{n})            total que respeta el autofiltro\n'
            'fila 2   =VLOOKUP(T3,TIENDA,2,0)         codigo de tienda\n'
            'K  SKU   =VLOOKUP(G5&"-"&H5&"-"&I5,CD!$A:$X,19,0)\n'
            'L  TRASP =IFERROR(VLOOKUP($G5&"-"&$H5,TRSPINV26,2,0),"-")\n'
            'M  REPOS =V5+Y5+AB5+...                  suma de las 69 columnas REP\n'
            'N  NVODSP=S5+P5-M5                       DSP + RT - lo ya repuesto\n'
            'O..S     =IFERROR(VLOOKUP(...,CD!$A:$X,18|20|21|22|23,0),0)',
            language="text",
        )
        st.markdown("---")
        for note in result.notes:
            st.markdown(f"- {note}")
        for source, res in st.session_state["loaded"].items():
            for note in res.notes:
                st.markdown(f"- **{C.SOURCE_META[source]['label']}**: {note}")


def _barras_conocidas() -> pd.Series:
    """LLAVE -> codigo de barras, sacado de lo que ya esta cargado.

    Sirve de puente cuando el maestro no trae talla: ARTI da barra -> ID y la
    bodega da LLAVE -> barra.
    """
    from repo_engine.readers import build_llave
    partes = []
    for src in (C.SRC_BODEGA, C.SRC_VTA):
        res = st.session_state.get("loaded", {}).get(src)
        if res is None or "Codigo Barra" not in res.df.columns:
            continue
        d = res.df
        barra = pd.to_numeric(d["Codigo Barra"], errors="coerce")
        partes.append(pd.DataFrame({
            "llave": build_llave(d["Cod. Modelo"], d["Cod. Color"], d["Talla/Numero"]),
            "barra": barra.map(lambda v: "" if pd.isna(v) else str(int(v))),
        }))
    if not partes:
        return pd.Series(dtype="object")
    todo = pd.concat(partes, ignore_index=True)
    todo = todo[(todo["barra"] != "") & (todo["llave"] != "--")]
    return todo.drop_duplicates("llave").set_index("llave")["barra"]


def _render_sku_directory():
    """Directorio LLAVE -> ID Producto: se llena solo y se puede ampliar."""
    directorio = sku_directory.load()
    st.sidebar.markdown("**Directorio de SKU**")
    st.sidebar.caption(
        f"{len(directorio):,} llaves con ID Producto. Crece solo con cada corrida; "
        "el Stock CD del dia solo cubre lo que hoy esta en el CD."
    )

    with st.sidebar.expander("Ampliar de golpe con un maestro"):
        st.caption(
            "Sube cualquier export que traiga ID Producto + Cod. Modelo + Cod. Color "
            "+ Talla. Con un maestro de productos el directorio queda completo de una vez."
        )
        up = st.file_uploader("Archivo", type=["xlsx", "xlsb", "xls", "csv", "txt"],
                              key="up_sku_master", label_visibility="collapsed")
        if up is not None and st.button("Importar al directorio", width="stretch"):
            try:
                df = read_any(up, up.name)
                nuevo, sumados, error = sku_directory.import_file(df, directorio)
                if error:
                    st.error(error)
                    st.caption("Columnas encontradas: " + ", ".join(map(str, df.columns[:20])))
                else:
                    sku_directory.save(nuevo)
                    reset_downstream()
                    st.success(f"{sumados:,} llaves nuevas. Total: {len(nuevo):,}.")
                    st.rerun()
            except Exception as exc:
                st.error(f"No se pudo leer el archivo: {exc}")

    if bq.disponible():
        st.caption("**Desde ARTI**: trae el maestro completo del datalake y llena "
                   "el directorio de una vez.")
        if st.button("Traer SKUs de ARTI", width="stretch", key="bq_arti"):
            conn = bq.cliente()
            if not conn.ok:
                st.error(conn.detalle)
            else:
                try:
                    with st.spinner("Consultando el maestro de productos…"):
                        df, gb, mapa = bq.arti(conn, bq.tabla_arti())   # valida los secrets
                    llaves, via = bq.llaves_desde_arti(df, mapa, _barras_conocidas())
                    nuevo = dict(directorio)
                    sumados = sku_directory.merge(nuevo, llaves["llave"], llaves["id"])
                    sku_directory.save(nuevo)
                    reset_downstream()
                    st.success(f"{sumados:,} llaves nuevas desde ARTI via {via} "
                               f"({gb:.2f} GB leidos). Total: {len(nuevo):,}.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"No se pudo traer ARTI: {type(exc).__name__}: {exc}")

    if directorio:
        st.download_button(
            "Descargar directorio (.json)",
            data=sku_directory.export_json(directorio),
            file_name="sku_directory.json",
            mime="application/json",
            width="stretch",
            help="Guardalo en data/ del repo para que el avance no se pierda al redesplegar.",
        )


def _render_cuadre(result):
    cuadre = result.cuadre
    if cuadre is None:
        st.info("Sin datos de cuadre.")
        return

    if cuadre.cuadra:
        issue_box("ok", "El REPO cuadra",
                  "Cada unidad de los archivos fuente esta en la tabla o explicada "
                  "por una regla conocida. La columna 'Sin explicar' esta en cero.")
    else:
        issue_box("error", "Hay unidades sin explicar",
                  "Revisa la fila marcada con NO: hay unidades del archivo que no "
                  "llegaron al REPO ni fueron excluidas por una regla.")

    st.markdown("**Identidad de control:** `archivo = REPO + excluido por regla + sin explicar`")
    df = cuadre.to_frame()
    st.dataframe(
        df.style.format({
            "Unidades en el archivo": "{:,.0f}",
            "Unidades en el REPO": "{:,.0f}",
            "Excluidas por regla": "{:,.0f}",
            "Sin explicar": "{:,.0f}",
        }),
        width="stretch", hide_index=True,
    )

    des = cuadre.desglose_frame()
    if not des.empty:
        st.markdown("**Cobertura de los cruces**")
        st.dataframe(des, width="stretch", hide_index=True)

    por_tienda = getattr(cuadre, "por_tienda", None)
    if por_tienda is not None and not por_tienda.empty:
        st.markdown("**Cuadre tienda por tienda**")
        desc = por_tienda[(por_tienda["Dif VNT"].abs() > 0.5) |
                          (por_tienda["Dif STK"].abs() > 0.5)]
        if len(desc):
            issue_box("warn", f"{len(desc)} tiendas con diferencia",
                      "El total de la columna no coincide con el archivo fuente.")
            st.dataframe(desc, width="stretch", hide_index=True)
        else:
            issue_box("ok", "Las 69 tiendas cuadran",
                      "VNT y STK de cada columna coinciden exactamente con el archivo.")
        with st.expander("Ver el detalle de las 69 tiendas"):
            st.dataframe(por_tienda, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------

def render_sidebar():
    """Solo navegacion. Los ajustes de cada modulo viven dentro de su pantalla."""
    sidebar_brand(st.session_state.get("auth_user", ""))
    sidebar_section("Modulos")
    modulo = nav(st.session_state.get("modulo", "inicio"))
    sidebar_footer(st.session_state.get("auth_user", ""))
    if st.sidebar.button("Cerrar sesion", width="stretch", key="logout"):
        logout()
    return modulo


# ---------------------------------------------------------------------------
# ajustes de la Tabla de Repo (dentro de su propia pantalla)
# ---------------------------------------------------------------------------

def render_ajustes_repo():
    """Ajustes del modulo, dentro de su propia pantalla y no en el sidebar."""
    cat = load_catalogs()

    with st.expander("Ajustes del proceso y catalogos"):
        c1, c2 = st.columns([1.2, 1])
        with c1:
            st.markdown("**Columna REP (unidades en camino)**")
            modes = list(C.REP_MODES)
            choice = st.radio(
                "Como calcular REP", options=modes,
                format_func=lambda m: C.REP_MODES[m]["label"],
                index=modes.index(st.session_state["rep_mode"]),
                label_visibility="collapsed", key="rep_mode_radio")
            st.caption(C.REP_MODES[choice]["help"])
            if choice != st.session_state["rep_mode"]:
                st.session_state["rep_mode"] = choice
                reset_downstream()
        with c2:
            st.markdown("**Libro de salida**")
            st.caption("Siempre incluye REPO (con formulas), CD, SKUS, TIENDAS2, "
                       "LLAVES, TIENDAS, EN CAMINO y CUADRE.")
            alerta = st.checkbox(
                "Pintar NVO DSP CD en rojo si queda negativo",
                value=st.session_state["alerta_negativo"],
                help="Avisa cuando repones mas de lo disponible en el CD.")
            if alerta != st.session_state["alerta_negativo"]:
                st.session_state["alerta_negativo"] = alerta
                reset_downstream()
            incluir = st.checkbox(
                "Incluir la hoja DATA completa",
                value=st.session_state["incluir_data"],
                help="Tabla larga de auditoria (~140 mil filas). Suma varios minutos y MB.")
            if incluir != st.session_state["incluir_data"]:
                st.session_state["incluir_data"] = incluir
                reset_downstream()

        st.divider()
        c3, c4 = st.columns(2)
        with c3:
            _render_sku_directory()
        with c4:
            st.markdown("**Catalogos de referencia**")
            st.caption(f"{len(cat.tiendas)} tiendas · {len(cat.traspasos)} claves de "
                       "traspaso de temporada")
            with st.popover("Ver las 69 tiendas", width="stretch"):
                st.dataframe(
                    pd.DataFrame([{"Cod": t.cod, "Abrev": t.abrev, "Nombre": t.nombre}
                                  for t in cat.tiendas]),
                    width="stretch", hide_index=True, height=320)
            with st.popover("Actualizar traspasos de temporada", width="stretch"):
                st.caption("Pega los COD MODELO-COD COLOR marcados con T, uno por linea.")
                texto = st.text_area("Claves", value="\n".join(sorted(cat.traspasos)),
                                     height=200, label_visibility="collapsed")
                if st.button("Guardar lista", width="stretch"):
                    from repo_engine.catalogs import save_traspasos
                    save_traspasos([l for l in texto.splitlines() if l.strip()])
                    reset_downstream()
                    st.success("Lista actualizada.")
                    st.rerun()
            if st.button("Reiniciar el proceso", width="stretch"):
                for key in ("loaded", "reports", "result", "excel"):
                    st.session_state.pop(key, None)
                st.rerun()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def render_repo():
    hero("Tabla de Repo Final",
         "Sube los 5 reportes de siempre y descarga el REPO armado: mismos nombres, "
         "mismo orden de columnas y los 69 bloques de tienda listos para trabajar.")

    t_gen, t_tallas, t_critico, t_canales = st.tabs(
        ["Generar Tabla Repo", "Tallas unicas", "Stock critico", "Control SE / FB / DH"])

    with t_gen:
        _tab_generar()
    with t_tallas:
        pagina_tallas.render("tallas")
    with t_critico:
        pagina_tallas.render("critico")
    with t_canales:
        pagina_tallas.render("canales")


def _tab_generar():
    if st.session_state["result"] is not None:
        current = 5
    elif not missing_sources() and not blocking_errors():
        current = 3
    elif st.session_state["loaded"]:
        current = 2
    else:
        current = 1
    stepper(STEPS, current)

    render_ajustes_repo()
    render_uploads()

    section("Estado de la carga", "Cada archivo alimenta una parte distinta del REPO", "layers")
    for source in C.SOURCE_ORDER:
        meta = C.SOURCE_META[source]
        res = st.session_state["loaded"].get(source)
        rep = st.session_state["reports"].get(source)
        if res is None:
            slot_row(meta["icon"], meta["label"], meta["desc"], "wait")
        elif rep is not None and not rep.ok:
            slot_row(meta["icon"], meta["label"], "Estructura no valida", "err")
        else:
            slot_row(meta["icon"], meta["label"],
                     f"{getattr(res, '_filename', '')} · {fmt(res.rows)} filas", "ok")

    render_process()

    if st.session_state["result"] is not None:
        render_result()


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

PAGINAS = {
    "inicio": pagina_inicio.render,
    "llenado": pagina_llenado.render,
    "efectividad": pagina_efectividad.render,
    "pedidos": pagina_pedidos.render,
}


def main():
    _state()
    if not require_login():
        return

    app_styles()
    modulo = render_sidebar()

    pagina = PAGINAS.get(modulo)
    if pagina is not None:
        pagina()
        return
    render_repo()


if __name__ == "__main__":
    main()
