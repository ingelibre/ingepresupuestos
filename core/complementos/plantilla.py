# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""«Crear complemento»: una carpeta que ya funciona y se puede instalar."""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

from core.complementos import esquema

CODIGO = '''# SPDX-License-Identifier: GPL-3.0-or-later
"""__NOMBRE__ — complemento de IngePresupuestos."""
from ingepresupuestos import api


def registrar(app):
    app.reporte("__ID__-resumen", "__NOMBRE__: resumen", resumen)
    app.validador("__ID__-metrados", "__NOMBRE__: metrados en cero", sin_metrado)


def resumen(p):
    """p es un api.Presupuesto: datos ya calculados, de solo lectura."""
    filas = [(x.item, x.descripcion, x.unidad, x.metrado, x.parcial)
             for x in p.hojas()]
    return api.Documento("Resumen", [
        api.Campos([("Proyecto", p.nombre), ("Cliente", p.cliente)]),
        api.Tabla(
            [api.Columna("Ítem", 12), api.Columna("Descripción", 48),
             api.Columna("Und.", 8, "centro"),
             api.Columna("Metrado", 14, "derecha"),
             api.Columna("Parcial", 18, "derecha", p.decimales)], filas),
        api.Parrafo("Total: " + p.moneda.formato(p.total, p.decimales),
                    negrita=True, alinear="derecha"),
    ])


def sin_metrado(p):
    return [api.Aviso(f"{x.item} {x.descripcion}: sin metrado", partida_id=x.id)
            for x in p.hojas() if not x.metrado]
'''

PRUEBA = '''# SPDX-License-Identifier: GPL-3.0-or-later
"""Prueba del complemento, sin abrir IngePresupuestos.

Con el código fuente de IngePresupuestos en ../ingepresupuestos-app:
    PYTHONPATH=../ingepresupuestos-app python3 -m pytest prueba.py
"""
import complemento
from ingepresupuestos import api
from ingepresupuestos.pruebas import presupuesto_ejemplo


def test_resumen():
    doc = complemento.resumen(presupuesto_ejemplo())
    assert isinstance(doc, api.Documento)
    assert "886.12" in doc.bloques[-1].texto


def test_registrar():
    app = api.Aplicacion("__ID__")
    complemento.registrar(app)
    assert len(app._registros) == 2
'''

LEEME = '''# __NOMBRE__

Complemento de IngePresupuestos.

1. Edita `complemento.json` (autor, licencia, descripción)__EDITA__.
2. Comprueba: `ingepresupuestos --validar-complemento <esta carpeta>`
3. En IngePresupuestos: Configuración ▸ Complementos ▸ Instalar carpeta…, y Activar.
4. Tras cada cambio: Recargar.
5. Para compartirlo: `ingepresupuestos --empaquetar-complemento <esta carpeta>`
'''


def id_de(nombre: str) -> str:
    t = unicodedata.normalize('NFKD', nombre.lower())
    t = re.sub(r'[^a-z0-9]+', '-', ''.join(
        c for c in t if not unicodedata.combining(c))).strip('-')
    t = re.sub(r'^[0-9-]+', '', t)[:40].strip('-')
    return t if len(t) >= 3 else (f'complemento-{t}' if t else 'mi-complemento')


def crear(nombre: str, donde, *, datos: bool = False, autor: str = '') -> Path:
    """Crea `donde/<id>/`. No pisa una carpeta que ya existe."""
    nombre = ' '.join(nombre.split())[:60] or 'Mi complemento'
    # Va dentro de un .py: sin comillas ni barras que lo rompan.
    limpio = re.sub(r'["\\{}]', '', nombre)
    id_ = id_de(nombre)
    destino = Path(donde) / id_
    if destino.exists():
        raise FileExistsError(str(destino))
    m = {'esquema': esquema.ESQUEMA, 'id': id_, 'nombre': nombre,
         'version': '0.1.0', 'autor': autor or 'Tu nombre',
         'licencia': 'GPL-3.0-or-later', 'descripcion': ''}
    archivos = {}
    if datos:
        m.update(titulos=["OBRAS PRELIMINARES"], unidades=[], vocabulario=[
            {'idioma': 'es', 'textos': {}}])
    else:
        m.update(api_version=1, codigo='complemento.py')
        archivos = {'complemento.py': CODIGO, 'prueba.py': PRUEBA}
    archivos['LEEME.md'] = LEEME.replace(
        '__EDITA__', '' if datos else ' y `complemento.py`')
    esquema.validar(m)
    destino.mkdir(parents=True)
    (destino / esquema.ARCHIVO).write_text(
        json.dumps(m, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for rel, texto in archivos.items():
        (destino / rel).write_text(
            texto.replace('__NOMBRE__', limpio).replace('__ID__', id_),
            encoding='utf-8')
    return destino
