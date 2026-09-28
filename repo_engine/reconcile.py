"""Cuadre: cada unidad de los archivos fuente tiene que aparecer o estar explicada.

La logica es siempre la misma:

    total del archivo  =  lo que entra al REPO  +  lo excluido por regla  +  lo no cruzado

Si esa identidad se cumple, el REPO cuadra. Si sobra o falta algo, aparece en la
fila "Sin explicar", que es la unica que deberia estar en cero siempre.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C
from .catalogs import Catalogs
from .readers import build_llave


@dataclass
class Linea:
    concepto: str
    origen: float          # total del archivo fuente
    en_repo: float         # lo que quedo en la tabla final
    excluido: float        # descartado por una regla conocida
    detalle: str = ""
    cuadra: bool = field(init=False, default=False)
    sin_explicar: float = field(init=False, default=0.0)

    def __post_init__(self):
        self.sin_explicar = round(self.origen - self.en_repo - self.excluido, 6)
        self.cuadra = abs(self.sin_explicar) < 0.5


@dataclass
class Cuadre:
    lineas: list[Linea] = field(default_factory=list)
    desglose: list[dict] = field(default_factory=list)

    @property
    def cuadra(self) -> bool:
        return all(l.cuadra for l in self.lineas)

    def to_frame(self) -> pd.DataFrame:
        return pd.DataFrame([{
            "Concepto": l.concepto,
            "Unidades en el archivo": l.origen,
            "Unidades en el REPO": l.en_repo,
            "Excluidas por regla": l.excluido,
            "Sin explicar": l.sin_explicar,
            "Cuadra": "SI" if l.cuadra else "NO",
            "Detalle": l.detalle,
        } for l in self.lineas])

    def desglose_frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.desglose)


def _sum(df: pd.DataFrame, col: str) -> float:
    if df is None or col not in df.columns:
        return 0.0
    return float(pd.to_numeric(df[col], errors="coerce").fillna(0).sum())


def build_cuadre(repo: pd.DataFrame,
                 data: pd.DataFrame,
                 loaded: dict[str, pd.DataFrame],
                 rep_long: pd.DataFrame | None,
                 catalogs: Catalogs) -> Cuadre:
    cuadre = Cuadre()

    vnt_cols = [c for c in repo.columns if c.endswith("| VNT")]
    stk_cols = [c for c in repo.columns if c.endswith("| STK")]
    rep_cols = [c for c in repo.columns if c.endswith("| REP")]
    repo_vnt = float(np.nansum(repo[vnt_cols].to_numpy(dtype=float))) if vnt_cols else 0.0
    repo_stk = float(np.nansum(repo[stk_cols].to_numpy(dtype=float))) if stk_cols else 0.0
    repo_rep = float(np.nansum(repo[rep_cols].to_numpy(dtype=float))) if rep_cols else 0.0

    # ---------------- venta ----------------
    # Ojo: el export de bodega tambien puede traer unidades vendidas, y la
    # plantilla las suma igual que las del archivo de venta.
    origen_vnt = _sum(loaded.get(C.SRC_VTA), "Unidades") + _sum(loaded.get(C.SRC_BODEGA), "Unidades")
    fuera_vnt = float(data.loc[~data["_en_repo"], "VNT"].sum())
    excl_vnt = origen_vnt - float(data["VNT"].sum())   # DESPACHOS / sin codigo
    cuadre.lineas.append(Linea(
        concepto="Venta (VNT)",
        origen=origen_vnt, en_repo=repo_vnt, excluido=excl_vnt + fuera_vnt,
        detalle=(f"{excl_vnt:,.0f} de Clase DESPACHOS o sin codigo · "
                 f"{fuera_vnt:,.0f} en tiendas sin columna en el REPO"),
    ))

    # ---------------- stock ----------------
    bod = loaded.get(C.SRC_BODEGA)
    if bod is not None and not bod.empty:
        origen_stk = float(
            pd.to_numeric(bod["Stock"], errors="coerce").fillna(0).sum()
            - pd.to_numeric(bod["Transito"], errors="coerce").fillna(0).sum()
            - _sum(bod, "Reserva eC.") - _sum(bod, "Merma") - _sum(bod, "2da calidad")
        )
    else:
        origen_stk = 0.0
    # Lo en camino se suma al STK de la tienda: entra al origen para cuadrar.
    camino_stk = float(data.loc[data["_origen"].eq("en_camino"), "STK"].sum())
    origen_stk += camino_stk
    fuera_stk = float(data.loc[~data["_en_repo"], "STK"].sum())
    excl_stk = origen_stk - float(data["STK"].sum())
    cuadre.lineas.append(Linea(
        concepto="Stock disponible (STK)",
        origen=origen_stk, en_repo=repo_stk, excluido=excl_stk + fuera_stk,
        detalle=(f"incluye {camino_stk:,.0f} en camino · "
                 f"{excl_stk:,.0f} de Clase DESPACHOS o sin codigo · "
                 f"{fuera_stk:,.0f} en el CD 320 y tiendas sin columna en el REPO"),
    ))

    # ---------------- pedidos en camino ----------------
    if rep_long is not None and not rep_long.empty:
        origen_rep = float(rep_long["REP"].sum())
        llaves_repo = set(repo["LLAVE"]) if "LLAVE" in repo.columns else set()
        sin_fila = float(rep_long.loc[~rep_long["LLAVE"].isin(llaves_repo), "REP"].sum())
    else:
        origen_rep, sin_fila = 0.0, 0.0
    cuadre.lineas.append(Linea(
        concepto="Pedidos en camino (REP)",
        origen=origen_rep, en_repo=repo_rep, excluido=sin_fila,
        detalle=f"{sin_fila:,.0f} unidades de SKU sin stock ni venta en ninguna tienda",
    ))

    # ---------------- disponible del CD ----------------
    # Es el control que importa para armar la repo: cada unidad disponible en el
    # CD tiene que estar en una fila de la tabla o estar explicada por una regla.
    cd = loaded.get(C.SRC_CD)
    if cd is not None and not cd.empty and "LLAVE" in cd.columns:
        dsp_col = C.CD_LOOKUP_MAP["DSP"]
        origen_dsp = _sum(cd, dsp_col)
        cd_u = cd.drop_duplicates("LLAVE")
        dup_dsp = origen_dsp - _sum(cd_u, dsp_col)      # BUSCARV se queda con la primera
        llaves_repo = set(repo["LLAVE"]) if "LLAVE" in repo.columns else set()
        sin_fila = cd_u.loc[~cd_u["LLAVE"].isin(llaves_repo)]
        excl_dsp = _sum(sin_fila, dsp_col)
        cuadre.lineas.append(Linea(
            concepto="Disponible en el CD (DSP)",
            origen=origen_dsp, en_repo=_sum(repo, "DSP"), excluido=excl_dsp + dup_dsp,
            detalle=(f"{len(sin_fila):,} llaves del CD sin fila en el REPO "
                     f"({excl_dsp:,.0f} unidades: Clase DESPACHOS, Marca OTROS o sin codigo) · "
                     f"{dup_dsp:,.0f} en llaves duplicadas del CD"),
        ))
        llaves_cd = set(cd_u["LLAVE"])
    else:
        llaves_cd = set()

    # ---------------- filas ----------------
    origen_filas = float(len(set(data["LLAVE"]) | llaves_cd))
    cuadre.lineas.append(Linea(
        concepto="Filas (SKU unicos)",
        origen=origen_filas,
        en_repo=float(len(repo)),
        excluido=origen_filas - len(repo),
        detalle=("Cada LLAVE del periodo, mas las del CD con unidades, "
                 "genera exactamente una fila del REPO"),
    ))

    # ---------------- cobertura de los BUSCARV ----------------
    if cd is not None and "SKU" in repo.columns:
        con_match = int((repo["SKU"] != C.NA_TOKEN).sum())
        cuadre.desglose.append({
            "Cruce": "SKU / reservas contra Stock CD",
            "Llave": "Cod Modelo-Cod Color-Talla",
            "Filas del REPO": len(repo),
            "Con match": con_match,
            "Sin match": len(repo) - con_match,
            "Nota": "Sin match = el SKU no esta hoy en el CD; queda #N/A y las reservas en 0",
        })

    if "TRASPASOS DE TEMPORADA" in repo.columns:
        t = int((repo["TRASPASOS DE TEMPORADA"] == "T").sum())
        cuadre.desglose.append({
            "Cruce": "Traspasos de temporada",
            "Llave": "Cod Modelo-Cod Color",
            "Filas del REPO": len(repo),
            "Con match": t,
            "Sin match": len(repo) - t,
            "Nota": f"{len(catalogs.traspasos)} claves en la lista mantenida en la app",
        })

    det, evo = loaded.get(C.SRC_DETALLADO), loaded.get(C.SRC_EVOLUCION)
    if det is not None and evo is not None:
        pedidos = set(evo["Nro. Pedido"].dropna())
        con = int(det["Numero Pedido"].isin(pedidos).sum())
        cuadre.desglose.append({
            "Cruce": "Detallado contra Evolucion",
            "Llave": "Numero de pedido",
            "Filas del REPO": len(det),
            "Con match": con,
            "Sin match": len(det) - con,
            "Nota": "Sin match = ecommerce y wholesale, que no pasan por reposicion Retail",
        })

    # ---------------- por tienda ----------------
    tiendas = []
    for t in catalogs.tiendas:
        v = repo.get(f"{t.abrev}| VNT")
        s = repo.get(f"{t.abrev}| STK")
        r = repo.get(f"{t.abrev}| REP")
        sub = data[data["_tienda_key"] == t.key]
        tiendas.append({
            "Cod": t.cod, "Tienda": t.abrev, "Nombre": t.nombre,
            "VNT archivo": float(sub["VNT"].sum()),
            "VNT repo": float(np.nansum(v.to_numpy(dtype=float))) if v is not None else 0.0,
            "STK archivo": float(sub["STK"].sum()),
            "STK repo": float(np.nansum(s.to_numpy(dtype=float))) if s is not None else 0.0,
            "REP repo": float(np.nansum(r.to_numpy(dtype=float))) if r is not None else 0.0,
        })
    df = pd.DataFrame(tiendas)
    df["Dif VNT"] = df["VNT repo"] - df["VNT archivo"]
    df["Dif STK"] = df["STK repo"] - df["STK archivo"]
    cuadre.por_tienda = df  # type: ignore[attr-defined]
    return cuadre
