"""Traer venta, Evolucion y Detallado de BigQuery con un solo boton.

Antes eran dos bloques con su propio periodo, su propio boton y el mapeo de
columnas siempre a la vista. Aca todo eso se resuelve solo: las tablas se
comprueban, las columnas se reconocen y el mapeo solo aparece si algo falta.
Lo que ve el planner es un periodo, un boton y el resultado.
"""

from __future__ import annotations

import json
import traceback
from dataclasses import dataclass, field
from datetime import date, timedelta

import pandas as pd
import streamlit as st

from . import bq, config as C
from .readers import LoadResult
from .ui import chips, issue_box
from .validation import validate_source


@dataclass
class Fuente:
    clave: str                 # ventas | ped_header | ped_detail
    source: str                # SRC_* de config
    etiqueta: str
    tabla: str = ""
    mapa: dict = field(default_factory=dict)
    faltan: list[str] = field(default_factory=list)
    error: str | None = None
    columnas: list[str] = field(default_factory=list)

    @property
    def lista(self) -> bool:
        return self.error is None and not self.faltan


#: clave, source, etiqueta, funcion de tabla, patron de busqueda, clave de secrets
FUENTES = (
    ("ventas", C.SRC_VTA, "Venta", bq.tabla_ventas, "venta", "ventas_table"),
    ("ped_header", C.SRC_EVOLUCION, "Evolucion (cabecera)", bq.tabla_ped_header,
     "pedido", "pedidos_header_table"),
    ("ped_detail", C.SRC_DETALLADO, "Detallado (detalle)", bq.tabla_ped_detail,
     "pedido", "pedidos_detail_table"),
)


def _faltan(clave: str, mapa: dict) -> list[str]:
    return bq.faltantes(mapa) if clave == "ventas" else bq.faltantes_pedidos(mapa, clave)


def preparar(conn: bq.Conexion) -> dict[str, Fuente]:
    """Comprueba las tres tablas y arma su mapeo, sin dibujar nada."""
    cfg = bq.config()
    guardados = bq.cargar_mapeo()
    salida: dict[str, Fuente] = {}
    for clave, source, etiqueta, fn_tabla, patron, _secret in FUENTES:
        f = Fuente(clave, source, etiqueta)
        salida[clave] = f
        try:
            tabla = fn_tabla(cfg)
        except RuntimeError as exc:
            f.error = str(exc)
            continue
        tabla = bq.resolver_tabla(conn, tabla, patron)
        f.tabla = tabla
        tipos = bq.tipos(conn, tabla)
        if not tipos:
            try:
                bq.columnas(conn, tabla)
                f.error = (f"No existe la tabla `{tabla}` o no tienes permiso. "
                           "Revisa el nombre en los secrets.")
            except Exception as exc:
                f.error = bq.explica_error(exc)
            continue
        f.columnas = list(tipos)
        alias = bq.ALIAS_VENTAS if clave == "ventas" else bq.ALIAS_POR_FUENTE[clave]
        # Lo guardado a mano manda; la deteccion completa lo que falte.
        guardado = {k: v for k, v in (guardados.get(tabla) or {}).items() if v in tipos}
        f.mapa = {**bq.mapear(f.columnas, alias), **guardado}
        f.faltan = _faltan(clave, f.mapa)
    return salida


# ---------------------------------------------------------------------------
# consulta
# ---------------------------------------------------------------------------

def _guardar(source: str, frame: pd.DataFrame, notas: list[str],
             desde: date, hasta: date) -> None:
    res = LoadResult(source=source, df=frame, rows_raw=len(frame), notes=notas)
    res._sig = ("bigquery", desde, hasta)
    res._filename = f"BigQuery {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"
    st.session_state["loaded"][source] = res
    st.session_state["reports"][source] = validate_source(source, frame)


def _resumen_estados(cab: pd.DataFrame) -> str | None:
    """Que valores de estado llegaron, para confirmar cuales son Aprobado/Despachado."""
    if "estado" not in cab.columns or cab.empty:
        return None
    cuenta = cab["estado"].astype("string").fillna("(vacio)").value_counts().head(8)
    partes = [f"{k}: {v:,}".replace(",", " ") for k, v in cuenta.items()]
    return "Estados de pedido encontrados · " + " · ".join(partes)


DIAS_PEDIDOS = 60


def periodo_pedidos(desde: date, hasta: date) -> tuple[date, date]:
    """Siempre hasta hoy, y al menos los ultimos N dias de pedidos."""
    hoy = date.today()
    dias = int(st.session_state.get("bq_dias_pedidos", DIAS_PEDIDOS))
    return min(desde, hoy - timedelta(days=dias - 1)), max(hasta, hoy)


