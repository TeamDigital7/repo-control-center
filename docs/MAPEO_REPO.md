# Matriz de mapeo — Tabla de Repo Final

Documento de ingenieria inversa sobre `PLANTILLA DE REPO 18-08-2026 CR.xlsb`
(hoja `REPO`, 29.369 filas x 226 columnas).

Todas las reglas de este documento fueron **verificadas numericamente** contra la
plantilla original. Ver la seccion *Validacion* al final.

---

## 1. Estructura del archivo final

| Fila | Contenido |
|---|---|
| 1 | Totales por columna (solo bloques de tienda) |
| 2 | Codigo de tienda (`018`, `046`, `008`, …) — celda combinada sobre 3 columnas |
| 3 | Abreviatura (`HPK JKY`, `HPK PLN`, …) — celda combinada sobre 3 columnas |
| 4 | Encabezados |
| 5+ | Datos |

**226 columnas = 19 fijas + 69 tiendas x 3 metricas** (` VNT`, ` STK`, ` REP`;
los espacios iniciales son parte del encabezado original).

Granularidad de fila: **una fila por LLAVE**, donde

```
LLAVE = Cod. Modelo + "-" + Cod. Color + "-" + Talla/Numero
```

---

## 2. Matriz campo por campo

### 2.1 Columnas fijas (1–19)

| # | Col | Campo Repo Final | Archivo origen | Columna origen | Llave de cruce | Regla / formula |
|---|---|---|---|---|---|---|
| 1 | A | `Marca` | Bodega Gestion / VTA | `Marca` | LLAVE | Valor. Primer no nulo por LLAVE, prioridad Bodega |
| 2 | B | `Clase` | Bodega Gestion / VTA | `Clase` | LLAVE | Valor |
| 3 | C | `Genero` | Bodega Gestion / VTA | `Genero` | LLAVE | Valor |
| 4 | D | `Tipo Prenda` | Bodega Gestion / VTA | `Tipo Prenda` | LLAVE | Valor |
| 5 | E | `Modelo` | Bodega Gestion / VTA | `Modelo` | LLAVE | Valor |
| 6 | F | `Color` | Bodega Gestion / VTA | `Color` | LLAVE | Valor |
| 7 | G | `Cod Modelo` | Bodega Gestion / VTA | `Cod. Modelo` | LLAVE | Valor (se quita el apostrofe del export) |
| 8 | H | `Cod Color` | Bodega Gestion / VTA | `Cod. Color` | LLAVE | Valor |
| 9 | I | `Talla/Numero` | Bodega Gestion / VTA | `Talla/Numero` | LLAVE | Valor |
| 10 | J | `Temporada Comercial` | Bodega Gestion / VTA | `Temporada Comercial` | LLAVE | Valor; vacio → `(en blanco)` |
| 11 | K | `SKU` | **Stock CD** (hoja `CD`) | `ID Producto` | LLAVE | `=VLOOKUP(G5&"-"&H5&"-"&I5,CD!$A:$X,19,0)` → deja `#N/A` a la vista |
| 12 | L | `TRASPASOS DE TEMPORADA` | hoja `LLAVES` col. Q:R | `Traspaso a INV26` | `Cod Modelo-Cod Color` | `=IFERROR(VLOOKUP($G5&"-"&$H5,TRSPINV26,2,0),"-")` |
| 13 | M | `REPOSICIÓN` | — *(calculada)* | — | — | `=V5+Y5+AB5+…` **suma las 69 columnas REP** |
| 14 | N | `NVO DSP CD` | — *(calculada)* | — | — | `=S5+P5-M5` → **DSP + RT − lo ya repuesto** |
| 15 | O | `ECOM` | Stock CD | `Reserva eCommerce` | LLAVE | `=IFERROR(VLOOKUP(…,CD!$A:$X,18,0),0)` |
| 16 | P | `RT` | Stock CD | `Res. Retail` | LLAVE | `…,20,0` |
| 17 | Q | `WS` | Stock CD | `Res. Wholesale` | LLAVE | `…,21,0` |
| 18 | R | `MM` | Stock CD | `Res. Multicanal` | LLAVE | `…,22,0` |
| 19 | S | `DSP` | Stock CD | `Disponible` | LLAVE | `…,23,0` |

### 2.2 Bloques por tienda (T … HR)

