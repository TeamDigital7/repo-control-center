"""Reglas, constantes y contratos de datos de la Tabla de Repo Final.

Todo lo que se descubrio al hacer ingenieria inversa de
``PLANTILLA DE REPO ... .xlsb`` vive aqui. Ningun modulo debe hardcodear
posiciones de columna: siempre se resuelven por nombre.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Identidad de los 5 archivos fuente
# ---------------------------------------------------------------------------

SRC_VTA = "vta"
SRC_BODEGA = "bodega"
SRC_CD = "cd"
SRC_EVOLUCION = "evolucion"
SRC_DETALLADO = "detallado"

SOURCE_ORDER = [SRC_VTA, SRC_BODEGA, SRC_CD, SRC_EVOLUCION, SRC_DETALLADO]

SOURCE_META = {
    SRC_VTA: {
        "label": "Venta por tienda",
        "hint": "VTA DEL 01 AL dd-mm-aa.txt",
        "types": ["txt", "csv"],
        "icon": "01",
        "desc": "Unidades vendidas del periodo, a nivel SKU x tienda.",
    },
    SRC_BODEGA: {
        "label": "Bodega / Gestion de stock",
        "hint": "BODEGA GESTIONdd.mm.txt",
        "types": ["txt", "csv"],
        "icon": "02",
        "desc": "Stock y transito por SKU x tienda, incluye el CD 320.",
    },
    SRC_CD: {
        "label": "Stock CD",
        "hint": "STOCK CD.xlsx",
        "types": ["xlsx", "xlsb", "xls"],
        "icon": "03",
        "desc": "Disponible y reservas del centro de distribucion + ID Producto.",
    },
    SRC_EVOLUCION: {
        "label": "Evolucion de pedidos",
        "hint": "EVOLUCION.xlsx",
        "types": ["xlsx", "xlsb", "xls"],
        "icon": "04",
        "desc": "Estado (Aprobado / Despachado / Recepcionado) de cada pedido.",
    },
    SRC_DETALLADO: {
        "label": "Detallado de pedidos",
        "hint": "DETALLADO DE PEDIDOS DEL 01 AL dd-mm-aa.xlsx",
        "types": ["xlsx", "xlsb", "xls"],
        "icon": "05",
        "desc": "Desglose SKU x tienda de cada pedido (pedidas / pendientes / despachadas).",
    },
}

# ---------------------------------------------------------------------------
# Columnas esperadas por fuente (validacion estructural)
# ---------------------------------------------------------------------------

REQUIRED_COLUMNS = {
    SRC_VTA: [
        "Clase", "Marca", "Genero", "Tipo Prenda", "Temporada Comercial",
        "Cod. Modelo", "Modelo", "Cod. Color", "Color", "Talla/Numero",
        "Tienda", "Nombre Tienda", "Unidades",
    ],
    SRC_BODEGA: [
        "Clase", "Marca", "Genero", "Tipo Prenda", "Temporada Comercial",
        "Cod. Modelo", "Modelo", "Cod. Color", "Color", "Talla/Numero",
        "Tienda", "Unidades", "Stock", "Transito",
    ],
    SRC_CD: [
        "Cod. Modelo", "Cod. Color", "Talla/Nro/Curva Tarea", "ID Producto",
        "Reserva eCommerce", "Res. Retail", "Res. Wholesale", "Res. Multicanal",
        "Disponible",
    ],
    SRC_EVOLUCION: [
        "Nro. Pedido", "Estado", "Unid. Pedidas", "Unid. Despachadas",
        "Unid. Pendientes",
    ],
    SRC_DETALLADO: [
        "Numero Pedido", "Tienda / Cliente", "Cod. Modelo", "Cod. Color",
        "Talla / Numero", "Unid. Pedidas", "Unid. Pendientes",
        "Unid. Despachadas",
    ],
}

#: Columnas que permiten distinguir automaticamente un archivo de otro.
SOURCE_FINGERPRINTS = {
    # VTA y BODEGA comparten las primeras 25 columnas; solo difieren al final.
    SRC_VTA: {"must": ["Sitio eCommerce"], "must_not": ["Stock"]},
    SRC_BODEGA: {"must": ["Stock", "Transito"], "must_not": ["Sitio eCommerce"]},
    SRC_CD: {"must": ["Talla/Nro/Curva Tarea", "Stock Bodega"], "must_not": []},
    SRC_EVOLUCION: {"must": ["Nro. Pedido", "Estado"], "must_not": []},
    SRC_DETALLADO: {"must": ["Numero Pedido", "Tienda / Cliente"], "must_not": []},
}

# ---------------------------------------------------------------------------
# Estructura EXACTA de la hoja REPO
# ---------------------------------------------------------------------------

#: Las 19 columnas fijas, en el orden exacto de la plantilla.
FIXED_COLUMNS = [
    "Marca",
    "Clase",
    "Genero",
    "Tipo Prenda",
    "Modelo",
    "Color",
    "Cod Modelo",
    "Cod Color",
    "Talla/Numero",
    "Temporada Comercial",
    "SKU",
    "TRASPASOS DE TEMPORADA",
    "REPOSICIÓN",
    "NVO DSP CD",
    "ECOM",
    "RT",
    "WS",
    "MM",
    "DSP",
]

#: Las 10 primeras columnas son los "row labels" del pivote original.
GROUP_COLUMNS = FIXED_COLUMNS[:10]

#: Sub-encabezados por tienda. Los espacios iniciales son parte del original.
STORE_METRICS = [" VNT", " STK", " REP"]

#: Filas de encabezado del archivo final (1-indexed como en Excel).
ROW_TOTALS = 1      # fila de totales por columna
ROW_COD_TIENDA = 2  # codigo de tienda
ROW_ABREV = 3       # abreviatura de tienda
ROW_HEADER = 4      # nombres de columna
ROW_FIRST_DATA = 5

SHEET_NAME = "REPO"

#: Etiqueta que usa la tabla dinamica original para valores vacios.
BLANK_LABEL = "(en blanco)"

#: Texto que la plantilla deja cuando BUSCARX no encuentra el SKU.
NA_TOKEN = "#N/A"

# ---------------------------------------------------------------------------
# Reglas de negocio
# ---------------------------------------------------------------------------

#: Clases que la plantilla excluye del REPO (fletes / despachos, no son producto).
EXCLUDED_CLASES = {"DESPACHOS"}

#: Marcas excluidas del REPO.
EXCLUDED_MARCAS = {"OTROS"}

#: Fila de totales que traen los exports de Forus y hay que descartar.
TOTAL_ROW_TOKENS = {"TOTAL", "TOTAL INFORME", "TOTAL GENERAL"}

#: Codigo de bodega del CD dentro del archivo BODEGA GESTION.
CD_TIENDA_CODE = "320"
CD_TIENDA_NOMBRE = "BODEGA FORUS 320"

#: Mapeo columna del REPO  <-  columna de STOCK CD (todas por LLAVE).
CD_LOOKUP_MAP = {
    "ECOM": "Reserva eCommerce",
    "RT": "Res. Retail",
    "WS": "Res. Wholesale",
    "MM": "Res. Multicanal",
    "DSP": "Disponible",
}

#: Columna de STOCK CD que alimenta el SKU del REPO.
CD_SKU_COLUMN = "ID Producto"

#: Estados de EVOLUCION que significan "todavia no llego a la tienda".
ESTADOS_EN_CAMINO = ("Aprobado", "Despachado")

#: La columna REP es la CAPTURA del planner: al escribir en ella,
#: REPOSICIÓN (= suma de las 69 REP) sube y NVO DSP CD (= DSP + RT - REPOSICIÓN)
#: baja. Por eso el valor por defecto es dejarla vacia, igual que la plantilla.
REP_MODES = {
    "vacio": {
        "label": "Vacia, para llenar a mano (igual que la plantilla)",
        "help": (
            "REP es tu columna de captura. Al escribir, REPOSICIÓN suma y "
            "NVO DSP CD descuenta del disponible del CD automaticamente."
        ),
    },
    "pendiente_recepcion": {
        "label": "Precargar con pedidos que aun no llegan a la tienda",
        "help": (
            "Arranca la repo desde lo ya pedido: unidades del DETALLADO cuyos "
            "pedidos siguen Aprobados o Despachados segun EVOLUCION."
        ),
    },
    "despachado_no_recibido": {
        "label": "Precargar solo con pedidos ya despachados",
        "help": "Mas estricto: excluye los pedidos que siguen en estado Aprobado.",
    },
    "transito_bodega": {
        "label": "Precargar con el transito de Bodega Gestion",
        "help": "Usa la columna Transito del archivo de bodega, sin cruzar pedidos.",
    },
}
DEFAULT_REP_MODE = "vacio"

#: `_origen` de las filas de DATA que vienen de lo ya enviado a la tienda.
ORIGEN_EN_CAMINO = "en_camino"

#: Modos que solo precargan la columna; el detalle siempre va a la hoja EN CAMINO.
REP_PRELOAD_MODES = ("pendiente_recepcion", "despachado_no_recibido", "transito_bodega")

# ---------------------------------------------------------------------------
# Libro vivo: hojas de apoyo, rangos con nombre y formulas
# ---------------------------------------------------------------------------

#: Layout EXACTO de la hoja CD del libro (los indices los usan los BUSCARV).
#: A = LLAVE, luego el export de STOCK CD en el orden original de la plantilla.
CD_SHEET_COLUMNS = [
    "LLAVE",                  # A  1  = Cod. Modelo & "-" & Cod. Color & "-" & Talla
    "Clase",                  # B  2
    "Marca",                  # C  3
    "Genero",                 # D  4
    "Linea",                  # E  5
    "Temporada",              # F  6
    "Temporada Comercial",    # G  7
    "Cod. Modelo",            # H  8
    "Modelo",                 # I  9
    "Cod. Color",             # J 10
    "Color",                  # K 11
    "Talla/Nro/Curva Tarea",  # L 12
    "Tipo Prenda",            # M 13
    "Cod.Barra/SKU",          # N 14
    "Stock Bodega",           # O 15
    "Total Pares",            # P 16
    "Reserva Pedidos",        # Q 17
    "Reserva eCommerce",      # R 18  -> ECOM
    "ID Producto",            # S 19  -> SKU
    "Res. Retail",            # T 20  -> RT
    "Res. Wholesale",         # U 21  -> WS
    "Res. Multicanal",        # V 22  -> MM
    "Disponible",             # W 23  -> DSP  (en la plantilla el titulo es "Disp")
    "Res. MarketPlace",       # X 24  columna nueva del export, va al final
]
CD_SHEET_HEADER_ALIAS = {"Disponible": "Disp"}

#: Indice de columna (1-based) dentro de la hoja CD para cada BUSCARV del REPO.
CD_COL_INDEX = {"ECOM": 18, "SKU": 19, "RT": 20, "WS": 21, "MM": 22, "DSP": 23}

#: Rangos con nombre que deben existir para que las formulas vivan.
NAMED_RANGES = {
    "TIENDA": "=TIENDAS2!$D:$E",    # ABREV -> COD TI   (fila 2 del REPO)
    "TRSPINV26": "=LLAVES!$Q:$R",   # llave -> "T"      (columna L del REPO)
    "CD": "=CD!$A:$X",              # usado por la hoja DATA
    "ORDEN": "=TIENDAS2!$B:$C",     # NOMBRE TIENDA -> ORDEN
    "ABREV": "=TIENDAS2!$B:$D",     # NOMBRE TIENDA -> ABREV
    "SKUS": "=SKUS!$A:$B",          # LLAVE -> ID Producto (respaldo de la columna K)
}

# ---------------------------------------------------------------------------
# Formato de la hoja REPO (extraido celda por celda de la plantilla)
# ---------------------------------------------------------------------------

FONT_NAME = "Calibri"
FONT_SIZE = 11
ZOOM = 55

COLOR_REP = "#FCE4D6"        # bloque REP y fila de codigo de tienda
COLOR_REP_FONT = "#FF0000"
COLOR_CALC = "#00FF99"       # REPOSICIÓN y NVO DSP CD, de la fila 4 hacia abajo
COLOR_CALC_TOP = "#9DF9A4"   # las mismas columnas en las filas 1-3
COLOR_TRASPASO = "#00B0F0"   # encabezado de TRASPASOS DE TEMPORADA
COLOR_ALERTA = "#FFC7CE"     # extra: disponible negativo
COLOR_ALERTA_FONT = "#9C0006"

COLUMN_WIDTHS = {
    "Marca": 8.9, "Clase": 5.9, "Genero": 6.8, "Tipo Prenda": 15.3,
    "Modelo": 10.9, "Color": 13.6, "Cod Modelo": 21.8, "Cod Color": 7.8,
    "Talla/Numero": 7.8, "Temporada Comercial": 17.6, "SKU": 9.0,
    "TRASPASOS DE TEMPORADA": 8.9, "REPOSICIÓN": 5.9, "NVO DSP CD": 5.9,
    "ECOM": 3.9, "RT": 3.9, "WS": 3.9, "MM": 3.9, "DSP": 6.3,
}
STORE_COLUMN_WIDTH = 5.7
ROW_HEIGHTS = {1: 14.4, 2: 34.2, 3: 89.4, 4: 94.8}

# ---------------------------------------------------------------------------
# Orden natural de tallas
# ---------------------------------------------------------------------------

SIZE_ORDER = [
    "XXS", "2XS", "XS", "S", "SM", "M", "MD", "L", "LG", "XL", "1XL",
    "XXL", "2XL", "XXXL", "3XL", "4XL", "5XL",
    "O/S", "OS", "U", "UNI", "T/U",
]
SIZE_RANK = {s: i for i, s in enumerate(SIZE_ORDER)}
