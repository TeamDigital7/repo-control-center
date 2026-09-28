# Producto Control Center

App en Streamlit con cuatro modulos para el area de Producto. La navegacion es
lateral, por tarjetas; los ajustes de cada modulo viven dentro de su pantalla.

```
Inicio · Tabla de Repo · Llenados de Canal · Analisis de Efectividad
```

### 🏠 Inicio

Estado de la sesion (que archivos hay cargados, que ya se calculo) y accesos a
los modulos.

### 🔌 BigQuery (opcional)

Si estan los secrets, la **venta** deja de subirse a mano: se elige un rango de
fechas y la app la trae de la tabla de venta configurada en los secrets, agregada en
el servidor y con dry run previo para controlar el costo. El **maestro ARTI**
llena el directorio de SKU de una vez.

El stock (CD y Bodega Gestion) se sigue subiendo porque la tabla necesita la foto
del momento, no un historico. Ver [`docs/BIGQUERY.md`](docs/BIGQUERY.md).

### 📦 Tabla de Repo

Arma la **Tabla de Repo Final** a partir de los 5 reportes de siempre, con la
misma estructura, nombres, formulas y formato que la plantilla `.xlsb` que hoy
se construye a mano.

```
Subir 5 archivos  →  Validar  →  Procesar cruces  →  Revisar errores  →  Descargar Excel
```

No hay que configurar mapeos: las reglas estan programadas y verificadas contra
la plantilla original (ver [`docs/MAPEO_REPO.md`](docs/MAPEO_REPO.md)).

Dentro de la pantalla, en tabs:

| Tab | Que resuelve |
|---|---|
| **Generar Tabla Repo** | El flujo de 5 pasos y el libro de salida |
| **Tallas unicas** | De que modelos queda una sola talla en cada tienda |
| **Stock critico** | Modelos cuyo stock total en la tienda esta al limite |
| **Control SE / FB / DH** | Lo mismo, vigilado aparte para los canales de liquidacion |

El analisis de curva usa la foto de stock de `BODEGA GESTION` que ya se cargo
para el REPO: no hay que subir nada extra. Cada tab filtra y descarga a Excel.

### 🚚 Llenados de Canal

Reparte una orden de compra entre tiendas: detecta las columnas marcadas con `X`,
interpreta curvas tipo `1-2-2-2-1` y arma el llenado por SKU, talla y tienda.
Nunca reparte mas de lo que trae la OC. Preview antes de descargar.
Ver [`docs/LLENADO_DE_CANAL.md`](docs/LLENADO_DE_CANAL.md).

### 📈 Efectividad de traspasos

Dashboard ejecutivo que mide si lo enviado a cada tienda efectivamente se
vendio ahi, con la venta atribuible **topeada al traspaso**. Incluye medidor de
efectividad, rankings de tiendas y modelos, evolucion, semaforo, cortes a
7/14/30 dias y un reporte Excel de 6 hojas listo para presentar.

Reproduce el analisis manual con 0 diferencias en 30.262 filas.
Ver [`docs/EFECTIVIDAD.md`](docs/EFECTIVIDAD.md).

---

## Que hace

* **Lee los 5 reportes tal como salen del ERP** (`.txt` con `;` y BOM, `.xlsx`,
  `.xlsb`), quita filas `TOTAL`, apostrofes y separadores raros.
* **Detecta si un archivo va en la casilla equivocada** comparando su estructura.
* **Corrige la inversion de columnas de `EVOLUCION.xlsx`** (`Unid. Despachadas`
  y `Unid. Pendientes` vienen intercambiadas en el export).
* **Ejecuta todos los cruces**: apila venta + bodega, calcula
  `STK = Stock − Transito − Reserva eC. − Merma − 2da calidad`, pivotea por las
  69 tiendas y arma los BUSCARV contra `STOCK CD`.
* **Cuenta lo ya enviado como stock de la tienda**: los pedidos del `DETALLADO`
  que segun `EVOLUCION` siguen *Aprobados* o *Despachados* (aun no recepcionados)
  se suman al `STK` de su tienda, asi no se vuelven a reponer. Si el SKU todavia
  no existe en la tienda, aparece como fila nueva. Se puede apagar en *Ajustes*.
  El cruce por pedido tolera ceros a la izquierda, `.0` de Excel y estados en
  mayusculas o sin tilde.
* **Entrega un libro vivo, no un volcado**: la hoja `REPO` sale con sus formulas,
  sus hojas de apoyo y sus rangos con nombre, asi que al escribir en `REP` la
  columna `REPOSICIÓN` suma y `NVO DSP CD` descuenta el disponible del CD.
* **Replica el formato celda por celda**: mismos sombreados (durazno en `REP`,
  verde en las calculadas, celeste en `TRASPASOS`), anchos, alturas, zoom 55 %,
  paneles inmovilizados y autofiltro.
