"""Dashboard de pedidos: cabecera + detalle de PeruCentral en un solo frame.

Replica las cifras del reporte de BI:

    Cantidad Pedida      = SUM(unidades pedidas)
    Cantidad Despachada  = SUM(unidades despachadas)
    Var Pedidos          = pedida - despachada
    % Cumplimiento       = despachada / pedida

Todo se calcula sobre el **detalle** (la linea del pedido, que es la que trae
producto y tienda) y se enriquece con los atributos de la **cabecera** (estado,
tipo de pedido, fecha) cruzando por numero de pedido. Agregar por la cabecera
contaria cada pedido una vez en lugar de cada par, y las cifras no calzarian
con el BI.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .catalogs import Catalogs, load_catalogs, normalize_store_code

#: El CD no esta en el maestro de tiendas (no es una tienda de la cadena), pero
#: si es el mayor origen de pedidos: sin nombre propio salia como "(en blanco)"
#: encabezando el ranking.
COD_CD = "320"
CADENA_CD = "BOD 320"
NOMBRE_CD = "BODEGA FORUS 320"

#: Dimensiones que el tablero ofrece como filtro, en el orden del BI.
DIMENSIONES = {
    "tipo_pedido": "Tipo de Pedido",
    "cadena": "Tipo de Cadena",
    "ciudad": "Ciudad",
    "marca": "Marca",
    "tienda": "Tienda",
    "modcol": "Cod Mod Col",
    "tipo_prenda": "Tipo Prenda",
    "estado": "Estado",
}


def _texto(serie: pd.Series) -> pd.Series:
    return (serie.astype("string").str.strip()
            .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "<NA>": pd.NA}))


def _num(frame: pd.DataFrame, col: str) -> pd.Series:
    if col not in frame.columns:
        return pd.Series(0.0, index=frame.index)
    return pd.to_numeric(frame[col], errors="coerce").fillna(0.0)


# ---------------------------------------------------------------------------
# construccion del frame de lineas
# ---------------------------------------------------------------------------

def construir(detalle: pd.DataFrame,
              cabecera: pd.DataFrame | None = None,
              catalogs: Catalogs | None = None) -> tuple[pd.DataFrame, list[str]]:
    """Una fila por linea de pedido, con los atributos de la cabecera pegados.

    Ambos frames vienen con los nombres logicos del mapeo de BigQuery
    (`nro_pedido`, `estado`, `unid_pedidas`, ...), no con los del Excel.
    """
    catalogs = catalogs or load_catalogs()
    notas: list[str] = []
    if detalle is None or detalle.empty:
        return pd.DataFrame(), ["El detalle de pedidos vino vacio."]

    out = pd.DataFrame(index=detalle.index)
    out["nro_pedido"] = _texto(detalle["nro_pedido"])
    out["pedida"] = _num(detalle, "unid_pedidas")
    out["despachada"] = _num(detalle, "unid_despachadas")

    for campo in ("marca", "tipo_prenda", "clase", "modelo", "color", "talla"):
        out[campo] = _texto(detalle[campo]) if campo in detalle.columns else pd.NA

    cod = _texto(detalle["tienda_cod"]) if "tienda_cod" in detalle.columns else None
    nombre = (_texto(detalle["tienda_nombre"]) if "tienda_nombre" in detalle.columns
              else None)
    out["tienda_key"] = (cod.map(lambda v: normalize_store_code(v) if pd.notna(v) else pd.NA)
                         if cod is not None else pd.NA)
    out["tienda"] = nombre if nombre is not None else out["tienda_key"]

    if {"cod_modelo", "cod_color"} <= set(detalle.columns):
        out["modcol"] = (_texto(detalle["cod_modelo"]).fillna("") + "-" +
                         _texto(detalle["cod_color"]).fillna("")).str.strip("-")
        out["modcol"] = out["modcol"].replace({"": pd.NA})
    else:
        out["modcol"] = pd.NA

    # -- atributos de la cabecera ------------------------------------------
    for campo in ("estado", "tipo_pedido", "ciudad", "cadena", "canal"):
        out[campo] = pd.NA
    out["fecha"] = pd.NaT

    if cabecera is not None and not cabecera.empty and "nro_pedido" in cabecera.columns:
        cab = cabecera.drop_duplicates("nro_pedido").copy()
        cab["nro_pedido"] = _texto(cab["nro_pedido"])
        cab = cab.set_index("nro_pedido")
        for campo in ("estado", "tipo_pedido", "ciudad", "cadena", "canal"):
            if campo in cab.columns:
                out[campo] = out["nro_pedido"].map(_texto(cab[campo]))
        if "fecha" in cab.columns:
            out["fecha"] = pd.to_datetime(out["nro_pedido"].map(cab["fecha"]),
                                          errors="coerce")
        sin_cab = out["estado"].isna().sum() if "estado" in cab.columns else 0
        if sin_cab:
            notas.append(
                f"{int(sin_cab):,} lineas no encontraron su pedido en la cabecera: "
                "quedan sin estado ni tipo de pedido.")
    else:
        notas.append("Sin cabecera: no hay estado, tipo de pedido ni fecha.")

    if out["fecha"].isna().all() and "fecha" in detalle.columns:
        out["fecha"] = pd.to_datetime(detalle["fecha"], errors="coerce")

    # -- cadena: del maestro de tiendas, no del tablon ----------------------
    # El codigo de tienda es estable; el nombre de cadena en staging no siempre.
    abrev = {t.key: t.abrev for t in catalogs.tiendas}
    nombres = {t.key: (t.nombre or t.abrev) for t in catalogs.tiendas}
    derivada = out["tienda_key"].map(
        lambda k: CADENA_CD if str(k) == normalize_store_code(COD_CD)
        else (abrev.get(k, "").split(" ")[0] or pd.NA) if pd.notna(k) else pd.NA)
    out["cadena"] = out["cadena"].fillna(pd.Series(derivada, index=out.index))
    clave_cd = normalize_store_code(COD_CD)
    del_nombre = out["tienda_key"].map(
        lambda k: (NOMBRE_CD if str(k) == clave_cd else nombres.get(k, pd.NA))
        if pd.notna(k) else pd.NA)
    out["tienda"] = out["tienda"].fillna(pd.Series(del_nombre, index=out.index))

    out["estado"] = out["estado"].fillna("(sin estado)")
    out["tipo_pedido"] = out["tipo_pedido"].fillna("(sin tipo)")
    notas.append(f"{len(out):,} lineas · {out['nro_pedido'].nunique():,} pedidos.")
    return out.reset_index(drop=True), notas


# ---------------------------------------------------------------------------
# filtros y metricas
# ---------------------------------------------------------------------------

def opciones(df: pd.DataFrame, campo: str) -> list[str]:
    if df.empty or campo not in df.columns:
        return []
    return sorted(str(v) for v in df[campo].dropna().unique())


def filtrar(df: pd.DataFrame, seleccion: dict[str, list[str]]) -> pd.DataFrame:
    """Aplica solo los filtros con algo elegido: vacio = todas, como el BI."""
    out = df
    for campo, valores in (seleccion or {}).items():
        if valores and campo in out.columns:
            out = out[out[campo].astype("string").isin([str(v) for v in valores])]
    return out


def kpis(df: pd.DataFrame) -> dict:
    pedida = float(df["pedida"].sum()) if not df.empty else 0.0
    despachada = float(df["despachada"].sum()) if not df.empty else 0.0
    return {
        "pedida": pedida,
        "despachada": despachada,
        "var": pedida - despachada,
        "cumplimiento": (despachada / pedida * 100) if pedida else 0.0,
        "pedidos": int(df["nro_pedido"].nunique()) if not df.empty else 0,
    }


def por(df: pd.DataFrame, campo: str, top: int | None = None) -> pd.DataFrame:
    """Pedida / despachada / cumplimiento agrupado por una dimension."""
    if df.empty or campo not in df.columns:
        return pd.DataFrame(columns=[campo, "Cantidad Pedida", "Cantidad Despachada",
                                     "Var", "%Cumplimiento"])
    g = (df.groupby(df[campo].fillna("(en blanco)").astype(str), dropna=False)
         [["pedida", "despachada"]].sum().reset_index())
    g.columns = [campo, "Cantidad Pedida", "Cantidad Despachada"]
    g["Var"] = g["Cantidad Pedida"] - g["Cantidad Despachada"]
    g["%Cumplimiento"] = np.where(g["Cantidad Pedida"] > 0,
                                  g["Cantidad Despachada"] / g["Cantidad Pedida"] * 100,
                                  0.0)
    g = g.sort_values("Cantidad Pedida", ascending=False).reset_index(drop=True)
    return g.head(top) if top else g


def matriz_estado(df: pd.DataFrame) -> pd.DataFrame:
    """Tipo de pedido en filas, estado en columnas (el 'Ranking x Estado' del BI)."""
    if df.empty:
        return pd.DataFrame()
    t = pd.pivot_table(df, index="tipo_pedido", columns="estado", values="pedida",
                       aggfunc="sum", fill_value=0)
    t = t.reindex(sorted(t.columns), axis=1)
    t.loc["TOTAL GENERAL"] = t.sum()
    return t.reset_index()


PERIODOS = {"Mes": "M", "Semana": "W", "Dia": "D"}


def por_periodo(df: pd.DataFrame, granularidad: str = "Mes") -> pd.DataFrame:
    """Serie de pedida vs despachada por mes, semana o dia."""
    if df.empty or df["fecha"].isna().all():
        return pd.DataFrame(columns=["periodo", "Cantidad Pedida", "Cantidad Despachada"])
    sub = df.dropna(subset=["fecha"]).copy()
    freq = PERIODOS.get(granularidad, "M")
    if freq == "W":
        sub["periodo"] = sub["fecha"].dt.isocalendar().week.astype(int).map(
            lambda s: f"S{s:02d}")
    elif freq == "D":
        sub["periodo"] = sub["fecha"].dt.strftime("%d/%m")
    else:
        sub["periodo"] = sub["fecha"].dt.strftime("%Y-%m")
    g = (sub.groupby("periodo", as_index=False)[["pedida", "despachada"]].sum()
         .sort_values("periodo"))
    g.columns = ["periodo", "Cantidad Pedida", "Cantidad Despachada"]
    return g.reset_index(drop=True)
