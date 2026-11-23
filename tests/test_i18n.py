# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Traducciones de la interfaz (issue #21: portugués de Brasil).

`tr()` lee `resources/i18n/<código>.json` con el texto en español como clave.
Estos tests vigilan que toda cadena que pasa por `tr()` tenga su traducción
pt_BR y en (issue #39), que las traducciones conserven los marcadores `{n}` de `.format`, y
que nadie llame a `tr()` al importar un módulo (todavía no se sabe el idioma).

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 -m pytest tests/test_i18n.py -q
"""
import ast
import json
import os
import re
import string
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from scripts import i18n_faltantes as F  # noqa: E402

RAIZ = F.RAIZ


def _marcadores(texto: str) -> set[str]:
    try:
        return {campo for _lit, campo, _spec, _conv in string.Formatter().parse(texto)
                if campo is not None}
    except ValueError:
        return {'<llaves desbalanceadas>'}


@pytest.mark.parametrize('cod', ['pt_BR', 'en'])
def test_toda_cadena_de_tr_tiene_traduccion(cod):
    faltan = F.faltantes(cod)
    assert not faltan, (
        f"{len(faltan)} cadenas de tr() sin traducción en resources/i18n/{cod}.json "
        f"(python3 scripts/i18n_faltantes.py {cod}): {faltan[:15]}")


def test_ingles_conserva_etiquetas_html_espacios_y_saltos():
    """Issue #39: el inglés lleva las mismas etiquetas, saltos y espacios de
    los extremos que el español (hay frases que se concatenan)."""
    def forma(t):
        return (sorted(re.findall(r'</?\w[^>]*>', t)), t.count('\n'), t.count('\t'),
                t[:len(t) - len(t.lstrip())], t[len(t.rstrip()):], t.count('&'))
    malos = [(k, v) for k, v in F.catalogo('en').items() if forma(k) != forma(v)]
    assert not malos, malos[:10]


def test_ingles_no_se_rotula_como_parcial():
    from utils.i18n import IDIOMAS
    desc = {c: d for c, _n, d in IDIOMAS}
    assert 'partial' not in desc['en'].lower()


def test_ingles_la_columna_inicio_del_gantt_no_dice_home():
    fuente = (RAIZ / 'views' / 'cronograma_view.py').read_text(encoding='utf-8')
    assert 'tr("Inicio")' not in fuente
    en = F.catalogo('en')
    assert (en['Inicio'], en['Inicio:']) == ('Home', 'Start:')


def test_los_json_son_diccionarios_de_texto_sin_vacios():
    for cod in F.idiomas():
        cat = F.catalogo(cod)
        assert isinstance(cat, dict) and cat, cod
        malos = [k for k, v in cat.items()
                 if not isinstance(k, str) or not isinstance(v, str) or not v.strip()]
        assert not malos, (cod, malos[:10])


def test_las_traducciones_conservan_los_marcadores_de_format():
    """«Se importaron {n} partidas» → la traducción debe llevar {n} y nada más:
    si no, `.format(n=…)` revienta (KeyError) solo en ese idioma."""
    for cod in F.idiomas():
        malos = [(k, v) for k, v in F.catalogo(cod).items()
                 if _marcadores(k) != _marcadores(v)]
        assert not malos, (cod, malos[:10])


def test_ingles_conserva_las_traducciones_que_vivian_en_el_codigo():
    en = F.catalogo('en')
    assert len(en) >= 249       # las 249 de _TRADUCCIONES (hasta oct 2026)
    assert en['Guardar'] == 'Save'
    assert en['Biblioteca CU'] == 'Unit Cost Library'
    assert en['Agregar partida'] == 'Add item'


def _llamadas_al_importar(arbol: ast.AST, alias: set[str]) -> list[int]:
    """Líneas donde `tr()` se ejecuta al importar: cuerpo del módulo o de una
    clase, valores por defecto de argumentos y decoradores. El cuerpo de
    funciones y lambdas no cuenta (corre después)."""
    malas: list[int] = []

    def visitar(nodo):
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in nodo.decorator_list + nodo.args.defaults + [
                    x for x in nodo.args.kw_defaults if x is not None]:
                visitar(d)
            return
        if isinstance(nodo, ast.Lambda):
            for d in nodo.args.defaults:
                visitar(d)
            return
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name)
                and nodo.func.id in alias):
            malas.append(nodo.lineno)
        for hijo in ast.iter_child_nodes(nodo):
            visitar(hijo)

    visitar(arbol)
    return malas


def test_nadie_llama_a_tr_al_importar_un_modulo():
    malas = {}
    for p in F.archivos_fuente():
        arbol = ast.parse(p.read_text(encoding='utf-8'))
        alias = {a for a in F._alias_tr(arbol) if a != 'N_'}
        if not alias:
            continue
        lineas = _llamadas_al_importar(arbol, alias)
        if lineas:
            malas[str(p.relative_to(RAIZ))] = lineas
    assert not malas, (
        "tr() a nivel de módulo/clase se evalúa antes de leer el idioma; usar "
        f"N_() en la constante y tr(variable) donde se muestra: {malas}")


def test_tr_carga_el_json_y_cae_al_espanol():
    import utils.i18n as i18n
    previo = i18n._idioma_actual
    try:
        i18n.set_idioma('pt_BR')
        assert i18n.tr('Guardar') == F.catalogo('pt_BR')['Guardar']
        assert i18n.tr('Texto que nadie tradujo jamás') == 'Texto que nadie tradujo jamás'
        i18n.set_idioma('xx')            # idioma sin archivo
        assert i18n.tr('Guardar') == 'Guardar'
        i18n.set_idioma('es')
        assert i18n.tr('Guardar') == 'Guardar'
        assert i18n.N_('Guardar') == 'Guardar'
    finally:
        i18n.set_idioma(previo)


def test_portugues_se_ofrece_en_configuracion_y_viaja_en_el_empaquetado():
    from utils.i18n import IDIOMAS
    assert ('pt_BR', 'Português (Brasil)') in [(c, n) for c, n, _d in IDIOMAS]
    for c, _n, _d in IDIOMAS:
        if c != 'es':
            assert (RAIZ / 'resources' / 'i18n' / f'{c}.json').exists(), c
    spec = (RAIZ / 'ingepresupuestos.spec').read_text(encoding='utf-8')
    assert "'resources/i18n/*.json'" in spec


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-q']))
