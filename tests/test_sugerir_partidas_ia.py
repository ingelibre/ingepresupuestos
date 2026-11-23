# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Issue #50: «Sugerir partidas con IA» con proveedores simulados (sin claves)."""
import json
import os
import shutil
import sys
import tempfile
import types
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest                                                       # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_fd, _tmpdb = tempfile.mkstemp(suffix='_ia_test.db')
os.close(_fd)
shutil.copy(SEED, _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

from core import ai_specs as ai                                     # noqa: E402

LISTA = [{"item": "01", "descripcion": "OBRAS PROVISIONALES", "unidad": ""}] + [
    {"item": f"01.{i:02d}", "descripcion": f"PARTIDA {i}", "unidad": "m2"}
    for i in range(1, 40)]
JSON = json.dumps({"partidas": LISTA})


def _pid():
    conn = d.get_db()
    pid = conn.execute("INSERT INTO proyectos (nombre, modalidad) VALUES "
                       "('Vivienda de prueba','Contrata')").lastrowid
    conn.commit()
    conn.close()
    return pid


@pytest.fixture
def deepseek(monkeypatch):
    """Servidor tipo OpenAI falso: entrega `cola` en orden."""
    cola, pedidos = [], []

    class _Cli:
        def __init__(self, **k):
            self.chat = NS(completions=NS(create=self._create))

        def _create(self, **k):
            pedidos.append(k)
            r = cola.pop(0)
            if isinstance(r, Exception):
                raise r
            texto, fin = r
            return NS(choices=[NS(message=NS(content=texto), finish_reason=fin)])

    mod = types.ModuleType('openai')
    mod.OpenAI = _Cli
    monkeypatch.setitem(sys.modules, 'openai', mod)
    monkeypatch.setattr(ai, 'recuperar_partidas_hibrido', lambda *a, **k: [])
    monkeypatch.setattr(ai, '_estructura_referencia', lambda *a, **k: '')
    d.set_config('ia_proveedor', 'deepseek')
    d.set_config('api_key', 'x')
    return cola, pedidos


@pytest.mark.parametrize('texto', [
    JSON,
    f"```json\n{JSON}\n```",
    f"Claro, aquí tienes [borrador] la lista:\n\n```json\n{JSON}\n```\nSuerte.",
    f"<think>Pienso {{\"item\": 1}}</think>\n{JSON}",
    json.dumps(LISTA),
])
def test_formatos_que_devuelven_los_modelos(deepseek, texto):
    cola, pedidos = deepseek
    cola.append((texto, 'stop'))
    ps, err = ai.sugerir_partidas_ia(_pid())
    assert err is None and len(ps) == 40
    assert ps[0]['es_titulo'] and not ps[1]['es_titulo']
    assert len(pedidos) == 1


def test_json_cortado_se_completa_en_otra_tanda(deepseek):
    cola, pedidos = deepseek
    corte = JSON.index('"01.20"') + 30
    cola.append((JSON[:corte], 'length'))
    cola.append((json.dumps({"partidas": LISTA[20:]}), 'stop'))
    avisos = []
    ps, err = ai.sugerir_partidas_ia(_pid(), avisos)
    assert err is None and not avisos
    assert [p['item'] for p in ps] == [p['item'] for p in LISTA]
    assert 'PARTIDA 19' in pedidos[1]['messages'][0]['content']


def test_json_cortado_sin_mas_respuesta_conserva_lo_recibido(deepseek):
    cola, _ = deepseek
    cola.append((JSON[:JSON.index('"01.20"') + 30], 'length'))
    cola.append(Exception('429 rate limit'))
    avisos = []
    ps, err = ai.sugerir_partidas_ia(_pid(), avisos)
    assert err is None and len(ps) == 20
    assert avisos and '20' in avisos[0]


def test_razonador_que_gasta_todo_pensando_se_reintenta_con_mas(deepseek):
    cola, pedidos = deepseek
    cola += [(None, 'length'), (JSON, 'stop')]
    ps, err = ai.sugerir_partidas_ia(_pid())
    assert err is None and len(ps) == 40
    assert pedidos[1]['max_tokens'] > pedidos[0]['max_tokens'] > 4000


def test_errores_claros(deepseek):
    cola, _ = deepseek
    cola += [('', 'length')] * 3
    ps, err = ai.sugerir_partidas_ia(_pid())
    assert ps is None and 'se cortó' in err
    cola.append(('Lo siento, no puedo.', 'stop'))
    ps, err = ai.sugerir_partidas_ia(_pid())
    assert ps is None and 'Lo siento' in err
    cola.append(Exception('401 authentication'))
    ps, err = ai.sugerir_partidas_ia(_pid())
    assert ps is None and err.startswith('Error IA: Clave DeepSeek')


def test_numeros_hijos_y_claves_en_otro_idioma():
    arbol = {"partidas": [
        {"item": 1, "descripcion": "TÍTULO", "unidad": None, "hijos": [
            {"item": "1.1", "descrição": "ALVENARIA", "unidade": "m2"}]},
        {"item": "2.", "descripcion": "OTRO", "unidad": "—"}]}
    ps = ai.leer_partidas_json(json.dumps(arbol))
    assert [(p['item'], p['unidad'], p['es_titulo']) for p in ps] == [
        ('1', '', True), ('1.1', 'm2', False), ('2', '', True)]


def test_gemini_sin_pensar_y_cortado(monkeypatch, deepseek):
    d.set_config('ia_proveedor', 'gemini')
    pedidos = []

    class _Cli:
        def __init__(self, **k):
            self.models = NS(generate_content=self._gen)

        def _gen(self, model, contents, config):
            pedidos.append(config)
            if 'thinking_config' in config:
                raise Exception('400 Budget 0 is invalid. This model only '
                                'works in thinking mode.')
            corta = len(pedidos) == 2
            return NS(text=None if corta else JSON, candidates=[
                NS(finish_reason=NS(name='MAX_TOKENS' if corta else 'STOP'))])

    genai = types.ModuleType('google.genai')
    genai.Client = _Cli
    tps = types.ModuleType('google.genai.types')
    tps.ThinkingConfig = lambda **k: k
    tps.GenerateContentConfig = lambda **k: k
    genai.types = tps
    google = types.ModuleType('google')
    google.genai = genai
    for n, m in (('google', google), ('google.genai', genai),
                 ('google.genai.types', tps)):
        monkeypatch.setitem(sys.modules, n, m)
    ps, err = ai.sugerir_partidas_ia(_pid())
    assert err is None and len(ps) == 40


def test_el_prompt_sigue_al_pais(deepseek):
    cola, pedidos = deepseek
    for iso, dentro, fuera in (('PE', 'CAPECO', 'Colombia'),
                               ('CO', 'Colombia', 'CAPECO')):
        d.set_config('pais', iso)
        cola.append((JSON, 'stop'))
        ai.sugerir_partidas_ia(_pid())
        p = pedidos[-1]['messages'][0]['content']
        assert dentro in p and fuera not in p
    d.set_config('pais', '')
