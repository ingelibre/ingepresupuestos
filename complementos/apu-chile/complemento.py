# SPDX-License-Identifier: GPL-3.0-or-later
"""APU formato Chile (issue #31).

Pesos enteros: se redondea el total de cada línea y se suma lo redondeado,
para que la suma a mano dé lo impreso. Por eso el precio unitario neto puede
diferir en unos pesos del presupuesto; si difiere, el reporte lo dice al final.
"""
from ingepresupuestos import api

BLOQUES = (
    ("A", "MATERIALES", "MAT"),
    ("B", "EQUIPOS, MAQUINARIAS Y TRANSPORTE", "EQ"),
    ("C", "MANO DE OBRA", "MO"),
    ("D", "VARIOS", "SC"),
)
COLUMNAS = [
    api.Columna("DESCRIPCIÓN", 46),
    api.Columna("UNIDAD", 9, "centro"),
    api.Columna("CANTIDAD", 13, "derecha", 4),
    api.Columna("P. UNITARIO", 15, "derecha", 0),
    api.Columna("TOTAL", 17, "derecha", 0),
]


def registrar(app):
    app.reporte("apu-chile", "APU Chile", apu,
                ayuda="Precio unitario neto = el del presupuesto")
    app.reporte("apu-chile-neto", "APU Chile con GG y utilidad", apu_con_indirectos,
                ayuda="Reparte gastos generales y utilidad en cada precio "
                      "unitario neto")


def apu(p):
    return _documento(p, 1.0)


def apu_con_indirectos(p):
    """Lo del pie sobre el costo directo, menos el impuesto, va en cada PU."""
    if not p.costo_directo:
        raise api.ErrorComplemento("El presupuesto no tiene costo directo.")
    cargos = sum(l.valor for l in p.pie
                 if l.tipo != 'subtotal' and not l.es_impuesto)
    return _documento(p, 1.0 + cargos / p.costo_directo)


def calcular(partida, factor=1.0):
    """{bloques: [(letra, nombre, insumos, subtotal)], directo, neto, total}"""
    bloques = []
    for letra, nombre, tipo in BLOQUES:
        propios = {b[2] for b in BLOQUES}
        insumos = [i for i in partida.acu if i.tipo == tipo
                   or (tipo == 'SC' and i.tipo not in propios)]
        lineas = [(i, api.redondear(i.parcial, 0)) for i in insumos]
        bloques.append((letra, nombre, lineas, sum(t for _i, t in lineas)))
    directo = sum(b[3] for b in bloques)
    if not partida.acu:
        directo = api.redondear(partida.precio_unitario, 0)
    neto = api.redondear(directo * factor, 0)
    return {'bloques': bloques, 'directo': directo, 'neto': neto,
            'total': api.redondear(partida.metrado * neto, 0)}


def _pesos(p, v):
    return "$ " + p.moneda.numero(v, 0)


def _cantidad(p, v):
    t = p.moneda.numero(v, 4)
    return t.rstrip('0').rstrip(p.moneda.decimal) if p.moneda.decimal in t else t


def _documento(p, factor):
    bloques, total = [], 0.0
    partidas = p.hojas()
    if not partidas:
        raise api.ErrorComplemento("El presupuesto no tiene partidas.")
    for n, x in enumerate(partidas):
        if n:
            bloques.append(api.SaltoPagina())
        c = calcular(x, factor)
        total += c['total']
        und = x.unidad
        bloques += [
            api.Titulo(f"{x.item}  {x.descripcion}", 2),
            api.Campos([
                ("Nº de ítem", x.item),
                ("Partida", x.descripcion),
                ("Cantidad", _cantidad(p, x.metrado)),
                ("Unidad", und),
                ("Precio Unitario Neto", _pesos(p, c['neto'])),
                ("Total Neto Partida",
                 f"{_cantidad(p, x.metrado)} {und} x {_pesos(p, c['neto'])} = "
                 f"{_pesos(p, c['total'])}"),
            ]),
        ]
        filas = []
        for letra, nombre, lineas, sub in c['bloques']:
            filas.append(api.Fila([f"{letra}.- {nombre}"], 'titulo'))
            for i, t in lineas:
                filas.append([i.descripcion, i.unidad, i.cantidad,
                              i.precio, t])
            filas.append(api.Fila([f"SUBTOTAL {letra}", None, None, None, sub],
                                  'subtotal'))
        filas.append(api.Fila(["COSTO DIRECTO UNITARIO NETO PARTIDA", None, None,
                               None, c['directo']], 'subtotal'))
        filas.append(api.Fila(["PRECIO UNITARIO NETO PARTIDA", None, None, None,
                               c['neto']], 'subtotal'))
        bloques.append(api.Tabla(COLUMNAS, filas))
    esperado = api.redondear(p.costo_directo * factor, 0)
    cierre = [api.Parrafo(f"Total neto de las partidas: {_pesos(p, total)}",
                          negrita=True, alinear="derecha")]
    if total != esperado:
        cierre.append(api.Parrafo(
            f"El presupuesto, con sus decimales, da {_pesos(p, esperado)}; la "
            f"diferencia de {_pesos(p, total - esperado)} es por el redondeo a "
            "pesos enteros.", alinear="derecha"))
    return api.Documento("Análisis de Precios Unitarios", bloques + cierre)
