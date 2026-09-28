"""Motor de cruces: de los 5 archivos fuente a la Tabla de Repo Final.

Reproduce, en pandas, la cadena que hoy se arma a mano en Excel:

    VTA + BODEGA GESTION            -> hoja DATA (formato largo, SKU x tienda)
    DATA  (tabla dinamica)          -> hoja DINAMICA (SKU en filas, tiendas en columnas)
    + STOCK CD (BUSCARX por LLAVE)  -> SKU / ECOM / RT / WS / MM / DSP / NVO DSP CD
    + lista de traspasos            -> TRASPASOS DE TEMPORADA
    + EVOLUCION x DETALLADO         -> columna REP por tienda
    = hoja REPO
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C
from .catalogs import Catalogs, load_catalogs, normalize_store_code
from .readers import build_llave

ATTR_SOURCES = {
    "Marca": "Marca",
    "Clase": "Clase",
    "Genero": "Genero",
    "Tipo Prenda": "Tipo Prenda",
    "Modelo": "Modelo",
    "Color": "Color",
    "Cod Modelo": "Cod. Modelo",
    "Cod Color": "Cod. Color",
    "Talla/Numero": "Talla/Numero",
    "Temporada Comercial": "Temporada Comercial",
}


#: Los mismos atributos, leidos desde STOCK CD (ahi la talla cambia de nombre).
CD_ATTR_SOURCES = dict(ATTR_SOURCES, **{"Talla/Numero": "Talla/Nro/Curva Tarea"})


@dataclass
class BuildResult:
    repo: pd.DataFrame                 # 19 columnas fijas + 69*3 columnas de tienda
    data: pd.DataFrame                 # equivalente a la hoja DATA
    catalogs: Catalogs
    stats: dict = field(default_factory=dict)
    issues: list = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    en_camino: pd.DataFrame | None = None   # pedidos que aun no llegan (hoja EN CAMINO)
    cd: pd.DataFrame | None = None          # Stock CD normalizado (hoja CD)
    cuadre: object | None = None            # objeto Cuadre (hoja CUADRE)
    sku_dir: dict | None = None             # directorio LLAVE -> ID Producto (hoja SKUS)


# ---------------------------------------------------------------------------
# 1. hoja DATA
# ---------------------------------------------------------------------------

def build_data(vta: pd.DataFrame, bodega: pd.DataFrame, catalogs: Catalogs | None = None):
    """Apila venta + bodega en el formato largo de la hoja DATA.

    Reglas verificadas contra la plantilla:
      * LLAVE = Cod. Modelo-Cod. Color-Talla/Numero
      * STK   = Stock - Transito          (0 diferencias en 137.618 filas)
      * VNT   = Unidades
      * se excluyen Clase DESPACHOS y Marca OTROS (fletes)
    """
    catalogs = catalogs or load_catalogs()
    notes: list[str] = []
    frames = []

    for origen, df in ((C.SRC_VTA, vta), (C.SRC_BODEGA, bodega)):
        if df is None or df.empty:
            continue
        out = pd.DataFrame(index=df.index)
        for dest, src in ATTR_SOURCES.items():
            out[dest] = df[src] if src in df.columns else pd.NA
        out["LLAVE"] = build_llave(df["Cod. Modelo"], df["Cod. Color"], df["Talla/Numero"])
        out["_tienda_key"] = df["_tienda_key"]
        out["Nombre Tienda"] = df["Nombre Tienda"] if "Nombre Tienda" in df.columns else pd.NA
        out["VNT"] = df["Unidades"].astype(float) if "Unidades" in df.columns else 0.0

        def col(name):
            return df[name].astype(float) if name in df.columns else 0.0

        stock, transito = col("Stock"), col("Transito")
        out["Stock"] = stock
        out["Transito"] = transito
        # Formula literal de la hoja DATA:  AK = Z - AD - AA - AB - AC
        out["STK"] = (stock - transito - col("Reserva eC.")
                      - col("Merma") - col("2da calidad"))
        out["_origen"] = origen
        frames.append(out)

    if not frames:
        raise ValueError("No hay filas de venta ni de bodega para procesar.")

    data = pd.concat(frames, ignore_index=True)

    # --- exclusiones de la plantilla -------------------------------------
    clase = data["Clase"].astype("string").str.upper()
    marca = data["Marca"].astype("string").str.upper()
    fuera = clase.isin(C.EXCLUDED_CLASES) | marca.isin(C.EXCLUDED_MARCAS)
    if fuera.any():
        notes.append(
            f"Se excluyeron {int(fuera.sum()):,} filas de Clase DESPACHOS / Marca OTROS "
            "(fletes), igual que la plantilla."
        )
        data = data.loc[~fuera]

    sin_llave = data["LLAVE"].isin(["--", "-", ""]) | data["Cod Modelo"].isna()
    if sin_llave.any():
        notes.append(f"Se ignoraron {int(sin_llave.sum()):,} filas sin codigo de modelo.")
        data = data.loc[~sin_llave]

    # --- tiendas del REPO -------------------------------------------------
    validas = set(catalogs.by_key)
    data["_en_repo"] = data["_tienda_key"].isin(validas)

    data["Temporada Comercial"] = data["Temporada Comercial"].fillna(C.BLANK_LABEL)
    return data.reset_index(drop=True), notes


# ---------------------------------------------------------------------------
# 2. columna REP (pedidos en camino)
# ---------------------------------------------------------------------------

def estado_canonico(valor):
    """`APROBADO`, `aprobado` o `Aprobada` cuentan como Aprobado; igual Despachado.

    El Excel trae `Aprobado`/`Despachado`, pero la tabla del ERP puede traerlo
    en mayusculas o con otra terminacion; comparado tal cual, ningun pedido
    coincidia y la REP quedaba en cero.
    """
    if pd.isna(valor):
        return pd.NA
    import unicodedata
    txt = unicodedata.normalize("NFKD", str(valor)).encode("ascii", "ignore").decode()
    txt = txt.strip().upper()
    if txt.startswith("APROB"):
        return "Aprobado"
    if txt.startswith(("DESPACH", "EXPED", "EN TRANSITO", "TRANSITO", "EN CAMINO",
                       "ENVIAD")):
        return "Despachado"
    return str(valor).strip()


def nro_pedido(serie: pd.Series) -> pd.Series:
    """Numero de pedido comparable entre Evolucion y Detallado.

    Un export lo trae como `123456` y otro como `123456.0` o `0123456`; sin
    normalizar, el pedido no cruza y se queda sin estado.
    """
    txt = serie.astype("string").str.strip().str.replace(r"^'+", "", regex=True)
    txt = txt.str.replace(r"\.0+$", "", regex=True)
    return txt.where(~txt.str.fullmatch(r"\d+", na=False), txt.str.lstrip("0"))


def _corrige_invertidas(det: pd.DataFrame, evo: pd.DataFrame, notes: list[str]) -> pd.DataFrame:
    """El Detallado puede traer Despachadas y Pendientes intercambiadas.

    Es el mismo error de encabezado que tiene el export de Evolucion. Se
    detecta sumando cada pedido en el Detallado y comparando contra las
    despachadas de la Evolucion (ya corregida por su Fill Rate): si coinciden
    mas pedidos con las pendientes que con las despachadas, estan cruzadas.
    """
    if "Unid. Despachadas" not in evo.columns:
        return det
    ref = (evo.assign(_k=nro_pedido(evo["Nro. Pedido"]))
           .drop_duplicates("_k").set_index("_k")["Unid. Despachadas"])
    suma = det.groupby("_k")[["Unid. Despachadas", "Unid. Pendientes"]].sum()
    suma = suma.join(ref.rename("_ref"), how="inner")
    suma = suma[(suma["_ref"] > 0)]
    if suma.empty:
        return det
    tal_cual = (suma["Unid. Despachadas"].round() == suma["_ref"].round()).sum()
    cruzado = (suma["Unid. Pendientes"].round() == suma["_ref"].round()).sum()
    if cruzado > tal_cual:
        det[["Unid. Despachadas", "Unid. Pendientes"]] = det[
            ["Unid. Pendientes", "Unid. Despachadas"]].values
        notes.append("El Detallado traia 'Unid. Despachadas' y 'Unid. Pendientes' "
                     "intercambiadas (verificado contra la Evolucion); se corrigio.")
    return det


def build_rep_matrix(detallado: pd.DataFrame,
                     evolucion: pd.DataFrame,
                     mode: str = C.DEFAULT_REP_MODE,
                     bodega: pd.DataFrame | None = None,
                     catalogs: Catalogs | None = None):
    """Unidades pedidas al CD que todavia no llegaron a cada tienda.

    Devuelve un DataFrame largo (LLAVE, _tienda_key, REP) + notas.
    """
    catalogs = catalogs or load_catalogs()
    notes: list[str] = []
    empty = pd.DataFrame(columns=["LLAVE", "_tienda_key", "REP"])

    if mode == "transito_bodega":
        if bodega is None or bodega.empty:
            return empty, ["No hay archivo de bodega para calcular el transito."]
        out = pd.DataFrame({
            "LLAVE": build_llave(bodega["Cod. Modelo"], bodega["Cod. Color"], bodega["Talla/Numero"]),
            "_tienda_key": bodega["_tienda_key"],
            "REP": bodega["Transito"].astype(float),
        })
        out = out[out["REP"] != 0]
        notes.append("REP tomado de la columna Transito de Bodega Gestion.")
        return out.groupby(["LLAVE", "_tienda_key"], as_index=False)["REP"].sum(), notes

    if detallado is None or detallado.empty:
        return empty, ["Sin archivo de Detallado de pedidos: REP queda en 0."]

    det = detallado.copy()
    det["_k"] = nro_pedido(det["Numero Pedido"])
    if evolucion is not None and not evolucion.empty:
        det = _corrige_invertidas(det, evolucion, notes)
        estado = (evolucion.assign(_k=nro_pedido(evolucion["Nro. Pedido"]))
                  .drop_duplicates("_k").set_index("_k")["Estado"])
        det["_estado"] = det["_k"].map(estado).map(estado_canonico)
        a_tiendas = det[det["_tienda_key"].isin(set(catalogs.by_key))]
        cuenta = (a_tiendas.drop_duplicates("_k")["_estado"].fillna("(sin estado)")
                  .value_counts())
        notes.append("Pedidos a tiendas del REPO por estado: " + " · ".join(
            f"{k} {v:,}" for k, v in cuenta.items()) +
            ". Solo Aprobado y Despachado suman a la REP.")
    else:
        det["_estado"] = pd.NA
        notes.append("Sin Evolucion: no se pudo filtrar por estado de pedido.")

    # Un pedido despachado HOY suele seguir "Aprobado" hasta que el ERP cambia
    # el estado: lo que ya salio del CD esta en Unid. Despachadas aunque el
    # estado no lo diga. Antes solo se contaban sus pendientes y lo despachado
    # hoy desaparecia de la REP.
    if mode == "despachado_no_recibido":
        # Todo lo que ya salio del CD y no se recibio, diga el estado lo que diga.
        mask = det["_estado"].isin(C.ESTADOS_EN_CAMINO) & (det["Unid. Despachadas"] > 0)
        valor = det["Unid. Despachadas"]
    else:  # pendiente_recepcion
        mask = det["_estado"].isin(C.ESTADOS_EN_CAMINO)
        # Aprobado   -> nada se recibio: lo pendiente en el CD + lo ya despachado.
        # Despachado -> ya salio y no llego: cuenta lo efectivamente despachado.
        valor = (det["Unid. Pendientes"] + det["Unid. Despachadas"]).where(
            det["_estado"].eq("Aprobado"), det["Unid. Despachadas"])

    sub = det.loc[mask & det["_tienda_key"].notna()].copy()
    sub["REP"] = valor.loc[sub.index].astype(float)
    sub = sub[sub["REP"] != 0]

    fuera = ~sub["_tienda_key"].isin(set(catalogs.by_key))
    if fuera.any():
        notes.append(
            f"{int(sub.loc[fuera, 'REP'].sum()):,.0f} unidades en camino van a tiendas que no "
            "estan en el REPO; no se muestran."
        )
        sub = sub.loc[~fuera]

    total = float(sub["REP"].sum())
    notes.append(f"REP: {total:,.0f} unidades en camino en {sub['_tienda_key'].nunique()} tiendas.")
    out = sub.groupby(["LLAVE", "_tienda_key"], as_index=False)["REP"].sum()
    return out, notes


# ---------------------------------------------------------------------------
# 3. hoja REPO
# ---------------------------------------------------------------------------

def _talla_rank(value: str):
    txt = str(value or "").strip().upper()
    if not txt:
        return (3, 0.0, "")
    try:
        return (0, float(txt.replace(",", ".")), "")
    except ValueError:
        pass
    if txt in C.SIZE_RANK:
        return (1, float(C.SIZE_RANK[txt]), "")
    return (2, 0.0, txt)


def _order_rows(df: pd.DataFrame, catalogs: Catalogs) -> pd.DataFrame:
    """Orden estable que reproduce el agrupamiento visual de la dinamica."""
    keys = {}
    for field_name in ("Marca", "Clase", "Genero", "Tipo Prenda"):
        rank = catalogs.rank(field_name)
        big = len(rank) + 1
        vals = df[field_name].astype("string").fillna("")
        keys[f"_r_{field_name}"] = vals.map(lambda v: rank.get(v, big))
        keys[f"_t_{field_name}"] = vals
    tallas = df["Talla/Numero"].map(_talla_rank)
    keys["_talla_a"] = [t[0] for t in tallas]
    keys["_talla_b"] = [t[1] for t in tallas]
    keys["_talla_c"] = [t[2] for t in tallas]
    tmp = df.assign(**keys)
    sort_cols = []
    for field_name in ("Marca", "Clase", "Genero", "Tipo Prenda"):
        sort_cols += [f"_r_{field_name}", f"_t_{field_name}"]
    sort_cols += ["Modelo", "Color", "Cod Modelo", "Cod Color",
                  "_talla_a", "_talla_b", "_talla_c"]
    tmp = tmp.sort_values(sort_cols, kind="mergesort", na_position="last")
    return tmp.drop(columns=[c for c in tmp.columns if c.startswith(("_r_", "_t_", "_talla_"))])


def _filas_solo_cd(cd: pd.DataFrame, llaves: set) -> tuple[pd.DataFrame, list[str]]:
    """Filas para los SKU que hoy solo existen en el CD.

    El universo de la tabla sale de VTA + BODEGA GESTION. Un SKU recien
    recepcionado en el CD todavia no tiene venta ni stock en tienda, asi que
    sin esta fila su disponible queda invisible para la reposicion y el total
    de la tabla no cuadra contra el disponible del CD.
    """
    vacio = pd.DataFrame(columns=["LLAVE"] + list(ATTR_SOURCES))
    if cd is None or cd.empty or "LLAVE" not in cd.columns:
        return vacio, []

    sub = cd.drop_duplicates("LLAVE")
    sub = sub.loc[~sub["LLAVE"].isin(llaves)]
    if sub.empty:
        return vacio, []

    # Solo las que traen unidades: disponible o cualquier reserva distinta de 0.
    unidades = pd.Series(0.0, index=sub.index)
    for col in C.CD_LOOKUP_MAP.values():
        if col in sub.columns:
            unidades = unidades + pd.to_numeric(sub[col], errors="coerce").fillna(0.0)
    sub = sub.loc[unidades != 0]
    if sub.empty:
        return vacio, []

    # Las mismas exclusiones que la hoja DATA.
    def texto(col):
        return (sub[col].astype("string").str.upper() if col in sub.columns
                else pd.Series(pd.NA, index=sub.index, dtype="string"))

    fuera = texto("Clase").isin(C.EXCLUDED_CLASES) | texto("Marca").isin(C.EXCLUDED_MARCAS)
    fuera = fuera.fillna(False) | sub["LLAVE"].isin(["--", "-", ""])
    if "Cod. Modelo" in sub.columns:
        fuera = fuera | sub["Cod. Modelo"].isna()
    sub = sub.loc[~fuera]
    if sub.empty:
        return vacio, []

    out = pd.DataFrame(index=sub.index)
    for dest, src in CD_ATTR_SOURCES.items():
        out[dest] = sub[src] if src in sub.columns else pd.NA
    out["LLAVE"] = sub["LLAVE"]
    out["Temporada Comercial"] = (out["Temporada Comercial"].astype("string")
                                  .replace("", pd.NA).fillna(C.BLANK_LABEL))

    dsp = C.CD_LOOKUP_MAP["DSP"]
    disponible = float(pd.to_numeric(sub[dsp], errors="coerce").fillna(0).sum()) if dsp in sub else 0.0
    notes = [
        f"{len(out):,} SKU del Stock CD no tienen venta ni stock en tienda "
        f"({disponible:,.0f} unidades disponibles). Se agregaron como fila para que "
        "su disponible no quede fuera de la reposicion."
    ]
    return out.reset_index(drop=True)[["LLAVE"] + list(ATTR_SOURCES)], notes


#: Atributos del Detallado de pedidos, con sus nombres de columna.
DET_ATTR_SOURCES = dict(ATTR_SOURCES, **{"Talla/Numero": "Talla / Numero"})


def sumar_en_camino(data: pd.DataFrame, en_camino: pd.DataFrame,
                    detallado: pd.DataFrame | None) -> pd.DataFrame:
    """Suma al STK de cada tienda lo que ya viene en camino.

    Un pedido Aprobado o Despachado todavia no figura en el stock de la tienda
    (el archivo de bodega solo lo cuenta al recepcionar), y sin esto la tabla
    mostraba la tienda sin stock y el planner le volvia a reponer lo mismo.
    Se agrega como filas propias de la hoja DATA (`_origen = en_camino`) para
    que quede auditable. Al recepcionarse, el pedido pasa a Recepcionado, sale
    del calculo y entra por el archivo de bodega: no se cuenta dos veces.
    """
    if en_camino is None or en_camino.empty:
        return data
    filas = en_camino[["LLAVE", "_tienda_key", "REP"]].copy()
    if detallado is not None and not detallado.empty:
        attrs = pd.DataFrame({dest: detallado[src] if src in detallado.columns else pd.NA
                              for dest, src in DET_ATTR_SOURCES.items()})
        attrs["LLAVE"] = detallado["LLAVE"]
        attrs = attrs.drop_duplicates("LLAVE").set_index("LLAVE")
        for dest in ATTR_SOURCES:
            filas[dest] = filas["LLAVE"].map(attrs[dest])
    else:
        for dest in ATTR_SOURCES:
            filas[dest] = pd.NA
    filas["Temporada Comercial"] = (filas["Temporada Comercial"].astype("string")
                                    .fillna(C.BLANK_LABEL))
    filas["Nombre Tienda"] = pd.NA
    filas["VNT"] = 0.0
    filas["Stock"] = 0.0
    filas["Transito"] = 0.0
    filas["STK"] = filas.pop("REP").astype(float)
    filas["_origen"] = "en_camino"
    filas["_en_repo"] = True
    return pd.concat([data, filas[[c for c in data.columns if c in filas.columns]]],
                     ignore_index=True)


def build_repo(data: pd.DataFrame,
               cd: pd.DataFrame,
               rep_long: pd.DataFrame | None = None,
               catalogs: Catalogs | None = None,
               sku_dir: dict[str, str] | None = None) -> tuple[pd.DataFrame, dict, list[str]]:
    catalogs = catalogs or load_catalogs()
    notes: list[str] = []
    stats: dict = {}

    # -- atributos por LLAVE (bodega manda por ser la foto mas reciente) ----
    prio = data["_origen"].map({C.SRC_BODEGA: 0, C.SRC_VTA: 1}).fillna(2)
    ordered = data.assign(_prio=prio).sort_values("_prio", kind="mergesort")
    attrs = ordered.groupby("LLAVE", sort=False)[list(ATTR_SOURCES)].first()

    conflictos = (ordered.groupby("LLAVE")[["Modelo", "Color", "Temporada Comercial"]]
                  .nunique().max(axis=1))
    n_conf = int((conflictos > 1).sum())
    if n_conf:
        notes.append(
            f"{n_conf:,} SKU traen descripciones distintas entre venta y bodega; "
            "se uso la version de Bodega Gestion."
        )
    stats["conflictos_atributos"] = n_conf

    repo = attrs.reset_index()

    # -- SKU que hoy solo estan en el CD -----------------------------------
    solo_cd, n_cd = _filas_solo_cd(cd, set(repo["LLAVE"]))
    notes += n_cd
    stats["filas_solo_cd"] = len(solo_cd)
    repo["_solo_cd"] = False
    if len(solo_cd):
        repo = pd.concat([repo, solo_cd.assign(_solo_cd=True)], ignore_index=True)

    # -- BUSCARX contra STOCK CD -------------------------------------------
    cd_idx = cd.drop_duplicates("LLAVE").set_index("LLAVE")
    sku_map = cd_idx[C.CD_SKU_COLUMN].astype("string")
    repo["SKU"] = repo["LLAVE"].map(sku_map)
    stats["sku_desde_cd"] = int(repo["SKU"].notna().sum())

    # Respaldo: directorio acumulado de ID Producto (hoja SKUS del libro).
    repo["_sku_en_cd"] = repo["SKU"].notna()
    if sku_dir:
        respaldo = repo["LLAVE"].map(sku_dir)
        repo["SKU"] = repo["SKU"].fillna(respaldo)
    stats["sku_desde_directorio"] = int(repo["SKU"].notna().sum() - stats["sku_desde_cd"])

    sin_sku = repo["SKU"].isna()
    stats["sku_sin_match"] = int(sin_sku.sum())
    stats["sku_cobertura"] = float(1 - sin_sku.mean()) if len(repo) else 0.0
    repo["SKU"] = repo["SKU"].fillna(C.NA_TOKEN)

    for dest, src in C.CD_LOOKUP_MAP.items():
        repo[dest] = repo["LLAVE"].map(cd_idx[src]).fillna(0.0).astype(float)

    if stats.get("filas_solo_cd"):
        stats["disponible_solo_cd"] = float(repo.loc[repo["_solo_cd"], "DSP"].sum())

    # NVO DSP CD replica el disponible del CD (en la plantilla es DSP pegado).
    repo["NVO DSP CD"] = repo["DSP"]
    repo["REPOSICIÓN"] = 0.0

    # -- traspasos de temporada -------------------------------------------
    modcol = (repo["Cod Modelo"].astype("string").fillna("").str.strip() + "-" +
              repo["Cod Color"].astype("string").fillna("").str.strip()).str.upper()
    repo["TRASPASOS DE TEMPORADA"] = np.where(modcol.isin(catalogs.traspasos), "T", "-")
    stats["traspasos"] = int((repo["TRASPASOS DE TEMPORADA"] == "T").sum())

    # -- pivote por tienda --------------------------------------------------
    en_repo = data.loc[data["_en_repo"]]
    pv = en_repo.pivot_table(index="LLAVE", columns="_tienda_key",
                             values=["VNT", "STK"], aggfunc="sum")

    rep_pv = None
    if rep_long is not None and not rep_long.empty:
        rep_pv = rep_long.pivot_table(index="LLAVE", columns="_tienda_key",
                                      values="REP", aggfunc="sum")
        huerfanas = set(rep_long["LLAVE"]) - set(repo["LLAVE"])
        if huerfanas:
            perdidas = rep_long.loc[rep_long["LLAVE"].isin(huerfanas), "REP"].sum()
            notes.append(
                f"{len(huerfanas):,} SKU con pedidos en camino no tienen stock ni venta en "
                f"ninguna tienda ({perdidas:,.0f} unidades) y por eso no aparecen como fila."
            )
            stats["rep_sin_fila"] = len(huerfanas)

    llaves = repo["LLAVE"]
    columnas = {}
    for tienda in catalogs.tiendas:
        k = tienda.key
        for metric, frame in ((" VNT", pv.get("VNT")), (" STK", pv.get("STK"))):
            serie = frame[k] if frame is not None and k in frame.columns else None
            columnas[f"{tienda.abrev}|{metric}"] = (
                llaves.map(serie) if serie is not None else pd.Series(np.nan, index=repo.index)
            )
        serie = rep_pv[k] if rep_pv is not None and k in rep_pv.columns else None
        columnas[f"{tienda.abrev}| REP"] = (
            llaves.map(serie) if serie is not None else pd.Series(np.nan, index=repo.index)
        )

    repo = pd.concat([repo, pd.DataFrame(columnas, index=repo.index)], axis=1)

    # -- orden final de filas y columnas ------------------------------------
    repo = _order_rows(repo, catalogs)
    ordered_cols = list(C.FIXED_COLUMNS) + [
        f"{t.abrev}|{m}" for t in catalogs.tiendas for m in C.STORE_METRICS
    ]
    repo = repo.reindex(columns=ordered_cols + ["LLAVE", "_sku_en_cd", "_solo_cd"]).reset_index(drop=True)
    repo["_sku_en_cd"] = repo["_sku_en_cd"].fillna(False).astype(bool)
    repo["_solo_cd"] = repo["_solo_cd"].fillna(False).astype(bool)

    stats["filas"] = len(repo)
    stats["tiendas"] = len(catalogs.tiendas)
    stats["unidades_vnt"] = float(np.nansum(repo[[c for c in repo.columns if c.endswith("| VNT")]].to_numpy(dtype=float)))
    stats["unidades_stk"] = float(np.nansum(repo[[c for c in repo.columns if c.endswith("| STK")]].to_numpy(dtype=float)))
    stats["unidades_rep"] = float(np.nansum(repo[[c for c in repo.columns if c.endswith("| REP")]].to_numpy(dtype=float)))
    return repo, stats, notes


# ---------------------------------------------------------------------------
# orquestador
# ---------------------------------------------------------------------------

def build(loaded: dict[str, pd.DataFrame],
          rep_mode: str = C.DEFAULT_REP_MODE,
          sku_dir: dict[str, str] | None = None) -> BuildResult:
    from .diagnostics import collect_issues
    from .reconcile import build_cuadre
    from . import sku_directory

    catalogs = load_catalogs()
    notes: list[str] = []

    # El directorio de SKU se alimenta con lo que traen los archivos de hoy.
    sku_dir, nuevos = sku_directory.harvest(loaded, sku_dir)
    if nuevos:
        notes.append(f"El directorio de SKU sumo {nuevos:,} llaves nuevas "
                     f"(total {len(sku_dir):,}).")

    data, n1 = build_data(loaded[C.SRC_VTA], loaded[C.SRC_BODEGA], catalogs)
    notes += n1

    # El detalle de lo que ya viene en camino se calcula siempre: alimenta la
    # hoja EN CAMINO. Solo entra a las columnas REP si se pidio precargarlas.
    modo_calculo = rep_mode if rep_mode in C.REP_PRELOAD_MODES else "pendiente_recepcion"
    en_camino, n2 = build_rep_matrix(
        loaded.get(C.SRC_DETALLADO), loaded.get(C.SRC_EVOLUCION),
        mode=modo_calculo, bodega=loaded.get(C.SRC_BODEGA), catalogs=catalogs,
    )
    notes += n2

    if rep_mode in C.REP_PRELOAD_MODES:
        rep_long = en_camino
        notes.append("Las columnas REP quedaron precargadas con los pedidos en camino.")
    else:
        rep_long = None
        # Lo Aprobado y Despachado va al STK de la tienda: asi la tabla no le
        # vuelve a reponer lo que ya le esta llegando.
        data = sumar_en_camino(data, en_camino, loaded.get(C.SRC_DETALLADO))
        if not en_camino.empty:
            notes.append(
                f"El STK de cada tienda incluye {en_camino['REP'].sum():,.0f} unidades "
                f"en camino (pedidos Aprobados o Despachados) en "
                f"{en_camino['_tienda_key'].nunique()} tiendas. El detalle esta en la "
                "hoja EN CAMINO.")
        notes.append(
            "Las columnas REP quedaron vacias para que las llenes: REPOSICIÓN suma "
            "lo que escribas y NVO DSP CD descuenta del disponible del CD."
        )

    repo, stats, n3 = build_repo(data, loaded[C.SRC_CD], rep_long, catalogs, sku_dir)
    notes += n3

    issues = collect_issues(repo, data, loaded, catalogs, stats)
    cuadre = build_cuadre(repo, data, loaded, rep_long, catalogs)
    stats["rep_mode"] = rep_mode
    stats["cuadra"] = cuadre.cuadra
    stats["en_camino_total"] = float(en_camino["REP"].sum()) if not en_camino.empty else 0.0
    stats["sku_directorio"] = len(sku_dir)
    return BuildResult(repo=repo, data=data, catalogs=catalogs,
                       stats=stats, issues=issues, notes=notes,
                       en_camino=en_camino, cd=loaded.get(C.SRC_CD), cuadre=cuadre,
                       sku_dir=sku_dir)
