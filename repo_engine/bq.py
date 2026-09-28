"""Lectura de datos desde BigQuery.

Reemplaza la subida manual del archivo de venta: se elige un rango de fechas y
la app trae la venta agregada directamente del datalake.

Comparte el mismo bloque de secrets que el Catalogo Control Center
(`[bigquery]` + `[gcp_service_account]`), asi que no hay que configurar nada
nuevo si ya estaba enganchado.

Dos cuidados de diseno, porque BigQuery cobra por bytes leidos:

* **Todo se filtra por fecha en el WHERE** y se agrega en el servidor
  (`GROUP BY`), de modo que baja solo el resultado, no el tablon.
* Antes de ejecutar se hace un **dry run** que informa cuantos bytes se van a
  leer. La app lo muestra y puede bloquear la consulta si supera un tope.

Como no se conocen de antemano los nombres de columna del tablon, el modulo
**descubre el esquema** (`INFORMATION_SCHEMA.COLUMNS`) y mapea por alias. El
mapeo resuelto se guarda en `data/bq_mapping.json` y se puede corregir desde la
pantalla de conexion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAPPING_PATH = DATA_DIR / "bq_mapping.json"

#: Tabla de venta por defecto (la que indico el area).
#: Las rutas de las tablas viven en los secrets, no aca: este repositorio es
#: publico y un `proyecto.dataset.tabla` describe la infraestructura interna.
#: Vacio significa "no configurado", y la app lo dice en pantalla.
TABLA_VENTAS = ""
#: Maestro de productos, ya usado por el Catalogo Control Center.
TABLA_ARTI = ""

#: Tope de lectura por consulta. Sobre esto, la app avisa y no ejecuta sola.
MAX_GB_POR_DEFECTO = 20.0

#: Campos que la app necesita y los nombres con los que suelen venir.
#: El primer alias que exista en la tabla gana.
ALIAS_VENTAS = {
    "fecha": ["fecha", "fecha_venta", "fec_venta", "fecha_documento", "fecha_comprobante",
              "dia", "fecha_dia", "fec_doc"],
    "tienda_cod": ["cod_tienda", "codigo_tienda", "tienda", "cod_local", "local",
                   "cod_sucursal", "sucursal_codigo", "id_tienda"],
    "tienda_nombre": ["nombre_tienda", "desc_tienda", "tienda_nombre", "local_nombre",
                      "nombre_local", "sucursal", "desc_local", "nombre_sucursal"],
    "unidades": ["unidades", "cantidad", "cant", "qty", "unidades_vendidas",
                 "cantidad_vendida", "und", "cant_venta"],
    "id_producto": ["id_producto", "idproducto", "sku", "cod_producto", "codigo_producto",
                    "codint_ma", "producto_id"],
    "cod_modelo": ["cod_modelo", "codigo_modelo", "modelo_cod", "cod_mod", "estilo_cod"],
    "modelo": ["modelo", "desc_modelo", "nombre_modelo", "descripcion_modelo"],
    "cod_color": ["cod_color", "codigo_color", "color_cod"],
    "color": ["color", "desc_color", "nombre_color", "descripcion_color"],
    "talla": ["talla", "talla_numero", "tallanumero", "size", "cod_talla", "talla_desc"],
    "marca": ["marca", "desc_marca", "nombre_marca"],
    "clase": ["clase", "desc_clase", "categoria"],
    "genero": ["genero", "desc_genero", "sexo"],
    "linea": ["linea", "desc_linea"],
    "temporada": ["temporada", "desc_temporada"],
    "temporada_comercial": ["temporada_comercial", "temp_comercial", "coleccion",
                            "temporada_com"],
    "tipo_prenda": ["tipo_prenda", "tipoprenda", "desc_tipo_prenda", "tipo"],
    "estilo": ["estilo", "desc_estilo"],
    "venta": ["venta", "venta_neta", "importe", "monto", "total_venta", "vta"],
    "barra": ["codigo_barra", "cod_barra", "barra", "ean", "codbarras", "cod_ean"],
}

#: Campos obligatorios para que la consulta tenga sentido.
OBLIGATORIOS = ("fecha", "unidades")
#: Al menos uno de estos para identificar la tienda.
IDENTIFICA_TIENDA = ("tienda_cod", "tienda_nombre")
#: Al menos uno de estos para identificar el producto.
IDENTIFICA_PRODUCTO = ("id_producto", "cod_modelo")


@dataclass
class Conexion:
    ok: bool
    detalle: str
    proyecto: str = ""
    cliente: object = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# configuracion y cliente
# ---------------------------------------------------------------------------

#: Donde puede estar el JSON de la service account. El bloque de siempre es
#: [gcp_service_account] al nivel de arriba, pero es facil que termine anidado
#: dentro de [bigquery] al pegar, o con el nombre de otra convencion.
UBICACIONES_CUENTA = (
    ("gcp_service_account",),
    ("bigquery", "gcp_service_account"),
    ("connections", "gcp_service_account"),
    ("gcp",),
    ("service_account",),
    ("google_service_account",),
)

#: Campos sin los cuales el JSON no sirve para firmar.
CAMPOS_CUENTA = ("client_email", "private_key")


def _busca_cuenta(secrets) -> dict | None:
    """Encuentra el JSON de la service account este donde este."""
    for ruta in UBICACIONES_CUENTA:
        nodo = secrets
        try:
            for paso in ruta:
                if paso not in nodo:
                    nodo = None
                    break
                nodo = nodo[paso]
            if nodo is None:
                continue
            candidato = dict(nodo)
        except Exception:
            continue
        if all(c in candidato for c in CAMPOS_CUENTA):
            return candidato
    return None


def config() -> dict:
    """Lee los secrets. Misma estructura que el Catalogo Control Center."""
    import streamlit as st
    cfg: dict = {}
    try:
        if "bigquery" in st.secrets:
            # La cuenta puede venir anidada aca; no debe contaminar la config.
            cfg.update({k: v for k, v in dict(st.secrets["bigquery"]).items()
                        if k not in ("gcp_service_account", "service_account")})
        cuenta = _busca_cuenta(st.secrets)
        if cuenta:
            cfg["service_account_info"] = cuenta
    except Exception:
        return {}
    crudo = cfg.pop("service_account_json", None)
    if crudo and "service_account_info" not in cfg:
        try:
            cfg["service_account_info"] = json.loads(crudo)
        except json.JSONDecodeError:
            pass
    return cfg


def diagnostico_secrets() -> list[str]:
    """Que bloques y claves ve la app. Solo NOMBRES: ningun valor se muestra."""
    import streamlit as st
    lineas: list[str] = []
    try:
        bloques = sorted(str(k) for k in st.secrets.keys())
    except Exception as exc:
        return [f"No se pudieron leer los secrets: {type(exc).__name__}: {exc}"]
    lineas.append("Bloques encontrados: " + (", ".join(bloques) or "ninguno"))
    try:
        if "bigquery" in st.secrets:
            claves = sorted(str(k) for k in dict(st.secrets["bigquery"]).keys())
            lineas.append("Claves dentro de [bigquery]: " + (", ".join(claves) or "ninguna"))
    except Exception:
        pass
    cuenta = None
    try:
        cuenta = _busca_cuenta(st.secrets)
    except Exception:
        pass
    if cuenta:
        faltan = [c for c in CAMPOS_CUENTA if not str(cuenta.get(c, "")).strip()]
        lineas.append("Service account: encontrada" +
                      (f", pero sin {', '.join(faltan)}" if faltan else
                       f" ({len(cuenta)} campos, client_email y private_key presentes)"))
    else:
        lineas.append(
            "Service account: NO encontrada. Se busco como [gcp_service_account], "
            "dentro de [bigquery], y bajo [connections]. Tiene que traer al menos "
            "client_email y private_key.")
    return lineas


def disponible(cfg: dict | None = None) -> bool:
    cfg = config() if cfg is None else cfg
    if not cfg:
        return False
    if str(cfg.get("enabled", "true")).strip().lower() in ("0", "false", "no", "off"):
        return False
    cuenta = cfg.get("service_account_info")
    proyecto = str(cfg.get("project_id", "")).strip()
    if isinstance(cuenta, dict):
        proyecto = proyecto or str(cuenta.get("project_id", "")).strip()
    return bool(proyecto)


def cliente(cfg: dict | None = None) -> Conexion:
    cfg = config() if cfg is None else cfg
    if not disponible(cfg):
        return Conexion(False, "BigQuery no esta configurado en los secrets.")
    try:
        from google.cloud import bigquery
        from google.oauth2 import service_account
    except ImportError:
        return Conexion(False, "Falta instalar google-cloud-bigquery y google-auth.")
    try:
        proyecto = str(cfg.get("project_id", "")).strip()
        credenciales = None
        info = cfg.get("service_account_info")
        if not info:
            # Sin credenciales explicitas, la libreria intenta las del entorno y
            # sale a buscar el servidor de metadatos de Compute Engine, que en
            # Streamlit no existe. El error que devuelve no menciona los secrets.
            return Conexion(False,
                            "Falta el bloque [gcp_service_account] en los secrets. "
                            "Sin el, la app intenta autenticarse como si corriera "
                            "dentro de Google Cloud y falla buscando el servidor de "
                            "metadatos. Pega el JSON de la service account completo, "
                            "junto al bloque [bigquery].")
        credenciales = service_account.Credentials.from_service_account_info(dict(info))
        proyecto = proyecto or credenciales.project_id
        job_proyecto = str(cfg.get("job_project_id", "")).strip() or proyecto
        cli = bigquery.Client(project=job_proyecto or None, credentials=credenciales)
        return Conexion(True, f"Conectado al proyecto {job_proyecto}.", job_proyecto, cli)
    except Exception as exc:
        return Conexion(False, f"{type(exc).__name__}: {exc}")


#: Fallos de credenciales que se ven igual desde arriba pero se arreglan
#: distinto. El texto de Google es correcto pero no dice donde mirar.
PISTAS_ERROR = (
    ("invalid_jwt signature", "firma"),
    ("invalid jwt signature", "firma"),
    ("invalid_grant", "firma"),
    ("could not deserialize key", "formato"),
    ("no key could be detected", "formato"),
    ("incorrect padding", "formato"),
    ("access denied", "permiso"),
    ("permission denied", "permiso"),
    ("user does not have", "permiso"),
    ("not found: dataset", "ruta"),
    ("not found: table", "ruta"),
    ("metadata.google.internal", "sin_cuenta"),
    ("compute engine metadata", "sin_cuenta"),
    ("default credentials", "sin_cuenta"),
)

GUIA_ERROR = {
    "firma": (
        "La llave privada de la service account no valida contra su correo. "
        "Casi siempre es la `private_key` mal pegada en los secrets: tiene que "
        "ir en UNA linea, entre comillas dobles, con los saltos como los dos "
        "caracteres \\n y no como saltos de linea reales. Revisa tambien que "
        "`client_email` y `private_key` sean de la MISMA cuenta, y que la llave "
        "no haya sido rotada o borrada en GCP."
    ),
    "formato": (
        "La `private_key` no se pudo leer. Pegala completa, incluyendo las "
        "lineas BEGIN y END, en una sola linea entre comillas dobles y con los "
        "saltos como \\n."
    ),
    "permiso": (
        "La service account se autentico bien pero no tiene permiso sobre ese "
        "dataset. Pide `roles/bigquery.dataViewer` sobre el dataset y "
        "`roles/bigquery.jobUser` sobre el proyecto donde corren los jobs."
    ),
    "ruta": (
        "El dataset o la tabla no existen con ese nombre. Revisa la ruta en los "
        "secrets: distingue mayusculas de minusculas."
    ),
    "sin_cuenta": (
        "Falta el bloque [gcp_service_account] en los secrets. Sin credenciales "
        "explicitas la app intenta autenticarse como si corriera dentro de Google "
        "Cloud y sale a buscar el servidor de metadatos, que en Streamlit no "
        "existe. Pega el JSON de la service account completo."
    ),
}


def explica_error(exc: Exception) -> str:
    """Traduce el error de Google a algo accionable, sin ocultar el original."""
    crudo = f"{type(exc).__name__}: {exc}"
    texto = str(exc).lower()
    for aguja, clave in PISTAS_ERROR:
        if aguja in texto:
            return f"{GUIA_ERROR[clave]}\n\nError original: {crudo}"
    return crudo


def tabla_ventas(cfg: dict | None = None) -> str:
    cfg = config() if cfg is None else cfg
    tabla = str(cfg.get("ventas_table") or cfg.get("tabla_ventas") or TABLA_VENTAS).strip()
    return _valida_tabla(tabla, "ventas")


def tabla_arti(cfg: dict | None = None) -> str:
    cfg = config() if cfg is None else cfg
    tabla = str(cfg.get("product_master_table") or cfg.get("table") or TABLA_ARTI).strip()
    return _valida_tabla(tabla, "maestro de productos")


# ---------------------------------------------------------------------------
# descubrimiento de esquema
# ---------------------------------------------------------------------------

def columnas(conn: Conexion, tabla: str) -> pd.DataFrame:
    """Lee INFORMATION_SCHEMA. Es gratis y no toca los datos."""
    partes = tabla.split(".")
    if len(partes) != 3:
        raise ValueError(f"La tabla debe venir como proyecto.dataset.tabla: {tabla!r}")
    proyecto, dataset, nombre = partes
    sql = f"""
        SELECT column_name, data_type
        FROM `{proyecto}.{dataset}.INFORMATION_SCHEMA.COLUMNS`
        WHERE table_name = @tabla
        ORDER BY ordinal_position
    """
    from google.cloud import bigquery
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("tabla", "STRING", nombre)])
    return conn.cliente.query(sql, job_config=cfg).to_dataframe()


def perfil_tabla(conn: Conexion, tabla: str, mapa: dict) -> dict:
    """Cuantas filas tiene y entre que fechas, para explicar un resultado vacio.

    Cuando una consulta acotada por periodo devuelve cero filas, la duda es si
    la tabla esta vacia, si el rango no cae donde hay datos, o si la columna de
    fecha mapeada no es la correcta. Esto las separa en una sola consulta.
    """
    if "fecha" not in mapa:
        sql = f"SELECT COUNT(*) AS filas, NULL AS desde, NULL AS hasta FROM `{tabla}`"
    else:
        col = mapa["fecha"]
        sql = (f"SELECT COUNT(*) AS filas, MIN(DATE(`{col}`)) AS desde, "
               f"MAX(DATE(`{col}`)) AS hasta FROM `{tabla}`")
    df = conn.cliente.query(sql).to_dataframe()
    if not len(df):
        return {}
    fila = df.iloc[0]
    return {"filas": int(fila["filas"]),
            "desde": fila.get("desde"), "hasta": fila.get("hasta"),
            "columna_fecha": mapa.get("fecha")}


def buscar_tablas(conn: Conexion, tabla: str, patron: str = "pedido") -> pd.DataFrame:
    """Donde vive realmente una tabla que no aparecio donde se la busco.

    Primero mira el dataset indicado y despues, si ahi no hay nada, barre el
    proyecto entero por region. Las dos consultas son a INFORMATION_SCHEMA:
    son gratis y no tocan los datos.
    """
    from google.cloud import bigquery

    partes = tabla.split(".")
    if len(partes) != 3:
        return pd.DataFrame(columns=["table_schema", "table_name"])
    proyecto, dataset, _nombre = partes
    cfg = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("patron", "STRING", f"%{patron.lower()}%")])

    intentos = (
        f"""SELECT table_schema, table_name
            FROM `{proyecto}.{dataset}.INFORMATION_SCHEMA.TABLES`
            WHERE LOWER(table_name) LIKE @patron
            ORDER BY table_name LIMIT 50""",
        f"""SELECT table_schema, table_name
            FROM `{proyecto}.region-us.INFORMATION_SCHEMA.TABLES`
            WHERE LOWER(table_name) LIKE @patron
            ORDER BY table_schema, table_name LIMIT 50""",
    )
    for sql in intentos:
        try:
            df = conn.cliente.query(sql, job_config=cfg).to_dataframe()
        except Exception:
            continue
        if len(df):
            return df
    return pd.DataFrame(columns=["table_schema", "table_name"])


def _normaliza(texto: str) -> str:
    """`Nro. Pedido`, `NRO_PEDIDO` y `nroPedido` colapsan al mismo texto."""
    import unicodedata
    plano = unicodedata.normalize("NFKD", str(texto))
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return "".join(c for c in plano.lower() if c.isalnum())


def _sufijo_comun(columnas: list[str]) -> str:
    """Sufijo de tabla que llevan TODAS las columnas, si lo hay.

    Las tablas de staging suelen marcar su origen en cada columna
    (`nroped_ph`, `codloc_ph`, ...). Ese sufijo es ruido para el
    emparejamiento, pero solo se puede quitar si lo llevan todas: si una
    columna no lo tiene, no es un sufijo de tabla y podria ser parte del
    nombre real.
    """
    candidatos = set()
    for c in columnas:
        if "_" in c:
            cola = c.rsplit("_", 1)[1]
            if 1 <= len(cola) <= 3 and cola.isalpha():
                candidatos.add(cola.lower())
    if len(candidatos) != 1:
        return ""
    sufijo = candidatos.pop()
    if all(str(c).lower().endswith("_" + sufijo) for c in columnas):
        return sufijo
    return ""


def _sin_sufijo(columna: str, sufijo: str) -> str:
    if sufijo and str(columna).lower().endswith("_" + sufijo):
        return str(columna)[: -(len(sufijo) + 1)]
    return str(columna)


def _puntaje(alias_norm: str, col_norm: str) -> int:
    """Cuanto se parecen. 0 significa que no se parecen en nada."""
    if not alias_norm or not col_norm:
        return 0
    if alias_norm == col_norm:
        return 100
    if col_norm.startswith(alias_norm) or col_norm.endswith(alias_norm):
        return 85
    if alias_norm in col_norm:
        return 70
    if col_norm in alias_norm and len(col_norm) >= 4:
        return 60
    return 0


def mapear(cols: list[str], alias: dict | None = None) -> dict[str, str]:
    """Empareja cada campo logico con la columna real que mas se le parezca.

    El emparejamiento exacto no alcanza contra tablas de staging: los mismos
    datos llegan como `NRO_PEDIDO`, `nro.pedido` o `nroPedido` segun el origen.
    Se compara sobre el texto normalizado y se resuelve por puntaje, asignando
    primero las coincidencias mas fuertes para que una columna no quede tomada
    por un campo que la necesitaba menos.
    """
    alias = alias or ALIAS_VENTAS
    columnas = [str(c) for c in cols]
    sufijo = _sufijo_comun(columnas)
    norm_col = {c: _normaliza(_sin_sufijo(c, sufijo)) for c in columnas}

    candidatos = []
    for campo, nombres in alias.items():
        for n in nombres:
            an = _normaliza(n)
            for c in columnas:
                p = _puntaje(an, norm_col[c])
                if p:
                    # A igual puntaje gana el alias declarado antes.
                    candidatos.append((p, -nombres.index(n), campo, c))

    candidatos.sort(reverse=True)
    salida: dict[str, str] = {}
    usadas: set[str] = set()
    for _p, _orden, campo, col in candidatos:
        if campo in salida or col in usadas:
            continue
        salida[campo] = col
        usadas.add(col)
    return salida


def faltantes(mapa: dict | None) -> list[str]:
    mapa = mapa or {}
    problemas = [c for c in OBLIGATORIOS if c not in mapa]
    if not any(c in mapa for c in IDENTIFICA_TIENDA):
        problemas.append("tienda (codigo o nombre)")
    if not any(c in mapa for c in IDENTIFICA_PRODUCTO):
        problemas.append("producto (ID Producto o Cod. Modelo)")
    return problemas


def cargar_mapeo() -> dict:
    if not MAPPING_PATH.exists():
        return {}
    try:
        return json.loads(MAPPING_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def guardar_mapeo(mapa: dict, tabla: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    actual = cargar_mapeo()
    actual[tabla] = mapa
    MAPPING_PATH.write_text(json.dumps(actual, ensure_ascii=False, indent=1),
                            encoding="utf-8")


# ---------------------------------------------------------------------------
# ejecucion con control de costo
# ---------------------------------------------------------------------------

def estimar_gb(conn: Conexion, sql: str, params=None) -> float:
    """Dry run: cuanto se va a leer, sin leer nada ni cobrar."""
    from google.cloud import bigquery
    cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False,
                                  query_parameters=params or [])
    job = conn.cliente.query(sql, job_config=cfg)
    return job.total_bytes_processed / 1e9


def ejecutar(conn: Conexion, sql: str, params=None, max_gb: float = MAX_GB_POR_DEFECTO):
    """Devuelve (dataframe, gb_leidos). Lanza si supera el tope."""
    from google.cloud import bigquery
    gb = estimar_gb(conn, sql, params)
    if max_gb and gb > max_gb:
        raise RuntimeError(
            f"La consulta leeria {gb:.1f} GB y el tope esta en {max_gb:.0f} GB. "
            "Acorta el rango de fechas o sube el tope."
        )
    cfg = bigquery.QueryJobConfig(query_parameters=params or [])
    df = conn.cliente.query(sql, job_config=cfg).to_dataframe()
    return df, gb


def _param(nombre: str, tipo: str, valor):
    from google.cloud import bigquery
    return bigquery.ScalarQueryParameter(nombre, tipo, valor)


# ---------------------------------------------------------------------------
# consultas de negocio
# ---------------------------------------------------------------------------

def _select(mapa: dict, campos: list[str]) -> list[str]:
    """Columnas del SELECT, con alias al nombre logico."""
    return [f"`{mapa[c]}` AS {c}" for c in campos if c in mapa]


#: Sin `HAVING`: si la columna de origen se llama igual que el alias de salida
#: (`unidades`), BigQuery resuelve el nombre al alias —que ya es un SUM— y falla
#: con "Aggregations of aggregations are not allowed". Las filas que suman cero
#: se descartan despues, en pandas, que es equivalente y no puede romperse.

def sql_ventas_agregadas(mapa: dict, tabla: str) -> str:
    """Venta del periodo agregada por producto y tienda: alimenta la Tabla de Repo."""
    dims = [c for c in ("tienda_cod", "tienda_nombre", "clase", "marca", "genero",
                        "linea", "temporada", "estilo", "tipo_prenda",
                        "temporada_comercial", "cod_modelo", "modelo", "cod_color",
                        "color", "talla", "id_producto", "barra") if c in mapa]
    select = ",\n               ".join(_select(mapa, dims))
    group = ", ".join(str(i + 1) for i in range(len(dims)))
    venta = (f",\n               SUM(`{mapa['venta']}`) AS venta"
             if "venta" in mapa else "")
    return f"""
        SELECT {select},
               SUM(`{mapa['unidades']}`) AS unidades{venta}
        FROM `{tabla}`
        WHERE DATE(`{mapa['fecha']}`) BETWEEN @desde AND @hasta
        GROUP BY {group}
    """


def sql_ventas_diarias(mapa: dict, tabla: str) -> str:
    """Venta diaria por tienda y producto: alimenta el Analisis de Efectividad."""
    dims = [c for c in ("tienda_cod", "tienda_nombre", "id_producto", "cod_modelo",
                        "modelo", "cod_color", "color", "talla") if c in mapa]
    select = ",\n               ".join(_select(mapa, dims))
    group = ", ".join(str(i + 2) for i in range(len(dims)))
    return f"""
        SELECT DATE(`{mapa['fecha']}`) AS fecha,
               {select},
               SUM(`{mapa['unidades']}`) AS unidades
        FROM `{tabla}`
        WHERE DATE(`{mapa['fecha']}`) BETWEEN @desde AND @hasta
        GROUP BY 1, {group}
    """


def ventas(conn: Conexion, mapa: dict, tabla: str, desde: date, hasta: date,
           diaria: bool = False, max_gb: float = MAX_GB_POR_DEFECTO):
    sql = sql_ventas_diarias(mapa, tabla) if diaria else sql_ventas_agregadas(mapa, tabla)
    params = [_param("desde", "DATE", desde), _param("hasta", "DATE", hasta)]
    df, gb = ejecutar(conn, sql, params, max_gb)
    if "unidades" in df.columns:          # el filtro que antes hacia el HAVING
        df = df[pd.to_numeric(df["unidades"], errors="coerce").fillna(0) != 0]
    return df.reset_index(drop=True), gb


#: Alias del maestro de productos. Segun la capa, el tablon trae unos u otros.
ALIAS_ARTI = {
    "id_producto": ["codint_ma", "codint", "id_producto", "idproducto", "sku"],
    "modcol": ["cod_mod_col", "codmod_codcol", "mod_col", "modelo_color",
               "codigo_modelo_color"],
    "cod_modelo": ["codmod_ma", "cod_modelo", "codigo_modelo", "modelo_cod", "cod_mod"],
    "cod_color": ["codcol_ma", "cod_color", "codigo_color", "color_cod"],
    "talla": ["talnum_ma", "talla_numero", "talla", "size", "cod_talla"],
    "barra": ["codbar_ma", "cod_bar_ma", "ean", "ean_ma", "codbarras", "cod_barras",
              "codigo_barra", "codigo_barras", "barra", "gtin", "upc"],
}


def sql_arti(tabla: str, mapa: dict) -> str:
    """Maestro de productos. Se pide solo lo necesario para armar la llave."""
    campos = [c for c in ("id_producto", "modcol", "cod_modelo", "cod_color",
                          "talla", "barra") if c in mapa]
    select = ",\n               ".join(
        f"CAST(`{mapa[c]}` AS STRING) AS {c}" for c in campos)
    return f"""
        SELECT DISTINCT
               {select}
        FROM `{tabla}`
        WHERE `{mapa['id_producto']}` IS NOT NULL
    """


def arti(conn: Conexion, tabla: str, max_gb: float = MAX_GB_POR_DEFECTO):
    """Devuelve (dataframe, gb, mapa_usado). Descubre el esquema por su cuenta."""
    cols = columnas(conn, tabla)
    mapa = mapear(list(cols["column_name"]), ALIAS_ARTI)
    if "id_producto" not in mapa:
        raise RuntimeError(
            "No encontre la columna de ID Producto (CODINT_MA) en "
            f"{tabla}. Columnas: {', '.join(map(str, cols['column_name'][:25]))}…")
    if not any(c in mapa for c in ("modcol", "cod_modelo", "barra")):
        raise RuntimeError(
            f"{tabla} no trae modelo-color ni codigo de barras: no hay como armar "
            "la llave del REPO.")
    df, gb = ejecutar(conn, sql_arti(tabla, mapa), None, max_gb)
    return df, gb, mapa


def llaves_desde_arti(df: pd.DataFrame, mapa: dict,
                      barras_por_llave: pd.Series | None = None):
    """Convierte el maestro en pares LLAVE -> ID Producto.

    Camino 1: si ARTI trae modelo-color y talla, la llave se arma directo.
    Camino 2: si no, se puentea por codigo de barras contra las llaves que ya
    conocemos de bodega y venta.
    """
    def limpio(serie):
        return (pd.Series(serie).astype("string").str.strip()
                .str.replace(r"^'+", "", regex=True).str.upper())

    ids = limpio(df["id_producto"])

    if "talla" in mapa and ("modcol" in mapa or
                            ("cod_modelo" in mapa and "cod_color" in mapa)):
        if "modcol" in mapa:
            base = limpio(df["modcol"])
        else:
            base = limpio(df["cod_modelo"]) + "-" + limpio(df["cod_color"])
        llaves = base + "-" + limpio(df["talla"])
        return pd.DataFrame({"llave": llaves, "id": ids}), "modelo-color + talla"

    if "barra" in mapa and barras_por_llave is not None and len(barras_por_llave):
        barra_a_id = dict(zip(limpio(df["barra"]), ids))
        llaves = pd.Series(barras_por_llave.index, dtype="object")
        valores = pd.Series(barras_por_llave.values).astype("string").map(barra_a_id)
        out = pd.DataFrame({"llave": llaves, "id": valores}).dropna()
        return out, "puente por codigo de barras"

    raise RuntimeError("El maestro no trae talla ni codigo de barras cruzable.")


# ---------------------------------------------------------------------------
# adaptadores al formato que ya usan los motores
# ---------------------------------------------------------------------------

RENOMBRA_VTA = {
    "clase": "Clase", "marca": "Marca", "genero": "Genero", "linea": "Linea",
    "temporada": "Temporada", "estilo": "Estilo", "tipo_prenda": "Tipo Prenda",
    "temporada_comercial": "Temporada Comercial", "cod_modelo": "Cod. Modelo",
    "modelo": "Modelo", "cod_color": "Cod. Color", "color": "Color",
    "talla": "Talla/Numero", "barra": "Codigo Barra", "tienda_cod": "Tienda",
    "tienda_nombre": "Nombre Tienda", "unidades": "Unidades", "venta": "Venta",
    "id_producto": "ID Producto",
}

RENOMBRA_VENTA_DIARIA = {
    "fecha": "FECHA", "tienda_cod": "Tienda", "tienda_nombre": "Nombre Tienda",
    "cod_modelo": "Cod Modelo", "modelo": "Modelo", "cod_color": "Cod Color",
    "color": "Color", "talla": "Talla/Numero", "unidades": "Total",
    "id_producto": "sku",
}


def a_formato_vta(df: pd.DataFrame) -> pd.DataFrame:
    """Deja el resultado igual que devuelve el lector del TXT de venta.

    No se agregan `Stock` ni `Transito`: esas dos columnas son la huella con la
    que la app reconoce el archivo de bodega, y ponerlas haria que el frame de
    venta se detecte como el archivo equivocado. El motor las trata como 0
    cuando no existen.
    """
    from .catalogs import normalize_store_code

    out = df.rename(columns=RENOMBRA_VTA).copy()
    for col in ("Clase", "Marca", "Genero", "Linea", "Temporada", "Estilo",
                "Vigencia", "Tipo Prenda", "Temporada Comercial", "Cod. Modelo",
                "Modelo", "Cod. Color", "Color", "Talla/Numero", "Tienda",
                "Nombre Tienda", "Codigo Barra"):
        if col not in out.columns:
            out[col] = pd.NA
        else:
            out[col] = (out[col].astype("string").str.strip()
                        .str.replace(r"^'+", "", regex=True)
                        .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA}))
    for col in ("Unidades", "Venta"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0.0)
        else:
            out[col] = 0.0
    out["_tienda_key"] = out["Tienda"].map(normalize_store_code)
    out["Origen Venta"] = "bigquery"
    return out


def a_formato_venta_diaria(df: pd.DataFrame) -> pd.DataFrame:
    """Deja el resultado igual que la hoja `venta` del Excel de venta diaria."""
    out = df.rename(columns=RENOMBRA_VENTA_DIARIA).copy()
    for col in ("FECHA", "Nombre Tienda", "sku", "Total"):
        if col not in out.columns:
            out[col] = pd.NA
    return out


# ---------------------------------------------------------------------------
# pedidos: cabecera + detalle
# ---------------------------------------------------------------------------
#
# Reemplazan la subida manual del DETALLADO y la EVOLUCION, y alimentan el
# dashboard de pedidos. Como son tablas de staging, los nombres de columna no
# se asumen: se descubren con INFORMATION_SCHEMA y se emparejan por alias,
# igual que el tablon de ventas. Lo que no se reconozca se corrige una vez en
# pantalla y queda guardado en `data/bq_mapping.json`.

TABLA_PED_HEADER = ""
TABLA_PED_DETAIL = ""

ALIAS_PED_HEADER = {
    "nro_pedido": ["nroped", "nro_pedido", "nro_ped", "num_pedido", "numero_pedido", "cod_pedido",
                   "id_pedido", "numped", "nro_orden", "orden", "pedido"],
    "fecha": ["fecdoc", "fecped", "fec_pedido", "fecha_pedido", "fec_emision", "fecha_emision",
              "fec_doc", "fecha_documento", "fecha_aprobacion", "fecha_registro",
              "fecha"],
    "estado": ["estado", "desest", "des_estado", "desc_estado", "nom_estado", "estado_pedido",
               "estado_desc", "estado", "situacion", "status"],
    "tipo_pedido": ["clasificacion", "tipped", "tip_pedido", "tipo_pedido", "des_tipo_pedido", "desc_tipo_pedido",
                    "tip_ped", "tipo_ped", "clasificacion", "clasificacion_pedido",
                    "motivo", "tipo_documento", "tipo"],
    "canal": ["canal", "codcan", "canal_venta", "desc_canal", "tipo_canal"],
    "bodega_origen": ["origen", "codori", "bodega_origen", "cod_bodega_origen", "almacen_origen",
                      "bodega", "cod_bodega"],
    "destino": ["destinatario", "coddes", "destino", "bodega_destino", "almacen_destino", "tienda_destino",
                "nombre_destino", "desc_destino"],
    "tienda_cod": ["codloc", "cod_local", "cod_tienda", "codigo_tienda", "cod_loc",
                   "tienda_cod", "cod_destino", "id_local"],
    "tienda_nombre": ["localoperador", "nomloc", "desloc", "nom_local", "des_local", "nombre_local", "nombre_tienda",
                      "nom_tienda", "des_tienda", "desc_tienda", "tienda_nombre",
                      "nombre_loc", "tienda"],
    "ciudad": ["desciu", "codciu", "des_ciudad", "nom_ciudad", "desc_ciudad", "ciudad", "departamento",
               "provincia", "region", "zona"],
    "cadena": ["des_cadena", "nom_cadena", "tip_cadena", "tipo_cadena", "cadena",
               "marca_cadena"],
    "unid_pedidas": ["canped", "cant_pedida", "cant_ped", "unid_pedidas", "cantidad_pedida",
                     "und_pedidas", "qty_pedida", "total_pedido"],
    "unid_despachadas": ["candes", "candesp", "cant_despachada", "cant_desp", "unid_despachadas",
                         "cantidad_despachada", "und_despachadas", "qty_despachada",
                         "total_despachado"],
    "unid_pendientes": ["canpen", "canpend", "cant_pendiente", "cant_pend", "unid_pendientes",
                        "cantidad_pendiente", "und_pendientes", "qty_pendiente", "saldo"],
}

ALIAS_PED_DETAIL = {
    "nro_pedido": ["nro_pedido", "nro_ped", "num_pedido", "numero_pedido", "cod_pedido",
                   "id_pedido", "numped", "nro_orden", "orden", "pedido"],
    "fecha": ["fecdoc", "fecped", "fec_pedido", "fecha_pedido", "fec_emision", "fecha_emision",
              "fec_doc", "fecha"],
    "tienda_cod": ["cod_local", "cod_tienda", "codigo_tienda", "cod_loc",
                   "tienda_cod", "cod_destino", "id_local"],
    "tienda_nombre": ["nombre_tienda", "tienda_nombre", "tienda", "nombre_loc",
                      "tienda_cliente", "cliente", "desc_tienda"],
    "id_producto": ["codint", "id_producto", "codint_ma", "codint", "sku", "idproducto"],
    "cod_modelo": ["codmod", "cod_modelo", "codmod_ma", "codigo_modelo", "cod_mod", "modelo_cod"],
    "modelo": ["modelo", "desc_modelo", "nom_modelo", "descripcion"],
    "cod_color": ["codcol", "cod_color", "codcol_ma", "codigo_color", "color_cod"],
    "color": ["color", "desc_color", "nom_color"],
    "talla": ["talnum", "talla", "talnum_ma", "talla_numero", "talla_nro", "size", "cod_talla"],
    "barra": ["codbar", "barra", "codbar_ma", "codigo_barra", "cod_barras", "ean", "gtin"],
    "marca": ["desmar", "codmar", "des_marca", "nom_marca", "desc_marca", "marca"],
    "clase": ["clase", "desc_clase", "linea_negocio"],
    "tipo_prenda": ["des_tipo_prenda", "tipo_prenda", "desc_tipo_prenda", "des_familia",
                    "familia", "subfamilia", "categoria", "tipo_producto"],
    "unid_pedidas": ["canped", "cant_pedida", "cant_ped", "unid_pedidas", "cantidad_pedida",
                     "und_pedidas", "qty_pedida", "cantidad"],
    "unid_despachadas": ["candes", "candesp", "cant_despachada", "cant_desp", "unid_despachadas",
                         "cantidad_despachada", "und_despachadas", "qty_despachada",
                         "cantidad_atendida"],
    "unid_pendientes": ["canpen", "canpend", "cant_pendiente", "cant_pend", "unid_pendientes",
                        "cantidad_pendiente", "und_pendientes", "qty_pendiente", "saldo"],
}

#: Lo minimo para que el cruce y la columna REP funcionen.
OBLIG_PED_HEADER = ("nro_pedido", "estado")
OBLIG_PED_DETAIL = ("nro_pedido", "unid_pedidas")

ALIAS_POR_FUENTE = {
    "ped_header": ALIAS_PED_HEADER,
    "ped_detail": ALIAS_PED_DETAIL,
    "ventas": ALIAS_VENTAS,
}


#: Textos de la plantilla de secrets. Si llegan tal cual, es que se pego el
#: ejemplo sin reemplazar: mejor decirlo que dejar que BigQuery devuelva un 400.
PLACEHOLDERS = {"proyecto", "dataset", "tabla", "proyecto_id", "tu_project_id",
                "pon_aqui_tu_tabla", "..."}


CLAVE_SECRET = {"cabecera": "pedidos_header_table", "detalle": "pedidos_detail_table",
                "ventas": "ventas_table", "maestro de productos": "product_master_table"}


def _valida_tabla(tabla: str, etiqueta: str) -> str:
    clave = CLAVE_SECRET.get(etiqueta, "la clave correspondiente")
    if not str(tabla).strip():
        raise RuntimeError(
            f"Falta la tabla de {etiqueta} en los secrets. Agrega "
            f"`{clave} = \"proyecto.dataset.tabla\"` dentro del bloque [bigquery]. "
            "No hay valor por defecto a proposito: este repositorio es publico y "
            "las rutas de las tablas no van en el codigo.")
    partes = [p.strip() for p in str(tabla).split(".")]
    if len(partes) != 3 or not all(partes):
        raise RuntimeError(
            f"La tabla de {etiqueta} tiene que venir como proyecto.dataset.tabla "
            f"y llego '{tabla}'. Corrigela en los secrets, en `{clave}`.")
    if any(p.lower() in PLACEHOLDERS for p in partes):
        raise RuntimeError(
            f"La tabla de {etiqueta} quedo con el texto de ejemplo: '{tabla}'. "
            f"Reemplaza proyecto y dataset por los de verdad en `{clave}`.")
    return tabla


def tabla_ped_header(cfg: dict | None = None) -> str:
    cfg = config() if cfg is None else cfg
    tabla = str(cfg.get("pedidos_header_table") or cfg.get("tabla_pedidos_header")
                or TABLA_PED_HEADER).strip()
    return _valida_tabla(tabla, "cabecera")


def tabla_ped_detail(cfg: dict | None = None) -> str:
    cfg = config() if cfg is None else cfg
    tabla = str(cfg.get("pedidos_detail_table") or cfg.get("tabla_pedidos_detalle")
                or TABLA_PED_DETAIL).strip()
    return _valida_tabla(tabla, "detalle")


def faltantes_pedidos(mapa: dict | None, fuente: str) -> list[str]:
    mapa = mapa or {}
    obligatorios = OBLIG_PED_HEADER if fuente == "ped_header" else OBLIG_PED_DETAIL
    problemas = [c for c in obligatorios if c not in mapa]
    if fuente == "ped_detail" and not any(
            c in mapa for c in ("cod_modelo", "id_producto", "barra")):
        problemas.append("producto (Cod. Modelo, ID Producto o barra)")
    if fuente == "ped_header" and "fecha" not in mapa:
        problemas.append("fecha (sin ella no se puede acotar el periodo)")
    return problemas


def _fecha_where(mapa: dict, alias_tabla: str = "") -> str:
    """Filtro de periodo. Siempre parametrizado, nunca interpolado."""
    pref = f"{alias_tabla}." if alias_tabla else ""
    return f"DATE({pref}`{mapa['fecha']}`) BETWEEN @desde AND @hasta"


def sql_ped_header(mapa: dict, tabla: str) -> str:
    campos = [c for c in ALIAS_PED_HEADER if c in mapa]
    select = ",\n               ".join(_select(mapa, campos))
    return f"""
        SELECT {select}
        FROM `{tabla}`
        WHERE {_fecha_where(mapa)}
    """


def sql_ped_detail(mapa_d: dict, tabla_d: str,
                   mapa_h: dict | None = None, tabla_h: str | None = None) -> str:
    """Detalle del periodo.

    Si el detalle trae su propia fecha se filtra directo. Si no, se acota con
    los pedidos de la cabecera que caen en el rango: sin ese `IN` habria que
    leer la tabla entera.
    """
    campos = [c for c in ALIAS_PED_DETAIL if c in mapa_d]
    select = ",\n               ".join(_select(mapa_d, campos))
    if "fecha" in mapa_d:
        where = _fecha_where(mapa_d)
    elif mapa_h and tabla_h and "fecha" in mapa_h:
        where = (f"`{mapa_d['nro_pedido']}` IN (SELECT `{mapa_h['nro_pedido']}` "
                 f"FROM `{tabla_h}` WHERE {_fecha_where(mapa_h)})")
    else:
        raise RuntimeError(
            "Ni el detalle ni la cabecera tienen columna de fecha mapeada: no hay "
            "como acotar el periodo y la consulta leeria la tabla completa.")
    return f"""
        SELECT {select}
        FROM `{tabla_d}`
        WHERE {where}
    """


def ped_header(conn: Conexion, mapa: dict, tabla: str, desde: date, hasta: date,
               max_gb: float = MAX_GB_POR_DEFECTO):
    params = [_param("desde", "DATE", desde), _param("hasta", "DATE", hasta)]
    df, gb = ejecutar(conn, sql_ped_header(mapa, tabla), params, max_gb)
    return df.reset_index(drop=True), gb


def ped_detail(conn: Conexion, mapa_d: dict, tabla_d: str, desde: date, hasta: date,
               mapa_h: dict | None = None, tabla_h: str | None = None,
               max_gb: float = MAX_GB_POR_DEFECTO):
    params = [_param("desde", "DATE", desde), _param("hasta", "DATE", hasta)]
    sql = sql_ped_detail(mapa_d, tabla_d, mapa_h, tabla_h)
    df, gb = ejecutar(conn, sql, params, max_gb)
    return df.reset_index(drop=True), gb


# ---------------------------------------------------------------------------
# adaptadores de pedidos al formato de los lectores de Excel
# ---------------------------------------------------------------------------

def _texto(serie) -> pd.Series:
    return (serie.astype("string").str.strip()
            .str.replace(r"^'+", "", regex=True)
            .replace({"": pd.NA, "nan": pd.NA, "None": pd.NA, "<NA>": pd.NA}))


def a_formato_evolucion(df: pd.DataFrame) -> pd.DataFrame:
    """Deja la cabecera igual que devuelve el lector del Excel de EVOLUCION."""
    renombra = {
        "nro_pedido": "Nro. Pedido", "estado": "Estado", "canal": "Canal",
        "tipo_pedido": "Clasificacion", "bodega_origen": "Bodega origen",
        "destino": "Destino", "unid_pedidas": "Unid. Pedidas",
        "unid_despachadas": "Unid. Despachadas", "unid_pendientes": "Unid. Pendientes",
    }
    out = df.rename(columns=renombra).copy()
    if "Nro. Pedido" not in out.columns:
        raise RuntimeError("La cabecera no trae el numero de pedido mapeado.")
    out["Nro. Pedido"] = _texto(out["Nro. Pedido"])
    for col in ("Estado", "Clasificacion", "Destino", "Canal", "Bodega origen"):
        if col in out.columns:
            out[col] = _texto(out[col])
    for col in ("Unid. Pedidas", "Unid. Despachadas", "Unid. Pendientes"):
        out[col] = (pd.to_numeric(out[col], errors="coerce").fillna(0.0)
                    if col in out.columns else 0.0)
    return out.reset_index(drop=True)


def a_formato_detallado(df: pd.DataFrame) -> pd.DataFrame:
    """Deja el detalle igual que devuelve el lector del Excel de DETALLADO.

    Incluye `LLAVE` y `_tienda_key`, que el lector deriva y el motor de REP da
    por hechos. `Tienda / Cliente` se rearma como "008 HP JOCKEY" cuando la
    tabla trae el codigo y el nombre por separado, que es el formato del que
    parte el resto de la app.
    """
    from .catalogs import normalize_store_code
    from .readers import build_llave

    renombra = {
        "nro_pedido": "Numero Pedido", "fecha": "Fecha Pedido",
        "id_producto": "Id Producto", "cod_modelo": "Cod. Modelo", "modelo": "Modelo",
        "cod_color": "Cod. Color", "color": "Color", "talla": "Talla / Numero",
        "barra": "Barra", "marca": "Marca", "clase": "Clase",
        "tipo_prenda": "Tipo Prenda", "unid_pedidas": "Unid. Pedidas",
        "unid_despachadas": "Unid. Despachadas", "unid_pendientes": "Unid. Pendientes",
    }
    out = df.rename(columns=renombra).copy()
    if "Numero Pedido" not in out.columns:
        raise RuntimeError("El detalle no trae el numero de pedido mapeado.")

    for col in ("Numero Pedido", "Cod. Modelo", "Cod. Color", "Talla / Numero",
                "Modelo", "Color", "Clase", "Marca", "Tipo Prenda", "Id Producto",
                "Barra"):
        if col in out.columns:
            out[col] = _texto(out[col])

    cod = _texto(out["tienda_cod"]) if "tienda_cod" in out.columns else None
    nombre = _texto(out["tienda_nombre"]) if "tienda_nombre" in out.columns else None
    if cod is not None and nombre is not None:
        out["Tienda / Cliente"] = (cod.fillna("") + " " + nombre.fillna("")).str.strip()
    elif nombre is not None:
        out["Tienda / Cliente"] = nombre
    elif cod is not None:
        out["Tienda / Cliente"] = cod
    else:
        out["Tienda / Cliente"] = pd.NA

    if cod is not None:
        out["_tienda_key"] = cod.map(lambda v: normalize_store_code(v)
                                     if pd.notna(v) else pd.NA)
    else:
        # Mismo camino que el lector del Excel: "008 HP JOCKEY" -> 8.
        extraido = out["Tienda / Cliente"].astype("string").str.extract(
            r"^\s*(\d{1,4})\s+\S")[0]
        out["_tienda_key"] = extraido.map(lambda v: normalize_store_code(v)
                                          if pd.notna(v) else pd.NA)

    for col in ("Unid. Pedidas", "Unid. Despachadas", "Unid. Pendientes"):
        out[col] = (pd.to_numeric(out[col], errors="coerce").fillna(0.0)
                    if col in out.columns else 0.0)

    for col in ("Cod. Modelo", "Cod. Color", "Talla / Numero"):
        if col not in out.columns:
            out[col] = pd.NA
    out["LLAVE"] = build_llave(out["Cod. Modelo"], out["Cod. Color"],
                               out["Talla / Numero"])
    out = out.drop(columns=[c for c in ("tienda_cod", "tienda_nombre")
                            if c in out.columns])
    return out.reset_index(drop=True)