| Campo Repo Final | Archivo origen | Columna origen | Llave de cruce | Regla aplicada |
|---|---|---|---|---|
| `<TIENDA> VNT` | **VTA** + Bodega | `Unidades` | LLAVE + `Tienda` | `SUMA` por (LLAVE, tienda). Celda **vacia** si el par no existe |
| `<TIENDA> STK` | **Bodega Gestion** | `Stock − Transito − Reserva eC. − Merma − 2da calidad` | LLAVE + `Tienda` | `SUMA` por (LLAVE, tienda). Celda **vacia** si el par no existe |
| `<TIENDA> REP` | — | — | — | **Columna de captura del planner.** Se entrega vacia (ver 3.3) |

El codigo de tienda se cruza **normalizado sin ceros a la izquierda**: la plantilla
usa `018` y los exports usan `18`.

### 2.3 Filas de encabezado (formulas)

| Celda | Formula | Que hace |
|---|---|---|
| `T1 … HR1` | `=SUBTOTAL(9,T5:T{ultima})` | Total que **respeta el autofiltro** (no `SUMA`) |
| `M1`, `N1` | `=SUBTOTAL(9,M5:M{ultima})` | *Agregado nuestro*: tablero de lo repuesto y del disponible restante |
| `T2 … HR2` | `=VLOOKUP(T3,TIENDA,2,0)` | Codigo de tienda, buscado a partir de la abreviatura de la fila 3 |
| `T3 … HR3` | valor | Abreviatura, repetida en las 3 columnas del bloque (**sin combinar celdas**) |

---

## 2bis. El libro es vivo: hojas de apoyo y rangos con nombre

Sin estas hojas los BUSCARV del REPO se rompen. La app las genera siempre:

| Hoja | Para que sirve | Rango con nombre |
|---|---|---|
| `CD` | Stock CD con `LLAVE` en la columna A (`=H2&"-"&J2&"-"&L2`) | `CD` = `CD!$A:$X` |
| `TIENDAS2` | `D:E` = ABREV → COD TI, que alimenta la fila 2 | `TIENDA` = `TIENDAS2!$D:$E` |
| `LLAVES` | `Q:R` = llave → `T` de traspasos de temporada | `TRSPINV26` = `LLAVES!$Q:$R` |
| `TIENDAS` | Maestro con la letra de columna VNT/STK/REP de cada tienda | `ORDEN`, `ABREV` |
| `EN CAMINO` | Pedidos que salieron del CD y aun no llegan, por SKU y tienda | — |
| `CUADRE` | Conciliacion unidad por unidad (ver seccion 5) | — |
| `DATA` | Tabla larga de auditoria (opcional, ~140 mil filas) | — |

**El orden de columnas de la hoja `CD` es critico**: los indices 18, 19, 20, 21,
22 y 23 de los BUSCARV apuntan a `Reserva eCommerce`, `ID Producto`,
`Res. Retail`, `Res. Wholesale`, `Res. Multicanal` y `Disponible`. La columna
nueva `Res. MarketPlace` que trae el export actual se escribe al final (X) para
no correr los indices.

### Formato replicado celda por celda

| Zona | Relleno | Fuente |
|---|---|---|
| Fila 2 (codigo de tienda), toda la banda | `#FCE4D6` | rojo negrita |
| Columna `REP` de cada tienda (filas 2 en adelante) | `#FCE4D6` | rojo negrita |
| `REPOSICIÓN` y `NVO DSP CD`, filas 1–3 | `#9DF9A4` | rojo negrita |
| `REPOSICIÓN` y `NVO DSP CD`, fila 4 en adelante | `#00FF99` | rojo negrita |
| Encabezado `TRASPASOS DE TEMPORADA` | `#00B0F0` | negro negrita, texto vertical |
| Resto | sin relleno | negro |

Ademas: Calibri 11, zoom 55 %, paneles inmovilizados en fila 4 / columna 19,
autofiltro en `A4`, y los anchos y alturas exactos de la plantilla
(fila 3 = 89,4 · fila 4 = 94,8).

---

## 3. Cadena de transformacion (lo que hoy se hace a mano)

```
VTA .txt  ──┐
            ├──►  hoja DATA (formato largo, 137.618 filas)
BODEGA .txt ┘        · LLAVE   = CodModelo-CodColor-Talla
                     · STK     = Stock − Transito
                     · ORDEN / ABREVIATURA  ← BUSCARX en hoja TIENDAS
                              │
                              ▼
                    tabla dinamica  ──►  hoja DINAMICA
                     filas   = 10 atributos del producto
                     columnas= tienda × (VNT / STK / REP)
                              │
STOCK CD .xlsx ───────────────┤  BUSCARX por LLAVE
                              │   → SKU, ECOM, RT, WS, MM, DSP, NVO DSP CD
hoja LLAVES (manual) ─────────┤  BUSCARX por CodModelo-CodColor
                              │   → TRASPASOS DE TEMPORADA
EVOLUCION + DETALLADO ────────┘  cruce por Nro. Pedido + tienda + LLAVE
                              │   → REP
                              ▼
                          hoja REPO
```

