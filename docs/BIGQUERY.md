# Conexion a BigQuery

Reemplaza la subida manual del archivo de venta por una consulta con rango de
fechas, y llena el directorio de SKU desde ARTI.

**No hay que configurar nada nuevo**: usa los mismos bloques `[bigquery]` y
`[gcp_service_account]` que ya tiene el Catalogo Control Center.

---

## 1. Que pasa a BigQuery y que se sigue subiendo

| Dato | Origen | Por que |
|---|---|---|
| **Venta** | 🟢 BigQuery, por rango de fechas | `silver.ft_pe_reporteria_ventas_tablon` |
| **ID Producto / codigos de barra** | 🟢 BigQuery (ARTI) | `bronze.stg_pe_central_arti` |
| **Stock CD** | 🔵 Se sigue subiendo | La tabla necesita el stock **del momento** |
| **Bodega Gestion** | 🔵 Se sigue subiendo | Idem: es una foto, no un historico |
| **Detallado de pedidos** | 🟢 BigQuery, por rango de fechas | `bronze.stg_pe_perucentral_pedidos_detail` |
| **Evolucion de pedidos** | 🟢 BigQuery, por rango de fechas | `bronze.stg_pe_perucentral_pedidos_header` |
| **Traspasos (hoja guias)** | 🔵 Se sigue subiendo | Pendiente de tener la tabla |

Las dos tablas de pedidos alimentan la columna `REP` de la Tabla de Repo y el
**Dashboard de Pedidos** (seccion 6). En el paso de carga aparece el selector
*Origen de los pedidos*: subir los dos Excel, o traerlos por rango de fechas.
Si una tabla falla, el camino del Excel sigue disponible sin tocar nada.

Los nombres por defecto se pueden cambiar en los secrets sin tocar codigo:

```toml
[bigquery]
pedidos_header_table = "otro-proyecto.otro_dataset.mi_tabla_header"
pedidos_detail_table = "otro-proyecto.otro_dataset.mi_tabla_detail"
```

Dos avisos que ahorran un rato de depuracion:

- **No repitas el encabezado `[bigquery]`.** Las lineas van dentro del bloque
  que ya existe; TOML rechaza la clave duplicada y la app se queda sin conexion.
- **Si no hacen falta, no las pongas.** Dejarlas con el texto de ejemplo
  (`PROYECTO.DATASET....`) hace que BigQuery responda *Invalid project ID*. La
  app detecta ese caso y lo dice en pantalla, pero lo correcto es borrar las dos
  lineas y quedarse con los nombres por defecto.

---

## 2. Control de costo

BigQuery cobra por bytes leidos, asi que el modulo tiene tres defensas:

1. **Filtro de fecha en el `WHERE`**, siempre parametrizado
   (`WHERE DATE(fecha) BETWEEN @desde AND @hasta`). Nunca se escanea el tablon
   entero.
2. **Agregacion en el servidor** (`GROUP BY`): baja el resultado, no el detalle.
   Con la venta de enero a agosto 2026, el TXT tiene 30.837 filas y la consulta
   devuelve 25.620 ya agregadas.
3. **Dry run antes de ejecutar**: la app calcula cuantos GB va a leer y **no
   ejecuta** si supera el tope (20 GB por defecto, editable en pantalla).
   El consumo real se muestra en pantalla despues de cada consulta.

Nunca se usa `SELECT *`.

---

## 3. Mapeo de columnas

La app **no asume** los nombres de columna del tablon. La primera vez:

1. Lee `INFORMATION_SCHEMA.COLUMNS` (es gratis y no toca los datos).
2. Empareja cada campo que necesita con la primera columna que coincida por
   alias (`fecha`, `fecha_venta`, `fec_doc`, `fecha_documento`, …).
3. Muestra el mapeo para que lo revises y lo corrijas si hace falta.
4. Al guardar, queda en `data/bq_mapping.json` y no vuelve a preguntar.

Campos obligatorios: `fecha`, `unidades`, algo que identifique la tienda
(codigo o nombre) y algo que identifique el producto (ID Producto o Cod. Modelo).
El resto son opcionales y enriquecen el resultado.

---

## 4. Directorio de SKU desde ARTI

