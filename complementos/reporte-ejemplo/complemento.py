# SPDX-License-Identifier: GPL-3.0-or-later
"""Los diez insumos que más cuestan (issue #19)."""
from ingepresupuestos import api


def registrar(app):
    app.reporte("diez-insumos", "Diez insumos que más cuestan", generar)


def generar(p):
    mayores = sorted(p.insumos, key=lambda i: -i.parcial)[:10]
    filas = [(i.descripcion, i.unidad, i.cantidad, i.parcial,
              100 * i.parcial / p.costo_directo if p.costo_directo else 0)
             for i in mayores]
    return api.Documento("Diez insumos que más cuestan", [
        api.Campos([("Proyecto", p.nombre),
                    ("Costo directo", p.moneda.formato(p.costo_directo, p.decimales))]),
        api.Tabla([api.Columna("Insumo", 46), api.Columna("Und.", 8, "centro"),
                   api.Columna("Cantidad", 14, "derecha"),
                   api.Columna("Parcial", 18, "derecha", p.decimales),
                   api.Columna("% del CD", 14, "derecha", 1)], filas),
    ])