### 3.1 Limpiezas obligatorias en cada fuente

| Fuente | Limpieza |
|---|---|
| VTA `.txt` | UTF-8 con BOM, separador `;`. Quitar la **fila TOTAL** final. Quitar el apostrofe `'` que antepone el ERP a los codigos |
| Bodega `.txt` | Igual. Ademas, las filas del CD vienen con `Nombre Tienda` **vacio** y `Tienda = 320` |
| Stock CD `.xlsx` | Quitar la fila **`TOTAL INFORME`** final |
| Evolucion `.xlsx` | Corregir encabezados invertidos (ver 4.1) |
| Detallado `.xlsx` | `Tienda / Cliente` viene como `"008 HP JOCKEY"`; el codigo son los digitos iniciales. Los clientes mayoristas traen RUC de 11–12 digitos y no son tiendas |

### 3.2 Filtros del REPO

* Se excluye `Clase = DESPACHOS` y `Marca = OTROS` (el pseudo-producto **FLETE**,
  `OT4101018-000-0`). En el snapshot del 18-08 eran 890 filas.
* Solo se muestran las **69 tiendas** con columna en el REPO. Quedan fuera:
  CD 320, BODEGA 340, POS VIRTUAL, BODEGA ECOMMERCE, VIRTUAL PARFOIS,
  BBG JOCKEY 2, BBG MEGAPLAZA, JANSPORT, HP TACNA, HP SAN ISIDRO,
  HP CENTRO CIVICO, HPK SAN BORJA.

### 3.3 `REP` es la columna de captura, no un dato calculado

Las formulas `M` y `N` lo dejan claro:

```
REPOSICIÓN  M5 = V5+Y5+AB5+…      suma de las 69 columnas REP de la fila
NVO DSP CD  N5 = S5+P5-M5         = DSP + RT - REPOSICIÓN
```

Es decir: **al escribir en `REP` de cualquier tienda, `REPOSICIÓN` sube y
`NVO DSP CD` descuenta el disponible del CD en tiempo real.** Por eso la columna
esta en cero en la plantilla: es la entrada del planner.

Por defecto la app la entrega **vacia**. Opcionalmente puede precargarse con lo
que ya viene en camino, cruzando `DETALLADO` con `EVOLUCION`:

| Modo | Definicion |
|---|---|
| `vacio` *(por defecto)* | `REP` en blanco, igual que la plantilla |
| `pendiente_recepcion` | Pedidos **Aprobado** → `Unid. Pendientes`; **Despachado** → `Unid. Despachadas`. Excluye `Recepcionado` |
| `despachado_no_recibido` | Solo estado **Despachado** → `Unid. Despachadas` |
| `transito_bodega` | Columna `Transito` de Bodega Gestion, sin cruzar pedidos |

En **todos** los modos el detalle de lo que viene en camino se escribe en la hoja
`EN CAMINO`, para consultarlo sin ensuciar la columna de captura.

### 3.4 Aviso de sobre-reposicion (agregado)

La plantilla original no tiene formato condicional. La app agrega una unica
regla, desactivable: si `NVO DSP CD` queda **negativo** (repusiste mas de lo que
hay en el CD), la celda se pinta de rojo. Ademas `M1` y `N1` muestran, con
`SUBTOTAL`, el total repuesto y el disponible restante segun el filtro activo.

---

## 4. Inconsistencias detectadas

### 4.1 EVOLUCION trae dos columnas invertidas — **critico**

En `EVOLUCION.xlsx` los encabezados `Unid. Despachadas` y `Unid. Pendientes`
estan intercambiados respecto de su contenido real.

Comprobacion: `Fill Rate = Despachadas / Pedidas` se cumple en **0 de 943** filas
con los encabezados tal como vienen, y en **940 de 943** si se intercambian.

Ejemplos:

| Nro. Pedido | Estado | Pedidas | col. "Despachadas" | col. "Pendientes" | Fill Rate |
|---|---|---|---|---|---|
| 1068125 | Aprobado | 175 | 175 | 0 | 0,00 |
| 1068124 | Despachado | 10 | 0 | 10 | 1,00 |