Es la solucion definitiva al `#N/A` de la columna SKU (hoy 65 % de las filas).
El boton *Traer SKUs de ARTI* resuelve por dos caminos, segun lo que tenga la
tabla:

* **Camino 1** — si ARTI trae modelo-color y talla, la llave se arma directo.
* **Camino 2** — si no, se puentea por codigo de barras: ARTI da
  `barra → ID Producto` y el archivo de bodega da `LLAVE → barra`.

En ambos casos el resultado se guarda en `data/sku_directory.json`, asi que el
avance no se pierde.

---

## 5. Verificacion

La Tabla de Repo generada con la venta de BigQuery es **identica** a la generada
con el TXT:

| | TXT | BigQuery |
|---|---|---|
| Filas del REPO | 30.493 | 30.493 |
| Unidades VNT | 30.791 | 30.791 |
| Unidades STK | 208.418 | 208.418 |
| Diferencia celda a celda | — | **0** |

Tambien se verifico que el mapeo automatico funciona con nombres alternativos
(`fec_doc`, `cod_local`, `desc_local`, `codint_ma`, `cant_venta`, `talla_desc`)
y que sin secrets la app degrada limpio a la subida de archivos.

---

## 6. Dashboard de Pedidos

Modulo **Dashboard de Pedidos** en la navegacion lateral. Reproduce el reporte
de BI de pedidos contra BigQuery, sin exportar nada a mano.

### Como se calcula

Todo sale del **detalle** (la linea del pedido, que es la que trae producto y
tienda) enriquecido con los atributos de la **cabecera** cruzando por numero de
pedido. Agregar por la cabecera contaria cada pedido una vez en vez de cada
par, y las cifras no calzarian con el BI.

| Indicador | Formula |
|---|---|
| Cantidad Pedida | `SUM(unidades pedidas)` |
| Cantidad Despachada | `SUM(unidades despachadas)` |
| Var Pedidos | pedida − despachada |
| % Cumplimiento | despachada / pedida |

### Filtros

Tipo de Pedido, Tipo de Cadena, Ciudad, Marca, Tienda, Cod Mod Col, Tipo Prenda
y Estado. Vacio significa *todas*, igual que los slicers del BI. **Los filtros
trabajan en memoria**: se consulta BigQuery una sola vez por periodo y filtrar
despues no vuelve a cobrar.

Cada filtro aparece solo si su columna existe en las tablas y trae datos, asi
que el tablero no se rompe si el staging cambia.

### La cadena no sale del tablon

`Tipo de Cadena` se deriva del **maestro de tiendas** (`data/catalogos.json`)
usando el codigo de tienda, no de una columna de staging: el codigo es estable
y el nombre de cadena no siempre. La bodega 320 se muestra como `BOD 320`, que
es el CD y no una tienda de la cadena. Si el tablon trae su propia columna de
cadena, esa manda.

### Mapeo de columnas

Las dos tablas son de staging, asi que los nombres de columna no se asumen: se
descubren con `INFORMATION_SCHEMA` y se emparejan por alias, igual que el
tablon de ventas. Lo que no se reconozca se corrige una vez en pantalla y queda
guardado en `data/bq_mapping.json`.

Minimo indispensable: `nro_pedido` y `estado` en la cabecera; `nro_pedido`,
`unid_pedidas` y algo que identifique el producto en el detalle. Sin `fecha` en
la cabecera no se puede acotar el periodo y la consulta se rechaza antes de
ejecutarse.

### Sacar los datos

Al pie del tablero hay dos caminos, y **ambos respetan los filtros que tengas
puestos**: lo que se descarga es exactamente lo que estas mirando.

| Formato | Que trae |
|---|---|
| **Excel** | Libro completo: Resumen con los cuatro KPIs, una hoja por vista (tienda, cadena, marca, clasificacion), la matriz Tipo x Estado, la evolucion por mes y semana, y el detalle linea a linea. El % de cumplimiento va en semaforo. |
| **CSV** | Una sola vista, la que elijas en el desplegable, o el detalle completo. Sale en UTF-8 con BOM para que Excel respete los acentos al abrirlo de un doble clic. |

La hoja de lineas corta en 200 mil filas: por encima de eso Excel se vuelve
inmanejable y el libro lo dice en la propia hoja. Para el detalle completo, CSV.
