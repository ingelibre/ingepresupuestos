# SPDX-License-Identifier: GPL-3.0-or-later
"""PYTHONPATH=<código de IngePresupuestos> python3 -m pytest prueba.py"""
import complemento as c
from ingepresupuestos import api
from ingepresupuestos.pruebas import presupuesto_ejemplo


def test_bloques_y_cierre():
    x = presupuesto_ejemplo().hojas()[0]
    r = c.calcular(x)
    assert [b[0] for b in r['bloques']] == ['A', 'B', 'C', 'D']
    assert r['directo'] == sum(b[3] for b in r['bloques']) == 65
    assert r['total'] == 650


def test_sin_cuadrilla_ni_rendimiento():
    doc = c.apu(presupuesto_ejemplo())
    t = next(b for b in doc.bloques if isinstance(b, api.Tabla))
    assert [x.titulo for x in t.columnas] == [
        'DESCRIPCIÓN', 'UNIDAD', 'CANTIDAD', 'P. UNITARIO', 'TOTAL']