Un pedido *Aprobado* no puede tener 175 unidades despachadas con fill rate 0.
La app **detecta y corrige** esta inversion automaticamente.

### 4.2 71 % de los SKU quedan con `#N/A` en la columna SKU

20.564 de 29.369 filas del REPO original tienen `#N/A`. No es un error de la
plantilla: `STOCK CD` solo lista lo que **hoy** hay en el centro de distribucion
(8.955 llaves), mientras el REPO incluye todo lo que existe en tienda. Es
esperable y la app lo reporta como advertencia, no como falla.

### 4.3 `TRASPASOS DE TEMPORADA` depende de una lista manual

El valor `T` **no** proviene de ninguno de los 5 archivos: sale de la hoja
`LLAVES` (columnas Q:R) de la plantilla, mantenida a mano. Son 411 claves
`CodModelo-CodColor`.

Verificacion: la lista reproduce las 1.306 marcas `T` con **0 falsos positivos y
0 falsos negativos**. La hoja `TRAS TEMP` (que parece cumplir el mismo rol) solo
explica 89 de las 1.306.

La app trae la lista precargada en `data/catalogos.json` y permite editarla desde
la barra lateral.

### 4.4 `NVO DSP CD` no era una copia de `DSP`

En la primera lectura parecia una copia con 75 excepciones manuales. La formula
real lo explica: `N = S + P − M` = `DSP + RT − REPOSICIÓN`. Como en la plantilla
del 18-08 toda la columna `REP` esta en cero, `M = 0` y la columna coincide con
`DSP` **salvo en las filas con `RT` distinto de cero** — que son exactamente esas
75. No hay ningun ajuste manual.

Ejemplo: `2062521-IN9-050` tiene `DSP = 0` y `RT = 12`, y la plantilla muestra
`NVO DSP CD = 12`.

### 4.5 Duplicados y filas basura

| Hallazgo | Detalle |
|---|---|
| Fila `TOTAL` | VTA y Bodega Gestion terminan con una fila de totales; si no se elimina, duplica el stock global (483.142 unidades de mas) |
| Fila `TOTAL INFORME` | Idem en Stock CD |
| Hoja `CD` de la plantilla | 11.541 filas con solo 8.806 llaves unicas: quedaron restos de pegados anteriores. El archivo `STOCK CD.xlsx` fresco no tiene duplicados |
| Tiendas sin nombre | 9.710 filas del CD en Bodega Gestion vienen con `Nombre Tienda` vacio |
| Stock negativo | 169 filas con stock negativo (ajustes de inventario); se respetan tal cual |

### 4.6 Pedidos sin estado

1.616 pedidos del Detallado no aparecen en Evolucion (ecommerce y wholesale, que
no pasan por reposicion Retail). De esos, 1.514 van a tiendas del REPO y por lo
tanto **no suman a REP**. La app lo reporta con el detalle por pedido.

### 4.7 Orden de filas y mayusculas del `Modelo`

El orden de filas de la plantilla proviene del orden interno de la tabla
dinamica de Excel, que no es alfabetico ni reproducible desde los archivos
fuente. La app usa un orden deterministico equivalente:
Marca → Clase → Genero → Tipo Prenda (con las listas personalizadas de la
plantilla) → Modelo → Color → Cod Modelo → Cod Color → Talla (orden natural).

Del mismo modo, la dinamica agrupa `Modelo` sin distinguir mayusculas y conserva
una capitalizacion arbitraria: 863 filas difieren solo en mayusculas/minusculas.
El texto es el mismo.

### 4.8 Universo de filas: VTA + BODEGA + CD

La plantilla arma las filas desde la dinamica de `DATA`, o sea desde las llaves
que aparecen en **VTA** o en **BODEGA GESTION**. Un SKU recien recepcionado en
el CD todavia no tiene venta ni stock en tienda: con esa regla no genera fila y
su disponible nunca llega al planner.

Por eso el motor agrega tambien **las llaves del `STOCK CD` que traen unidades**
(disponible o cualquier reserva distinta de cero) y no estan en ninguno de los
dos archivos de movimiento. Se les aplican las mismas exclusiones que a `DATA`
(`Clase = DESPACHOS`, `Marca = OTROS`, filas sin codigo de modelo), llegan con
`VNT`, `STK` y `REP` vacios, y casi siempre sin `Temporada Comercial` asignada,
por lo que se muestran como `(en blanco)`.

