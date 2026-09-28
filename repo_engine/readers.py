"""Lectura y normalizacion de los 5 archivos fuente.

Cada lector devuelve un DataFrame limpio + una lista de notas sobre lo que se
descarto (filas TOTAL, apostrofes, columnas invertidas, etc.).
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C

TEXT_ENCODINGS = ("utf-8-sig", "utf-16", "latin-1")
DELIMITERS = (";", "\t", ",", "|")


@dataclass
class LoadResult:
    source: str
    df: pd.DataFrame
    notes: list[str] = field(default_factory=list)
    rows_raw: int = 0

    @property
    def rows(self) -> int:
        return len(self.df)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _to_bytes(file_obj) -> bytes:
    if isinstance(file_obj, (bytes, bytearray)):
        return bytes(file_obj)
    if hasattr(file_obj, "getvalue"):
        return file_obj.getvalue()
    if hasattr(file_obj, "read"):
        pos = file_obj.tell() if hasattr(file_obj, "tell") else None
        data = file_obj.read()
        if pos is not None:
            file_obj.seek(pos)
        return data
    with open(file_obj, "rb") as fh:
        return fh.read()


def _decode(raw: bytes) -> str:
    for enc in TEXT_ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def _sniff_delimiter(head: str) -> str:
    first = head.splitlines()[0] if head else ""
    counts = {d: first.count(d) for d in DELIMITERS}
    best = max(counts, key=counts.get)
    return best if counts[best] else ";"


def clean_text_series(s: pd.Series) -> pd.Series:
    """Quita espacios y el apostrofe que Forus antepone para forzar texto."""
    out = s.astype("string").str.strip()
    out = out.str.replace(r"^'+", "", regex=True)
    out = out.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "NaN": pd.NA})
    return out


def normalize_pedido(s: pd.Series) -> pd.Series:
    """Numero de pedido comparable entre EVOLUCION y DETALLADO.

    Un export lo trae como texto (`'0001068125`) y el otro como numero
    (`1068125.0`); sin esto el cruce por pedido falla en silencio y lo ya
    enviado no suma ni al STK ni a la hoja EN CAMINO.
    """
    out = clean_text_series(s)
    out = out.str.replace(r"\.0+$", "", regex=True)
    digitos = out.str.fullmatch(r"\d+", na=False)
    out = out.mask(digitos, out.str.lstrip("0").replace("", "0"))
    return out.str.upper()


def extract_store_code(s: pd.Series) -> pd.Series:
    """`008 HP JOCKEY`, `008-HP JOCKEY` o `8` -> `8`.

    Los clientes mayoristas traen RUC de 11-12 digitos y quedan sin tienda.
    """
    from .catalogs import normalize_store_code
    cod = s.astype("string").str.extract(r"^\s*(\d{1,4})(?:\.0)?(?!\d)")[0]
    return cod.map(lambda v: normalize_store_code(v) if pd.notna(v) else pd.NA)


def to_num(s: pd.Series) -> pd.Series:
    """Convierte a numero tolerando separadores de miles y comas decimales."""
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce")
    txt = s.astype("string").str.strip()
    txt = txt.str.replace(r"[\s ]", "", regex=True)
    # 1.234,56 -> 1234.56 ; 1,234.56 -> 1234.56
    both = txt.str.contains(",", na=False) & txt.str.contains(r"\.", na=False)
    txt = txt.mask(both, txt.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    only_comma = txt.str.contains(",", na=False) & ~txt.str.contains(r"\.", na=False)
    txt = txt.mask(only_comma, txt.str.replace(",", ".", regex=False))
    return pd.to_numeric(txt, errors="coerce")


def _drop_total_rows(df: pd.DataFrame, notes: list[str]) -> pd.DataFrame:
    """Los exports de Forus terminan con una fila TOTAL que hay que eliminar."""
    if df.empty:
        return df
    probe_cols = [c for c in ("Clase", "Marca", "Nro. Pedido", "Numero Pedido") if c in df.columns]
    if not probe_cols:
        probe_cols = [df.columns[0]]
    mask = pd.Series(False, index=df.index)
    for col in probe_cols:
        vals = df[col].astype("string").str.strip().str.upper()
        mask |= vals.isin(C.TOTAL_ROW_TOKENS)
    if mask.any():
        notes.append(f"Se descarto {int(mask.sum())} fila(s) de totales del export.")
        df = df.loc[~mask]
    return df


def _normalize_headers(df: pd.DataFrame) -> pd.DataFrame:
    df = df.loc[:, [c for c in df.columns if not str(c).startswith("Unnamed")]]
    df.columns = [re.sub(r"\s+", " ", str(c)).strip() for c in df.columns]
    return df.loc[:, ~pd.Index(df.columns).duplicated()]


# ---------------------------------------------------------------------------
# lectores genericos
# ---------------------------------------------------------------------------

def _read_excel(raw: bytes, xlsb: bool = False) -> pd.DataFrame:
    """Excel como texto. Calamine (Rust) lee 5-10x mas rapido que openpyxl."""
    engines = ["calamine"] + (["pyxlsb"] if xlsb else ["openpyxl"])
    ultimo = None
    for engine in engines:
        try:
            return pd.read_excel(io.BytesIO(raw), dtype=str, engine=engine)
        except (ImportError, ValueError) as exc:
            ultimo = exc
    raise ultimo


def read_any(file_obj, filename: str = "") -> pd.DataFrame:
    """Lee txt/csv/xlsx/xlsb devolviendo todo como texto."""
    name = (filename or getattr(file_obj, "name", "") or "").lower()
    raw = _to_bytes(file_obj)
    if name.endswith((".txt", ".csv", ".tsv")):
        text = _decode(raw)
        sep = _sniff_delimiter(text[:8000])
        # Con el separador ya detectado, el motor C lee ~10x mas rapido que el de Python.
        try:
            df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, engine="c",
                             skip_blank_lines=True, on_bad_lines="skip", quotechar='"')
        except (pd.errors.ParserError, ValueError):
            df = pd.read_csv(io.StringIO(text), sep=sep, dtype=str, engine="python",
                             skip_blank_lines=True, on_bad_lines="skip")
    else:
        df = _read_excel(raw, xlsb=name.endswith(".xlsb"))
    return _normalize_headers(df)


def detect_source(df: pd.DataFrame) -> str | None:
    """Adivina cual de las 5 fuentes es un archivo a partir de sus columnas."""
    cols = set(df.columns)
    for src, fp in C.SOURCE_FINGERPRINTS.items():
        if all(m in cols for m in fp["must"]) and not any(m in cols for m in fp["must_not"]):
            return src
    return None


# ---------------------------------------------------------------------------
# lectores por fuente
# ---------------------------------------------------------------------------

_ATTR_COLS = [
    "Clase", "Marca", "Genero", "Linea", "Temporada", "Estilo", "Vigencia",
    "Tipo Prenda", "Temporada Comercial", "Cod. Modelo", "Modelo",
    "Cod. Color", "Color", "Talla/Numero",
]


def _read_movimiento(file_obj, filename: str, source: str) -> LoadResult:
    """VTA y BODEGA comparten estructura: SKU x tienda."""
    df = read_any(file_obj, filename)
    rows_raw = len(df)
    notes: list[str] = []
    df = _drop_total_rows(df, notes)

    for col in _ATTR_COLS + ["Tienda", "Nombre Tienda", "Codigo Barra"]:
        if col in df.columns:
            df[col] = clean_text_series(df[col])

    for col in ("Unidades", "Stock", "Transito", "Reserva eC.", "Merma", "2da calidad", "Venta"):
        if col in df.columns:
            df[col] = to_num(df[col]).fillna(0)
        else:
            df[col] = 0.0

    df["_tienda_key"] = df["Tienda"].map(_norm_code) if "Tienda" in df.columns else pd.NA

    # En BODEGA GESTION las filas del CD vienen con "Nombre Tienda" vacio.
    if source == C.SRC_BODEGA:
        blank = df["Nombre Tienda"].isna() if "Nombre Tienda" in df.columns else pd.Series(False, index=df.index)
        is_cd = blank & (df["_tienda_key"] == C.CD_TIENDA_CODE)
        if is_cd.any():
            df.loc[is_cd, "Nombre Tienda"] = C.CD_TIENDA_NOMBRE
            notes.append(
                f"{int(is_cd.sum())} filas del CD (Tienda {C.CD_TIENDA_CODE}) venian sin "
                f"nombre de tienda; se etiquetaron como {C.CD_TIENDA_NOMBRE}."
            )
        huerfanas = blank & ~is_cd
        if huerfanas.any():
            notes.append(f"{int(huerfanas.sum())} filas sin tienda identificable fueron ignoradas.")
            df = df.loc[~huerfanas]

    return LoadResult(source=source, df=df.reset_index(drop=True), notes=notes, rows_raw=rows_raw)


def _norm_code(value) -> str:
    from .catalogs import normalize_store_code
    return normalize_store_code(value)


def read_vta(file_obj, filename: str = "") -> LoadResult:
    return _read_movimiento(file_obj, filename, C.SRC_VTA)


def read_bodega(file_obj, filename: str = "") -> LoadResult:
    return _read_movimiento(file_obj, filename, C.SRC_BODEGA)


def read_cd(file_obj, filename: str = "") -> LoadResult:
    df = read_any(file_obj, filename)
    rows_raw = len(df)
    notes: list[str] = []
    df = _drop_total_rows(df, notes)

    for col in ("Cod. Modelo", "Cod. Color", "Talla/Nro/Curva Tarea", "Modelo", "Color",
                "Clase", "Marca", "Genero", "Tipo Prenda", "Temporada Comercial"):
        if col in df.columns:
            df[col] = clean_text_series(df[col])

    if C.CD_SKU_COLUMN in df.columns:
        sku = to_num(df[C.CD_SKU_COLUMN])
        df[C.CD_SKU_COLUMN] = sku.map(lambda v: "" if pd.isna(v) else str(int(v)))

    for col in C.CD_LOOKUP_MAP.values():
        if col in df.columns:
            df[col] = to_num(df[col]).fillna(0)
        else:
            df[col] = 0.0
            notes.append(f"El archivo no trae la columna '{col}'; se asumio 0.")

    df["LLAVE"] = build_llave(df["Cod. Modelo"], df["Cod. Color"], df["Talla/Nro/Curva Tarea"])
    dup = df["LLAVE"].duplicated(keep="first")
    if dup.any():
        notes.append(
            f"{int(dup.sum())} llaves duplicadas en Stock CD; se conservo la primera aparicion."
        )
    return LoadResult(source=C.SRC_CD, df=df.reset_index(drop=True), notes=notes, rows_raw=rows_raw)


def read_evolucion(file_obj, filename: str = "") -> LoadResult:
    df = read_any(file_obj, filename)
    rows_raw = len(df)
    notes: list[str] = []
    df = _drop_total_rows(df, notes)

    df["Nro. Pedido"] = normalize_pedido(df["Nro. Pedido"])
    for col in ("Estado", "Clasificacion", "Destino", "Canal", "Bodega origen"):
        if col in df.columns:
            df[col] = clean_text_series(df[col])
    for col in ("Unid. Pedidas", "Unid. Despachadas", "Unid. Pendientes", "Fill Rate"):
        if col in df.columns:
            df[col] = to_num(df[col]).fillna(0)

    # El export invierte Despachadas <-> Pendientes. Se detecta con el Fill Rate.
    if "Fill Rate" in df.columns:
        ped = df["Unid. Pedidas"].replace(0, np.nan)
        as_is = ((df["Unid. Despachadas"] / ped).round(2) == df["Fill Rate"].round(2)).sum()
        swapped = ((df["Unid. Pendientes"] / ped).round(2) == df["Fill Rate"].round(2)).sum()
        if swapped > as_is:
            df[["Unid. Despachadas", "Unid. Pendientes"]] = df[
                ["Unid. Pendientes", "Unid. Despachadas"]
            ].values
            notes.append(
                "Se corrigio el encabezado invertido del export: 'Unid. Despachadas' y "
                "'Unid. Pendientes' venian intercambiadas (verificado contra Fill Rate)."
            )

    dup = df["Nro. Pedido"].duplicated(keep="first")
    if dup.any():
        notes.append(f"{int(dup.sum())} pedidos repetidos en Evolucion; se uso el primer estado.")
    return LoadResult(source=C.SRC_EVOLUCION, df=df.reset_index(drop=True), notes=notes, rows_raw=rows_raw)


def read_detallado(file_obj, filename: str = "") -> LoadResult:
    df = read_any(file_obj, filename)
    rows_raw = len(df)
    notes: list[str] = []
    df = _drop_total_rows(df, notes)

    df["Numero Pedido"] = normalize_pedido(df["Numero Pedido"])
    for col in ("Tienda / Cliente", "Cod. Modelo", "Cod. Color",
                "Talla / Numero", "Clasificacion", "Modelo", "Color", "Clase", "Marca"):
        if col in df.columns:
            df[col] = clean_text_series(df[col])
    for col in ("Unid. Pedidas", "Unid. Pendientes", "Unid. Despachadas"):
        df[col] = to_num(df[col]).fillna(0)

    df["LLAVE"] = build_llave(df["Cod. Modelo"], df["Cod. Color"], df["Talla / Numero"])
    # "008 HP JOCKEY" -> codigo 8 ; los clientes mayoristas traen RUC de 11-12 digitos.
    df["_tienda_key"] = extract_store_code(df["Tienda / Cliente"])
    sin_tienda = df["_tienda_key"].isna().sum()
    if sin_tienda:
        notes.append(
            f"{int(sin_tienda)} filas corresponden a clientes wholesale / sin codigo de tienda "
            "y no aportan a las columnas por tienda."
        )
    return LoadResult(source=C.SRC_DETALLADO, df=df.reset_index(drop=True), notes=notes, rows_raw=rows_raw)


READERS = {
    C.SRC_VTA: read_vta,
    C.SRC_BODEGA: read_bodega,
    C.SRC_CD: read_cd,
    C.SRC_EVOLUCION: read_evolucion,
    C.SRC_DETALLADO: read_detallado,
}


def read_source(source: str, file_obj, filename: str = "") -> LoadResult:
    return READERS[source](file_obj, filename)


# ---------------------------------------------------------------------------
# llave de producto
# ---------------------------------------------------------------------------

def build_llave(cod_modelo, cod_color, talla) -> pd.Series:
    """LLAVE = Cod. Modelo + '-' + Cod. Color + '-' + Talla.

    Es exactamente la formula de la columna LLAVE de la hoja DATA de la
    plantilla (validada contra 137.618 filas sin una sola diferencia).
    """
    def part(s):
        return pd.Series(s).astype("string").fillna("").str.strip().str.replace(r"^'+", "", regex=True)

    return part(cod_modelo) + "-" + part(cod_color) + "-" + part(talla)
