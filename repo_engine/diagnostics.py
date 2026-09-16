"""Solo los errores que importan: sin match, duplicados y campos criticos vacios."""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import config as C
from .catalogs import Catalogs
from .readers import build_llave

SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


@dataclass
class Issue:
    code: str
    severity: str                 # error | warn | info
    title: str
    detail: str
    count: int = 0
    sample: pd.DataFrame | None = field(default=None, repr=False)

    @property
    def rank(self) -> int:
        return SEVERITY_ORDER.get(self.severity, 9)


def collect_issues(repo: pd.DataFrame,
                   data: pd.DataFrame,
                   loaded: dict[str, pd.DataFrame],
                   catalogs: Catalogs,
                   stats: dict) -> list[Issue]:
    issues: list[Issue] = []
    cd = loaded.get(C.SRC_CD)

    # 1. SKU sin resolver -----------------------------------------------------
    sin_sku = repo[repo["SKU"] == C.NA_TOKEN]
    if len(sin_sku):
        desde_cd = stats.get("sku_desde_cd", 0)
        desde_dir = stats.get("sku_desde_directorio", 0)
        issues.append(Issue(
            code="sku_sin_match",
            severity="warn" if len(sin_sku) < len(repo) else "error",
            title="SKU sin resolver",
            detail=(
                f"{len(sin_sku):,} de {len(repo):,} filas quedan con #N/A. "
                f"Se resolvieron {desde_cd:,} con el Stock CD del dia y {desde_dir:,} mas "
                f"con el directorio acumulado ({stats.get('sku_cobertura', 0):.0%} de cobertura). "
                "El resto son SKU que hoy no estan en el CD ni tuvieron pedidos en el periodo: "
                "su ID Producto no viene en ninguno de los 5 archivos. El directorio se llena "
                "solo cada semana, o de golpe cargando un maestro de productos."
            ),
            count=len(sin_sku),
            sample=sin_sku[["Marca", "Cod Modelo", "Cod Color", "Talla/Numero",
                            "Modelo", "Color", "Temporada Comercial"]].head(300),
        ))

    # 2. Duplicados de llave --------------------------------------------------
    dup = repo["LLAVE"].duplicated(keep=False)
    if dup.any():
        issues.append(Issue(
            code="llave_duplicada", severity="error",
            title="Llaves duplicadas en el REPO",
            detail="Un mismo Cod Modelo-Cod Color-Talla aparece en mas de una fila.",
            count=int(dup.sum()),
            sample=repo.loc[dup, ["Marca", "Cod Modelo", "Cod Color", "Talla/Numero", "Modelo"]].head(200),
        ))

    if cd is not None:
        dup_cd = cd["LLAVE"].duplicated(keep=False)
        if dup_cd.any():
            issues.append(Issue(
                code="cd_duplicado", severity="warn",
                title="Llaves duplicadas en Stock CD",
                detail="Se conservo la primera aparicion de cada llave, igual que un BUSCARV.",
                count=int(dup_cd.sum()),
                sample=cd.loc[dup_cd, ["Cod. Modelo", "Cod. Color", "Talla/Nro/Curva Tarea",
                                       C.CD_SKU_COLUMN, "Disponible"]].head(200),
            ))

    # 2b. SKU que solo existen en el CD --------------------------------------
    if stats.get("filas_solo_cd"):
        n = int(stats["filas_solo_cd"])
        disp = float(stats.get("disponible_solo_cd", 0.0))
        cols = ["Marca", "Clase", "Cod Modelo", "Cod Color", "Talla/Numero",
                "Modelo", "Color", "Temporada Comercial", "DSP"]
        solo = (repo.loc[repo["_solo_cd"], [c for c in cols if c in repo.columns]].head(300)
                if "_solo_cd" in repo.columns else None)
        issues.append(Issue(
            code="sku_solo_cd", severity="warn",
            title="SKU con stock solo en el CD",
            detail=(
                f"{n:,} SKU tienen unidades en el CD pero ninguna venta ni stock en tienda "
                f"({disp:,.0f} unidades disponibles). Son recepciones nuevas: se agregaron "
                "como fila para que entren a la reposicion, y suelen venir sin Temporada "
                "Comercial asignada."
            ),
            count=n,
            sample=solo,
        ))

    # 3. Campos criticos vacios ----------------------------------------------
    criticos = ["Marca", "Clase", "Cod Modelo", "Cod Color", "Talla/Numero"]
    vacios = repo[criticos].isna().any(axis=1)
    if vacios.any():
        issues.append(Issue(
            code="campos_vacios", severity="error",
            title="Campos criticos vacios",
            detail="Filas sin marca, clase o codigo completo: no se pueden reponer.",
            count=int(vacios.sum()),
            sample=repo.loc[vacios, criticos + ["Modelo"]].head(200),
        ))

    # 4. Tiendas de las fuentes que no estan en el REPO -----------------------
    conocidas = set(catalogs.by_key)
    fuera = (data.loc[~data["_en_repo"], ["_tienda_key", "Nombre Tienda"]]
             .dropna(subset=["_tienda_key"]).drop_duplicates())
    fuera = fuera[~fuera["_tienda_key"].isin(conocidas)]
    if len(fuera):
        movidas = data.loc[~data["_en_repo"]]
        issues.append(Issue(
            code="tienda_fuera_repo", severity="info",
            title="Tiendas fuera del REPO",
            detail=(
                f"{len(fuera)} bodegas/tiendas de los archivos no tienen columna en el REPO "
                f"(CD, ecommerce, POS, tiendas cerradas). Aportan "
                f"{movidas['STK'].sum():,.0f} unidades de stock que no se muestran."
            ),
            count=len(fuera),
            sample=fuera.rename(columns={"_tienda_key": "Codigo", "Nombre Tienda": "Nombre"}),
        ))

    # 5. Tiendas del REPO sin datos ------------------------------------------
    con_datos = set(data.loc[data["_en_repo"], "_tienda_key"].dropna())
    mudas = [t for t in catalogs.tiendas if t.key not in con_datos]
    if mudas:
        issues.append(Issue(
            code="tienda_sin_datos", severity="warn",
            title="Tiendas del REPO sin movimiento",
            detail="Estas tiendas quedaran con todas sus columnas vacias.",
            count=len(mudas),
            sample=pd.DataFrame([{"Codigo": t.cod, "Abrev": t.abrev, "Nombre": t.nombre} for t in mudas]),
        ))

    # 6. Pedidos sin estado ---------------------------------------------------
    det, evo = loaded.get(C.SRC_DETALLADO), loaded.get(C.SRC_EVOLUCION)
    if det is not None and evo is not None:
        pedidos = set(evo["Nro. Pedido"].dropna())
        falta = det[~det["Numero Pedido"].isin(pedidos) & det["_tienda_key"].notna()]
        if len(falta):
            issues.append(Issue(
                code="pedido_sin_estado", severity="warn",
                title="Pedidos a tienda sin estado en Evolucion",
                detail=(
                    f"{falta['Numero Pedido'].nunique():,} pedidos dirigidos a tiendas del REPO "
                    "no aparecen en Evolucion, por lo que no suman a la columna REP."
                ),
                count=int(falta["Numero Pedido"].nunique()),
                sample=(falta.groupby(["Numero Pedido", "Tienda / Cliente"], as_index=False)
                        ["Unid. Pendientes"].sum().head(200)),
            ))

    # 7. Stock negativo -------------------------------------------------------
    neg_cols = [c for c in repo.columns if c.endswith("| STK")]
    if neg_cols:
        neg = (repo[neg_cols].to_numpy(dtype=float) < 0).sum()
        if neg:
            issues.append(Issue(
                code="stock_negativo", severity="warn",
                title="Celdas con stock negativo",
                detail=f"{int(neg):,} combinaciones SKU/tienda con stock negativo (ajustes de inventario).",
                count=int(neg),
            ))

    # 8. Conflictos de descripcion -------------------------------------------
    if stats.get("conflictos_atributos"):
        issues.append(Issue(
            code="conflicto_atributos", severity="info",
            title="SKU con descripcion distinta entre fuentes",
            detail=(
                f"{stats['conflictos_atributos']:,} SKU traen Modelo/Color/Temporada distintos "
                "en venta y en bodega. Se uso la version de Bodega Gestion."
            ),
            count=int(stats["conflictos_atributos"]),
        ))

    issues.sort(key=lambda i: (i.rank, -i.count))
    return issues