* **Cuadra el resultado**: hoja y pestaña `CUADRE` donde cada unidad del archivo
  esta en la tabla o explicada por una regla. La columna *Sin explicar* debe dar
  cero.
* **Muestra solo errores relevantes**: sin match, duplicados, campos criticos
  vacios, pedidos sin estado, tiendas fuera del REPO.

## Formulas que quedan vivas en la hoja REPO

| Celda | Formula |
|---|---|
| `T1 … HR1` | `=SUBTOTAL(9,T5:T{n})` — total que respeta el autofiltro |
| `M1`, `N1` | `=SUBTOTAL(9,M5:M{n})` — tablero de lo repuesto y del disponible restante |
| `T2 … HR2` | `=VLOOKUP(T3,TIENDA,2,0)` — codigo de tienda |
| `K` SKU | `=VLOOKUP(G5&"-"&H5&"-"&I5,CD!$A:$X,19,0)` |
| `L` TRASPASOS | `=IFERROR(VLOOKUP($G5&"-"&$H5,TRSPINV26,2,0),"-")` |
| `M` REPOSICIÓN | `=V5+Y5+AB5+…` — suma de las 69 columnas `REP` |
| `N` NVO DSP CD | `=S5+P5-M5` — **DSP + RT − lo ya repuesto** |
| `O`…`S` | `=IFERROR(VLOOKUP(…,CD!$A:$X,18\|20\|21\|22\|23,0),0)` |

**La columna `REP` es tu columna de captura** y se entrega vacia, igual que la
plantilla. Opcionalmente se puede precargar con lo que ya viene en camino.

## Hojas del libro de salida

| Hoja | Contenido |
|---|---|
| `REPO` | La tabla final, con formulas y formato |
| `CD` | Stock CD con `LLAVE` en la columna A — alimenta todos los BUSCARV |
| `SKUS` | Directorio acumulado `LLAVE → ID Producto` (rango `SKUS`) |
| `TIENDAS2` | `D:E` = ABREV → COD TI (rango con nombre `TIENDA`) |
| `LLAVES` | `Q:R` = traspasos de temporada (rango `TRSPINV26`) |
| `TIENDAS` | Maestro con la letra de columna VNT/STK/REP de cada tienda |
| `EN CAMINO` | Pedidos que salieron del CD y aun no llegan, por SKU y tienda |
| `CUADRE` | Conciliacion unidad por unidad y tienda por tienda |
| `DATA` | Tabla larga de auditoria (opcional, ~140 mil filas) |

## Directorio de SKU

`STOCK CD` solo lista lo que **hoy** esta fisicamente en el centro de
distribucion (~9 mil de las ~30 mil llaves del REPO). Por eso la plantilla deja
`#N/A` en el 70 % de la columna `SKU`.

La app mantiene `data/sku_directory.json`, un directorio `LLAVE → ID Producto`
que **se llena solo**: cada corrida cosecha los ID que traen el `STOCK CD` y el
`DETALLADO DE PEDIDOS` y los guarda para siempre. La formula de la columna `K`
usa el CD primero y el directorio como respaldo:

```excel
=IFERROR(VLOOKUP(llave,CD!$A:$X,19,0),IFERROR(VLOOKUP(llave,SKUS,2,0),NA()))
```

| Fuente | Cobertura |
|---|---|
| Solo `STOCK CD` del dia (como la plantilla) | 29,4 % |
| + directorio acumulado | **35,1 %** y creciendo cada semana |

**Para llenarlo de una vez**: en la barra lateral, *Directorio de SKU → Ampliar
de golpe con un maestro*. Acepta cualquier export con `ID Producto` +
`Cod. Modelo` + `Cod. Color` + `Talla`. Con un maestro de productos completo, la
columna `SKU` queda al 100 % de forma permanente.

> En Streamlit Cloud el disco es efimero. Usa *Descargar directorio (.json)* y
> reemplaza `data/sku_directory.json` en el repo para conservar el avance.

## Estructura del proyecto