def traer(conn, prep: dict[str, Fuente], desde: date, hasta: date,
          max_gb: float) -> list[tuple[str, str, str]]:
    """Trae lo que este listo. Devuelve los avisos que deben quedar a la vista."""
    from .pagina_datos import explicar_vacio

    avisos: list[tuple[str, str, str]] = []
    gb_total = 0.0
    periodo = f"del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"

    def fallo(etiqueta: str, exc: Exception) -> None:
        if isinstance(exc, RuntimeError):
            avisos.append(("warn", f"{etiqueta}: no se trajo", str(exc)))
        else:
            avisos.append(("error", f"{etiqueta}: fallo la consulta",
                           bq.explica_error(exc)))
            st.session_state["bq_traza"] = traceback.format_exc()

    v = prep["ventas"]
    if v.lista:
        try:
            with st.spinner("Trayendo la venta…"):
                df, gb = bq.ventas(conn, v.mapa, v.tabla, desde, hasta, max_gb=max_gb)
            gb_total += gb
            if len(df):
                _guardar(C.SRC_VTA, bq.a_formato_vta(df),
                         [f"Venta traida de BigQuery {periodo}."], desde, hasta)
            else:
                explicar_vacio(conn, v.tabla, v.mapa, desde, hasta, "venta")
                avisos.append(("warn", "La venta vino vacia",
                               "Mira el aviso de arriba: dice en que fechas si hay datos."))
        except Exception as exc:
            fallo("Venta", exc)

    # Los pedidos no se acotan al periodo de venta: para la REP importa lo que
    # sigue en camino HOY, aunque se haya pedido semanas antes.
    desde_p, hasta_p = periodo_pedidos(desde, hasta)
    desde, hasta = desde_p, hasta_p
    periodo = f"del {desde:%d/%m/%Y} al {hasta:%d/%m/%Y}"
    h, d = prep["ped_header"], prep["ped_detail"]
    if h.lista and d.lista:
        try:
            with st.spinner("Trayendo la Evolucion y el Detallado…"):
                cab, gb1 = bq.ped_header(conn, h.mapa, h.tabla, desde, hasta, max_gb)
                det, gb2 = bq.ped_detail(conn, d.mapa, d.tabla, desde, hasta,
                                         h.mapa, h.tabla, max_gb)
            gb_total += gb1 + gb2
            if not len(cab):
                explicar_vacio(conn, h.tabla, h.mapa, desde, hasta, "cabecera")
                avisos.append(("warn", "Los pedidos vinieron vacios",
                               "Mira el aviso de arriba: dice en que fechas si hay datos."))
            elif not len(det):
                avisos.append(("warn", "El Detallado vino vacio",
                               f"La cabecera trajo {len(cab):,} pedidos pero el detalle "
                               "ninguna linea: el numero de pedido no cruza entre las "
                               "dos tablas.".replace(",", " ")))
            else:
                notas_cab = [f"Cabecera de pedidos traida de BigQuery {periodo}."]
                estados = _resumen_estados(cab)
                if estados:
                    notas_cab.append(estados)
                _guardar(C.SRC_EVOLUCION, bq.a_formato_evolucion(cab), notas_cab,
                         desde, hasta)
                detallado = bq.a_formato_detallado(det)
                notas_det = [f"Detalle de pedidos traido de BigQuery {periodo}."]
                if detallado["LLAVE"].astype("string").str.fullmatch(r"-*-").all():
                    notas_det.append(
                        "El detalle no trae modelo, color ni talla y no se pudo "
                        "completar con el maestro de productos: la LLAVE queda vacia. "
                        "Configura `product_master_table` en los secrets.")
                _guardar(C.SRC_DETALLADO, detallado, notas_det, desde, hasta)
        except Exception as exc:
            fallo("Pedidos", exc)

    st.session_state["bq_gb"] = gb_total
    return avisos


# ---------------------------------------------------------------------------
# pantalla
# ---------------------------------------------------------------------------

def _estado_chips(prep: dict[str, Fuente]) -> None:
    items = []
    for f in prep.values():
        res = st.session_state["loaded"].get(f.source)
        if res is not None and getattr(res, "_sig", (None,))[0] == "bigquery":
            items.append(("ok", f"{f.etiqueta} · {len(res.df):,} filas".replace(",", " ")))
        elif f.error:
            items.append(("err", f"{f.etiqueta} · sin conexion"))
        elif f.faltan:
            items.append(("warn", f"{f.etiqueta} · faltan columnas"))
        else:
            items.append(("idle", f"{f.etiqueta} · lista"))
    chips(items)


