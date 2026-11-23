# Complementos

Un complemento añade a IngePresupuestos un país, vocabulario, formatos de Excel,
temas de reportes, reportes o funciones propias. Hay de dos clases:

| | Solo datos | Con código |
|---|---|---|
| Qué es | un `complemento.json` (y un logo, si quieres) | lo mismo más archivos `.py` |
| Qué puede hacer | lo que dice este documento, nada más | **todo lo que puede el programa** |
| Al activarlo | se avisa si cambia datos que ya existen | hay que aceptar que confías en el autor |

Nada se descarga de internet. Todo se instala **apagado**.

- [Instalar y usar](#instalar-y-usar)
- [Tu primer complemento](#tu-primer-complemento) (5 minutos)
- [Tu primer tema](#tu-primer-tema)
- [`complemento.json`](#complementojson)
- [API de Python](#api-de-python)
- [Seguridad](#seguridad)
- [Límites](#límites)

## Instalar y usar

En el proyecto, **Complementos ▾ ▸ Administrar complementos…**; también en
**Configuración ▸ Complementos ▸ Gestionar complementos…**

- **Explorar** enseña los que vienen con el programa; **Instalados**, los tuyos.
  Se buscan (sin tildes ni mayúsculas), se filtran por categoría y se ordenan.
- **Instalar** (o **Instalar .zip…** / **Instalar carpeta…**) lo deja apagado.
- **Actualizar** sale cuando el incluido es de una versión posterior. Como cambia
  el contenido, hay que volver a activarlo.
- **Detalles** enseña la ficha y cada archivo; en **⋯** están Importar índice,
  Recargar, Abrir carpeta y Desinstalar.
- **INCLUIDO** se pone por contenido: un paquete ajeno con el mismo `id` no la lleva.
- **Activar…** enseña autor, licencia, archivos y qué datos cambia.
- **Desactivar** y **Desinstalar** no tocan los proyectos: la moneda que trajo un
  complemento se queda guardada como tuya, el país elegido conserva sus valores y
  un tema que falta se sustituye por el de fábrica, con un aviso.
- **Abrir carpeta** lleva a donde viven: `complementos/` dentro de la carpeta de
  datos del programa.

Solo un administrador gestiona complementos. Los reportes, acciones,
importadores y validadores de los que están activos salen en el menú de
complementos del proyecto; los temas, en **Reportes ▸ Tema**.

Si algo va mal, arranca con `--sin-complementos` (o con la variable
`INGEPPTO_SIN_COMPLEMENTOS=1`): no se carga ninguno.

### Los que vienen incluidos

| Complemento | Clase | Qué trae |
|---|---|---|
| `pais-brasil` | código | CNPJ/CPF, pie en portugués, formato de insumos de SINAPI (sin datos), vocabulario, sitio para el INCC, cálculo del BDI (TCU Ac. 2622/2013), «Composição do BDI» y «Planilha orçamentária» con dos formas de redondear. El BDI se copia a mano al pie |
| `pais-argentina` | código | pesos, CUIT, IVA, «rubro» por «título», el sitio para tu índice CAC (sin valores) y el reporte de materiales / mano de obra: los equipos van en mano de obra y los subcontratos solo se reparten con el % que escribas |
| `pais-espana` | código | «Presupuesto y mediciones» con IVA editable y «Condiciones generales» |
| `pais-honduras` | código | análisis sin cuadrilla, mano de obra en horas o jornales |
| `pais-dominicana` | código | ITBIS sobre materiales (18 % al empezar) |
| `pais-italia` | código | EUR, Analisi dei Prezzi, Computo Metrico Estimativo, Elenco Prezzi Unitari, Quadro Economico y sitio para el índice ISTAT |
| `pu-con-indirectos` | código | presupuesto con el pie repartido en los precios: mismo total, residuo a la vista, impuesto aparte o incluido |
| `apu-chile` | código | APU en bloques A–D, sin cuadrilla ni rendimiento, en pesos enteros; redondeo por línea o solo del precio unitario |
| `reporte-ejemplo` | código | el reporte propio más pequeño posible |
| `apu-mexico` | código | matriz de precio unitario con indirectos, financiamiento, utilidad y cargos en cascada; porcentajes por proyecto, en 0 al empezar; y los auxiliares o básicos |
| `ajustar-total` | código | acción: escala precios del proyecto para llegar a un total, con vista previa; todas las partidas o un capítulo |
| `impuesto-materiales` | código | reporte del impuesto sobre materiales por partida y total |
| `presupuesto-con-datos` | código | presupuesto con los datos del proyecto en la primera página |
| `zapatas` | código | acción: metrado de zapatas por dimensiones y armado, sin precios |
| `tema-sobrio`, `tema-propuesta` | datos | dos temas de reportes |

## Tu primer complemento

**1. Créalo.** En el gestor, **Crear complemento…**; o en una terminal:

```
ingepresupuestos --nuevo-complemento "Mi reporte"
```

Deja una carpeta `mi-reporte/` que ya funciona. Con `--datos`, una sin código.

**2. Instálalo:** Instalar carpeta… → elígela → Activar…. En un proyecto, el menú
de complementos ofrece «Mi reporte: resumen» en PDF y en Excel.

**3. Cámbialo.** Abre `complemento.py`:

```python
from ingepresupuestos import api

def registrar(app):
    app.reporte("caras", "Partidas más caras", generar)

def generar(p):
    caras = sorted(p.hojas(), key=lambda x: -x.parcial)[:20]
    return api.Documento("Partidas más caras", [
        api.Campos([("Proyecto", p.nombre)]),
        api.Tabla([api.Columna("Ítem", 12), api.Columna("Descripción", 60),
                   api.Columna("Parcial", 28, "derecha", p.decimales)],
                  [(x.item, x.descripcion, x.parcial) for x in caras]),
    ])
```

**4. Pulsa Recargar.** Como los archivos cambiaron, pide activarlo otra vez.

**5. Compruébalo y compártelo:**

```
ingepresupuestos --validar-complemento mi-reporte
ingepresupuestos --empaquetar-complemento mi-reporte
```

`prueba.py` enseña a probarlo sin abrir el programa, con un presupuesto de
mentira: `ingepresupuestos.pruebas.presupuesto_ejemplo()`.

En Flatpak el comando es `flatpak run com.ingepresupuestos.IngePresupuestos`, en
Snap `snap run ingepresupuestos` y, desde el código fuente, `python3 main.py`.

## Tu primer tema

Un tema es el aspecto de los reportes. No lleva código.

**Sin escribir nada.** En **Reportes ▸ Tema ▸ Crear tema a partir del actual…**:
ponle nombre, cambia colores, tipografía, márgenes, textos, columnas o firmas,
pulsa **Vista previa** y guarda. Queda elegido en ese proyecto. Desde el mismo
menú se edita y se **exporta como .zip** para pasárselo a otro. Se puede elegir
**para todos los proyectos** (administrador) o **para este proyecto**; lo del
proyecto manda, y viaja con él al exportar el `.db`.

**A mano.** Un `complemento.json` como este, en una carpeta:

```json
{
  "esquema": 1,
  "id": "tema-mio",
  "nombre": "Mi tema",
  "version": "1.0.0",
  "autor": "Yo",
  "licencia": "CC0-1.0",
  "temas": [
    {
      "clave": "mio",
      "nombre": "Mi tema",
      "colores": {"acento": "#0D52BF", "titulos": ["#082A66", "#0D52BF"]},
      "pie": {"izquierda": "{cliente}", "centro": "", "derecha": "{pagina}/{paginas}"}
    }
  ]
}
```

Todo es opcional menos `clave` y `nombre`; lo que no digas sale como de fábrica
(o como lo tengas en «Configurar formato»).

| Campo | Qué admite |
|---|---|
| `colores` | `#RRGGBB`: `marca`, `marca_oscuro` (encabezado y portada), `acento`, `acento_oscuro` (cuerpo), `suave` (fondo de cabeceras), `borde`, `cebra`, `subpresupuesto`; y `titulos`, hasta nueve, uno por nivel |
| `tipografia` | `familia`, `sustituta` (si la primera no está instalada) y `escala`: 100, 90, 80 o 75 |
| `margenes` | `superior`, `inferior`, `izquierdo`, `derecho`, en mm, de 5 a 40 |
| `bordes` | `ninguno`, `finos`, `normales`, `gruesos` |
| `encabezado` | `mostrar` y los textos `titulo`, `linea`, `subtitulo`, `derecha`, `derecha2` |
| `pie` | `mostrar`, `linea` y los textos `izquierda`, `centro`, `derecha`. Un texto vacío quita ese hueco |
| `logo` | `archivo` (un PNG o JPG en la raíz del paquete, hasta 1 MB y 4000 px) y `escala`, de 50 a 200 |
| `nombres` | el título de cada reporte: `{"presupuesto": "Propuesta económica"}` |
| `columnas` | `presupuesto` e `insumos`: qué columnas, en qué orden, con qué `titulo` y `ancho` (pt) |
| `firmas` | hasta cuatro `{"nombre", "cargo"}` al final del presupuesto |

Columnas de `presupuesto`: `descripcion` (con el ítem; va primero), `unidad`,
`cantidad`, `desglose`, `precio`, `parcial`. De `insumos`: `codigo`,
`descripcion`, `unidad`, `cantidad`, `precio`, `parcial`. Si hay `parcial`, va
después de `descripcion`.

Marcadores de los textos: `{proyecto}` `{cliente}` `{ubicacion}` `{costo_al}`
`{modalidad}` `{moneda}` `{empresa}` `{fecha}` `{titulo}` `{pagina}` `{paginas}`.

Un tema no admite HTML, CSS, SVG ni archivos de fuera del paquete.

**En qué reportes.** Todo lo anterior, en los PDF. **Excel, Word y sus versiones
de LibreOffice** toman lo que ya entendían de «Configurar formato»: colores de
marca y de títulos, logo, subtítulo, mostrar u ocultar encabezado y pie, y los
textos del pie sin número de página. No toman tipografía, márgenes, bordes,
columnas ni firmas. El **Gantt y la Curva S** toman encabezado, pie, logo y
colores de marca; exportados desde la vista del cronograma usan el tema general,
no el del proyecto. Un reporte con otra estructura se hace con la API.

## `complemento.json`

Un campo desconocido o mal escrito hace que el paquete no se instale: se dice
cuál.

| Campo | |
|---|---|
| `esquema` | siempre `1` |
| `id` | minúsculas, números y guiones, de 3 a 40: `pais-brasil` |
| `nombre`, `version`, `autor`, `licencia` | obligatorios |
| `descripcion`, `web` | opcionales; `web` empieza con `https://` |
| `categorias` | opcional, hasta 3 de: `reportes` `paises` `precios` `metrados` `importar` `revision` `temas` `otros` |
| `traducciones` | opcional: `{"en": {"nombre": "…", "descripcion": "…"}, "pt_BR": {…}}`; se usa según el idioma del programa |
| `imagen` | opcional: ruta de un PNG, JPG o WebP del paquete, de hasta 1 MB y 1600 px de lado. Se ve unas 2,5 veces más ancha que alta, desde arriba. Sin ella salen las iniciales |
| `api_version`, `codigo` | solo con código: la API mínima y el `.py` de entrada |

Secciones de datos, todas opcionales:

### `paises`

```json
{"iso": "AR", "nombre": "Argentina", "moneda": "Pesos Argentinos",
 "identificacion": "CUIT", "impuesto": {"nombre": "IVA", "pct": 21},
 "centro": [-34.6, -58.4],
 "indirectos": {"gastos_generales": 10, "utilidad": 10},
 "pie": [{"codigo": "GG", "nombre": "Gastos generales", "tipo": "pct_cd",
          "pct": "gastos_generales"},
         {"codigo": "SUB", "nombre": "Subtotal", "tipo": "subtotal"},
         {"codigo": "IGV", "nombre": "{impuesto_pct}", "tipo": "pct_sub",
          "pct": "impuesto"}]}
```

`centro`, `indirectos` y `pie` se pueden omitir. Los tipos de rubro son `rubro`,
`pct_cd`, `pct_sub`, `pct_util` y `subtotal`; `pct` es un número o
`gastos_generales`, `utilidad` o `impuesto` (lo del proyecto). El código `IGV` es
el del impuesto, se llame como se llame. El pie solo se usa en proyectos nuevos.

### `monedas`

`{"nombre": "Pesos X", "simbolo": "X$", "miles": ".", "decimal": ","}`. Una
moneda que ya existe no se cambia.

### `vocabulario`

```json
{"idioma": "es", "pais": "AR", "textos": {"Agregar título": "Agregar rubro"}}
```

Cambia **textos completos** de la interfaz, no palabras sueltas: así concuerdan
género y número. Los textos se buscan con
`ingepresupuestos --textos-de-complemento título`. Hay que conservar los
`{marcadores}` y las `<etiquetas>`. No cambia los reportes. `idioma` es `es`,
`en` o `pt_BR`; sin `pais`, vale en todos.

### `importadores_excel`

Para **Insumos ▸ Importar Excel**:

```json
{"nombre": "SINAPI — insumos",
 "detectar": ["Classificação", "Código do Insumo"],
 "columnas": {"tipo": ["Classificação"], "codigo": ["Código do Insumo"],
              "descripcion": ["Descrição do Insumo"], "unidad": ["Unidade"]},
 "tipos": {"EQ": ["EQUIPAMENTO"], "MO": ["MÃO DE OBRA"]},
 "aviso": "Elige en «Precio» la columna de tu estado."}
```

`detectar`: los rótulos que deben estar, todos, en una misma fila. `columnas`:
`codigo`, `descripcion` (obligatoria), `unidad`, `precio`, `tipo`, `inei`, cada
una con los rótulos que se buscan en orden. También: `pais`, `tipo_fijo`,
`prefijo`, `omitir_sin_precio`, `cantidad_en_unidad`, `quitar_impuesto_pct`. El
usuario ve la propuesta y puede corregirla antes de importar.

### `indices`

`{"clave": "CAC", "nombre": "Índice CAC", "valores": [{"periodo": "2026-01",
"valor": 100}]}`. `valores` puede faltar: el usuario los trae con **Importar
índice…**, de un CSV de dos columnas, periodo (`AAAA-MM` o `MM/AAAA`) y valor,
separadas por `;` o tabulador. El programa no los aplica por su cuenta: los lee
un complemento con `ctx.indice(clave)`.

### `titulos`, `unidades`, `temas`

Listas de textos que se suman a las del programa; y los
[temas](#tu-primer-tema).

## API de Python

Solo `from ingepresupuestos import api`. Lo demás (`core`, `views`, la base de
datos) cambia sin aviso, y `--validar-complemento` lo señala. `api.API_VERSION`
es 2: sube al **añadir** algo. Lo hecho para la 1 sigue valiendo sin cambios; si
usas algo marcado como **API 2**, declara `"api_version": 2`.

`registrar(app)` es obligatoria:

| | La función recibe | y devuelve |
|---|---|---|
| `app.reporte(clave, titulo, f, formatos=("pdf","xlsx"))` | `Presupuesto` | `Documento` |
| `app.validador(clave, titulo, f)` | `Presupuesto` | lista de `Aviso` |
| `app.importador(clave, titulo, f, extensiones=("csv",))` | `ruta, ctx` | lista de `PartidaNueva` |
| `app.accion(clave, titulo, f)` | `ctx` | nada |

Todas admiten `ayuda="…"`.

**`Presupuesto`** — ya calculado y de solo lectura: `id nombre cliente ubicacion
fecha_costos plazo_dias jornada estado moneda decimales partidas pie insumos
costo_directo total`, y `hojas()` (sin títulos).

- `Partida`: `id item descripcion nivel es_titulo unidad metrado precio_unitario
  parcial rendimiento sub_presupuesto acu`
- `Insumo` (línea del ACU): `recurso_id codigo descripcion tipo unidad cuadrilla
  cantidad precio parcial es_subpartida es_porcentaje`; `tipo` es `MO`, `MAT`,
  `EQ` o `SC`. Usa `parcial`: en las filas en «%» no es cantidad × precio.
- `LineaPie`: `nombre codigo tipo pct valor es_impuesto`
- `InsumoTotal`: `recurso_id codigo descripcion tipo unidad precio cantidad parcial`
- `Moneda`: `nombre simbolo miles decimal`, `numero(v, dec)`, `formato(v, dec)`
- `api.redondear(v, dec)`: el redondeo comercial del programa
- **API 2**: `Presupuesto.ajustes` (lo que tu complemento guardó en el proyecto),
  `decimales_metrado`, `modalidad`, `nombre_total` e `importe(partida, precio)`
  (metrado × precio con el redondeo del programa); `Partida.acu_abierto` (el ACU
  con las sub-partidas abiertas en sus insumos; mismo total); `LineaPie.etiqueta`
  («IVA (19%)»); `api.idioma()` (`es`, `en` o `pt_BR`);
  `Partida.especificacion` (texto) y `Partida.mediciones`
  (`LineaMetrado`: `descripcion unidades largo ancho alto parcial area kg_m`);
  `Presupuesto.auxiliares` (las sub-partidas) e `Insumo.auxiliar_id`
- **`from ingepresupuestos import piezas`** (API 2): `numero` y `texto` para leer
  ajustes, `pct`, `cuadrar`, `sumar_titulos`, `capitulos`, `recorrer`,
  `bloques_de`, `mediciones` (tabla de mediciones) e `impuesto_materiales`

**`Documento(titulo, bloques, horizontal=False)`** — bloques: `Titulo(texto,
nivel)`, `Parrafo(texto, negrita, alinear)`, `Campos([(etiqueta, valor)])`,
`Tabla(columnas, filas)`, `SaltoPagina()`. `Columna(titulo, ancho_en_%, alinear,
decimales)`; `Fila(celdas, "titulo" | "subtotal")`. El programa hace el PDF —con
el encabezado, el pie y el tema del usuario— y el Excel. No se admite HTML.

**`ctx`** — `presupuesto`, `recurso("datos/x.csv")` (bytes de un archivo del
paquete), `indice(clave)`, `avisar(texto)`, `preguntar(texto)`,
`pedir_archivo(("csv",))` y `editar`:

| | |
|---|---|
| `editar.agregar([PartidaNueva…])` | devuelve los ids |
| `editar.fijar_metrado(partida_id, cantidad)` | `reemplazar_planilla=True` si tiene planilla |
| `editar.fijar_precio(recurso_id, precio)` | solo en este proyecto |
| `editar.renombrar(partida_id, texto)` | |
| `editar.fijar_precios({recurso_id: precio})` | API 2: varios, en un solo paso de deshacer |
| `editar.simular_precios({recurso_id: precio})` | API 2: los `Totales(costo_directo, total)` que saldrían; no guarda |

Cada llamada es una transacción: si falla no queda nada, y entra en
**Deshacer**. Respeta los permisos del usuario y los proyectos aprobados. Con un
importador no hace falta: basta devolver las partidas, y el programa pide
confirmación.

**Pedir datos y recordarlos (API 2).** `ctx.pedir_datos(titulo, [Dato…], texto="")`
muestra un formulario y devuelve `{clave: valor}`, o `None` si se cancela.
`Dato(clave, titulo, tipo, valor, minimo, maximo, decimales, opciones, sufijo,
ayuda)`; `tipo` es `numero`, `entero`,
`texto`, `parrafo` (varias líneas), `opcion` o `si_no`.
`ctx.guardar_ajustes({…})` guarda textos, números y sí/no (hasta 10 KB) **en el
proyecto**: viajan con el `.db`, se deshacen y solo los ve tu complemento, en
`ctx.ajustes` y `p.ajustes`. Compruébalos al leerlos: el `.db` pudo hacerlo otro.

```python
from ingepresupuestos import api


def registrar(app):
    app.accion("tasa", "Configurar la tasa…", configurar)
    app.reporte("costo", "Costo con recargo", reporte)


def configurar(ctx):
    r = ctx.pedir_datos("Recargo", [api.Dato(
        "tasa", "Recargo", valor=ctx.ajustes.get("tasa", 0.0), maximo=100,
        sufijo="%")])
    if r is not None:
        ctx.guardar_ajustes(r)


def reporte(p):
    tasa = p.ajustes.get("tasa", 0.0)
    if not isinstance(tasa, (int, float)) or not 0 <= tasa <= 100:
        tasa = 0.0
    v = api.redondear(p.costo_directo * (1 + tasa / 100), p.decimales)
    return api.Documento("Costo con recargo", [
        api.Campos([(f"Con {tasa} %", p.moneda.formato(v, p.decimales))])])
```

Para un error que el usuario entienda: `raise api.ErrorComplemento("texto")`.
Cualquier otro se muestra con la línea del complemento donde ocurrió.

## Seguridad

- **Código = confianza.** Un complemento con código no está encerrado: puede leer
  y cambiar todo lo que el programa. Por eso se pide aceptarlo, con el autor y los
  archivos a la vista.
- La aceptación es por **contenido** (SHA-256 de todos los archivos). Si cambia un
  byte, deja de cargarse hasta que lo actives de nuevo. Solo se ejecutan esos
  bytes, nunca un `.pyc` de la carpeta.
- Lo activado no va en la base de datos: restaurar una copia o recibir un `.db` no
  activa nada. El asistente de IA (MCP) no puede instalar ni activar.
- Si uno falla al cargar, o el programa se cierra mientras lo carga, queda apagado
  y se explica; el programa arranca igual. Un complemento que se queda en un
  bucle sin fin sí lo bloquea: arranca con `--sin-complementos`.
- El `.zip` se valida antes de escribir nada: sin rutas absolutas, `..`, enlaces,
  nombres reservados ni cifrado; solo `.json .csv .txt .md .png .jpg .webp` (y `.py` con
  código); hasta 200 archivos, 5 MB cada uno y 20 MB en total.

## Límites

- No hay dependencias: solo la biblioteca estándar de Python y la API.
- Un complemento no cambia cálculos, pantallas ni reportes del programa; añade.
- El vocabulario no llega a los reportes.
- Los cambios de país, vocabulario o unidades se ven al volver a abrir cada
  ventana.