```
app.py                     entrypoint de Streamlit (login + wizard de 5 pasos)
repo_engine/
  config.py                reglas, constantes y contratos de datos
  catalogs.py              69 tiendas, traspasos de temporada, ordenes personalizados
  sku_directory.py         directorio persistente LLAVE → ID Producto
  readers.py               lectura y normalizacion de cada fuente
  validation.py            validacion estructural y cruzada
  transform.py             motor de cruces: DATA → pivote → REPO
  reconcile.py             cuadre unidad por unidad
  diagnostics.py           deteccion de incidencias
  excel_writer.py          exportador del libro vivo (formulas + formato)
  bq.py                    lectura desde BigQuery (venta por rango, ARTI)
  pagina_datos.py          conexion, mapeo de columnas y selector de periodo
  tallas.py                analisis de curva rota, stock critico y SE/FB/DH
  llenado.py               motor de reparto de OC por curva
  efectividad.py           motor de efectividad de traspasos
  efectividad_excel.py     reporte de 6 hojas
  charts.py                graficos del dashboard (Altair + SVG)
  icons.py                 iconos SVG en linea (trazados de Lucide)
  pagina_inicio.py         pantalla de inicio
  pagina_tallas.py         tabs de curva dentro de la Tabla de Repo
  pagina_llenado.py        pagina de Llenados de Canal
  pagina_efectividad.py    pagina de Analisis de Efectividad
  auth.py                  login (mismo esquema que el Catalogo Control Center)
  ui.py                    sistema de diseno: navegacion, cards, tabs, chips
data/catalogos.json        69 tiendas + traspasos, extraidos de la plantilla
data/sku_directory.json    directorio acumulado de ID Producto
assets/forus_logo.png      logo institucional
assets/brands/             logos de marca (login)
docs/MAPEO_REPO.md         matriz campo → origen → llave → regla, e inconsistencias
```

## Instalacion local

```bash
pip install -r requirements.txt
```

```bash
streamlit run app.py
```

Abre <http://localhost:8501>.

## Login y secrets

Copia `.streamlit/secrets.example.toml` a `.streamlit/secrets.toml` (o pegalo en
Streamlit Cloud → *Settings* → *Secrets*). Trae la **misma estructura del
Catalogo Control Center**, asi que puedes pegar tus secrets tal cual y solo
editar la lista de usuarios:

```toml
[app_auth]
[app_auth.users]
"admin" = "CAMBIAR_ESTA_CLAVE"
"nombre.apellido@empresa.com" = "CAMBIAR_ESTA_CLAVE"
"otra.persona@empresa.com" = "CAMBIAR_ESTA_CLAVE"
```

Esta app **solo necesita `[app_auth]`**. Los bloques `[bigquery]`,
`[gcp_service_account]` y `[shopify_sites.*]` estan en el ejemplo comentados por
si pegas el archivo completo: se ignoran sin dar error.

Si existe `[app_auth]` en `secrets.toml`, reemplaza a los usuarios por defecto
del codigo. `secrets.toml` esta en el `.gitignore`: **nunca lo subas a GitHub.**

## Deploy en Streamlit Community Cloud

1. Sube el repo a GitHub (el `.gitignore` ya excluye `secrets.toml` y los Excel).
2. En <https://share.streamlit.io> crea la app apuntando a `app.py`.
3. En **Settings → Secrets** pega el contenido de tu `secrets.toml`.

El limite de subida esta en 300 MB por archivo (`.streamlit/config.toml`), suficiente
para `BODEGA GESTION` (~20 MB) y `DETALLADO` (~5 MB).

## Los 5 archivos de entrada

| # | Archivo | Ejemplo | Aporta |
|---|---|---|---|
| 01 | Venta por tienda | `VTA DEL 01 AL 20-08-26.txt` | columnas ` VNT` |
| 02 | Bodega / Gestion | `BODEGA GESTION21.08.txt` | columnas ` STK` + atributos del producto |
| 03 | Stock CD | `STOCK CD.xlsx` | `SKU`, `ECOM`, `RT`, `WS`, `MM`, `DSP`, `NVO DSP CD` |
| 04 | Evolucion de pedidos | `EVOLUCION.xlsx` | estado de cada pedido (filtro de ` REP`) |
| 05 | Detallado de pedidos | `DETALLADO DE PEDIDOS DEL 01 AL 21-08-26.xlsx` | unidades por SKU y tienda (` REP`) |

## Mantenimiento de catalogos

Dos listas viven en `data/catalogos.json` porque **no estan en los 5 archivos**:

* **69 tiendas** con su codigo, abreviatura y orden de columna.
* **411 claves `CodModelo-CodColor`** marcadas como traspaso de temporada (`T`).
  Se editan desde la barra lateral de la app, sin tocar codigo.

## Rendimiento

Con los archivos de agosto 2026 (145 mil filas de movimiento, 39 mil lineas de
pedidos):

| Etapa | Tiempo |
|---|---|
| Lectura de los 5 archivos | ~16 s antes; ahora 4-7x mas rapida (calamine + lector C de pandas) |
| Cruces, pivote y cuadre | ~4 s |
| Escritura del libro con formulas (30.493 x 226) | ~65 s |

El libro pesa ~10 MB. La mayor parte del tiempo se va escribiendo las 30 mil
formulas de `REPOSICIÓN`, que son la suma explicita de las 69 columnas `REP`
igual que en la plantilla. Se mantiene asi a proposito: Excel recalcula solo la
fila que editas, en vez de barrer las 207 columnas en cada cambio.