Con los archivos del 26-08-2026 fueron **92 filas / 1.410 pares** (todas VANS:
UPLAND, SUPER LOWPRO, RANGE EXP, LX AUTHENTIC 44, LX OLD SKOOL 36, LARKSPUR,
AUTHENTIC CHINO, QUEENS HIGH PILE y VANS X ROWAN STRIPE). La app las lista
aparte con la alerta **"SKU con stock solo en el CD"**.

---

## 5. Como saber que cuadra

Cada corrida genera la hoja `CUADRE` (y la pestaña equivalente en la app) con
esta identidad de control:

```
unidades del archivo  =  unidades en el REPO  +  excluidas por regla  +  sin explicar
```

La columna **`Sin explicar` debe estar en cero**. Si no lo esta, hay unidades que
se perdieron en el camino y la fila se marca `NO`.

Resultado con los archivos de agosto 2026:

| Concepto | En el archivo | En el REPO | Excluidas por regla | Sin explicar | Cuadra |
|---|---|---|---|---|---|
| Venta (VNT) | 37.400 | 30.791 | 6.609 | **0** | SI |
| Stock disponible (STK) | 471.721 | 208.418 | 263.303 | **0** | SI |
| Pedidos en camino | 5.285 | — | — | **0** | SI |
| Disponible en el CD (DSP) | 281.440 | 281.440 | 0 | **0** | SI |
| Filas (SKU unicos) | 30.493 | 30.493 | 0 | **0** | SI |

Las exclusiones estan desglosadas: 2.434 unidades de `Clase = DESPACHOS`,
4.175 en tiendas sin columna en el REPO, 263.303 de stock en el CD 320 y demas
bodegas fuera del REPO.

Ademas se compara **tienda por tienda**: el total de cada columna `VNT` y `STK`
contra el mismo total calculado desde el archivo fuente. Las 69 cuadran con
diferencia cero.

> Este control ya encontro un caso real: el archivo `BODEGA GESTION` tambien
> trae unidades vendidas (2 en el periodo de agosto), que la plantilla suma junto
> con las del archivo de venta. Sin el cuadre habrian pasado inadvertidas.

### 5.1 La linea `Disponible en el CD (DSP)`

Es la que protege el armado: todo par disponible en el CD tiene que estar en una
fila de la tabla. Hasta la corrida del 16-09-2026 no existia, y por eso paso
inadvertido un descuadre real: la tabla mostraba **280.030** pares disponibles
contra **281.440** del archivo `STOCK CD`, **1.410 pares menos**.

La causa es el universo de filas (seccion 4.8): 92 llaves VANS recien
recepcionadas en el CD no tenian venta ni stock en tienda, asi que no generaban
fila y su disponible quedaba invisible para la reposicion. Las reservas
(`ECOM`, `RT`, `WS`, `MM`) si cuadraban, porque esas llaves venian con reserva
cero: el unico sintoma era el `DSP`.

---

## 6. Validacion contra la plantilla original

Reconstruccion del REPO original a partir de las hojas `DATA` y `CD` de la
propia plantilla, comparando **celda por celda**:

| Bloque | Celdas comparadas | Diferencias |
|---|---|---|
| Filas (llaves) | 29.369 | **0** — mismo conjunto exacto |
| `Marca`, `Clase`, `Genero`, `Tipo Prenda` | 117.476 | **0** |
| `Color`, `Cod Modelo`, `Cod Color`, `Talla/Numero`, `Temporada Comercial` | 146.845 | **0** |
| `SKU` | 29.369 | **0** |
| `TRASPASOS DE TEMPORADA` | 29.369 | **0** |
| `REPOSICIÓN`, `ECOM`, `RT`, `WS`, `MM` | 146.845 | **0** |
| `DSP` | 29.369 | 2 (celdas vacias en el original) |
| `NVO DSP CD` | 29.369 | 75 (ajustes manuales, ver 4.4) |
| `Modelo` | 29.369 | 863 (solo mayusculas, ver 4.7) |
| **` VNT` por tienda** | **2.026.461** | **0** |
| **` STK` por tienda** | **2.026.461** | **0** |

Total de unidades de stock reconstruido: **209.215**, identico al total de la
plantilla.

Reglas confirmadas sobre el 100 % de las filas:

* `LLAVE = Cod. Modelo-Cod. Color-Talla/Numero` — 0 diferencias en 137.618 filas
* `STK = Stock − Transito` — 0 diferencias en 137.618 filas
* `DSP/ECOM/RT/WS/MM ← Stock CD` por LLAVE — 0 diferencias en 67.076 cruces