def _ajustes(conn, prep: dict[str, Fuente]) -> None:
    """Lo tecnico, fuera del camino: que tabla se usa y que columna es cada campo."""
    st.session_state["bq_dias_pedidos"] = st.number_input(
        "Dias de pedidos hacia atras (hasta hoy)", 7, 365,
        int(st.session_state.get("bq_dias_pedidos", DIAS_PEDIDOS)), step=7,
        key="bq_dias_ped_in",
        help="Se traen los pedidos de estos ultimos dias, sea cual sea el periodo de "
             "venta, para no perder pedidos antiguos que siguen en camino.")
    for f in prep.values():
        st.markdown(f"**{f.etiqueta}** · `{f.tabla or 'sin tabla'}`")
        antes = bq.tabla_configurada(f.tabla) if f.tabla else f.tabla
        if antes != f.tabla:
            st.caption(f"En los secrets dice `{antes.split('.')[-1]}`, que no existe; "
                       f"uso esta. Para dejarlo fijo, cambia el nombre en los secrets.")
        if f.error:
            issue_box("error", "Sin conexion a esta tabla", f.error)
            continue
        alias = bq.ALIAS_VENTAS if f.clave == "ventas" else bq.ALIAS_POR_FUENTE[f.clave]
        opciones = ["—"] + sorted(f.columnas)
        nuevo = dict(f.mapa)
        grid = st.columns(3)
        for i, campo in enumerate(alias):
            actual = f.mapa.get(campo, "—")
            idx = opciones.index(actual) if actual in opciones else 0
            marca = " *" if campo in _faltan(f.clave, {}) or campo in f.faltan else ""
            sel = grid[i % 3].selectbox(f"{campo}{marca}", opciones, index=idx,
                                        key=f"todo_map_{f.clave}_{campo}")
            if sel != "—":
                nuevo[campo] = sel
            else:
                nuevo.pop(campo, None)
        a, b = st.columns(2)
        if a.button("Guardar columnas", key=f"todo_guardar_{f.clave}", width="stretch"):
            bq.guardar_mapeo(nuevo, f.tabla)
            st.rerun()
        if b.button("Volver a detectar", key=f"todo_redetectar_{f.clave}",
                    width="stretch"):
            guardado = bq.cargar_mapeo()
            guardado.pop(f.tabla, None)
            bq.MAPPING_PATH.write_text(json.dumps(guardado, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
            for campo in alias:
                st.session_state.pop(f"todo_map_{f.clave}_{campo}", None)
            st.rerun()
        st.divider()


def render() -> None:
    """Un periodo y un boton: venta, Evolucion y Detallado de una vez."""
    from .pagina_datos import selector_periodo

    conn = bq.cliente(bq.config())
    if not conn.ok:
        issue_box("error", "No se pudo conectar a BigQuery", conn.detalle)
        return

    with st.spinner("Revisando las tablas…"):
        prep = preparar(conn)
    _estado_chips(prep)

    problemas = [f for f in prep.values() if not f.lista]
    for f in problemas:
        if f.error:
            issue_box("error", f"{f.etiqueta}: no se puede leer", f.error)
        else:
            issue_box("warn", f"{f.etiqueta}: faltan columnas",
                      "No reconoci: " + ", ".join(f.faltan) +
                      ". Elige la columna en 'Ajustes de tablas y columnas' (abajo).")

    desde, hasta, max_gb = selector_periodo("todo", "Periodo de venta")
    d_p, h_p = periodo_pedidos(desde, hasta)
    st.caption(f"Pedidos: del **{d_p:%d/%m/%Y}** al **{h_p:%d/%m/%Y}** (hoy incluido), "
               "para que la REP cuente todo lo que sigue en camino. Se cambia en "
               "'Ajustes de tablas y columnas'.")

    partes = []
    if prep["ventas"].lista:
        partes.append("venta")
    if prep["ped_header"].lista and prep["ped_detail"].lista:
        partes.append("pedidos (Evolucion y Detallado)")
    texto = ("Traer " + " y ".join(partes)) if partes else "Nada listo para traer"
    if st.button(texto, type="primary", width="stretch", key="bq_traer_todo",
                 disabled=not partes):
        st.session_state.pop("bq_traza", None)
        avisos = traer(conn, prep, desde, hasta, max_gb)
        st.session_state["bq_avisos"] = avisos
        st.session_state["result"] = None
        st.session_state["excel"] = None
        if not avisos:
            st.rerun()

    for sev, titulo, detalle in st.session_state.get("bq_avisos", []):
        issue_box(sev, titulo, detalle)
    if st.session_state.get("bq_traza"):
        with st.expander("Detalle tecnico"):
            st.code(st.session_state["bq_traza"])
    if st.session_state.get("bq_gb"):
        st.caption(f"Ultima consulta: {st.session_state['bq_gb']:.2f} GB leidos de BigQuery.")

    for f in prep.values():
        res = st.session_state["loaded"].get(f.source)
        if res is not None and getattr(res, "_sig", (None,))[0] == "bigquery":
            for nota in res.notes:
                st.caption(f"↳ {nota}")

    with st.expander("Ajustes de tablas y columnas", expanded=bool(problemas)):
        _ajustes(conn, prep)
