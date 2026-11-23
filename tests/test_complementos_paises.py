"""Complementos por país: números hechos a mano."""
import dataclasses

import pytest

import core.database as d
from core.complementos import contexto, reportes
from ingepresupuestos import api
from ingepresupuestos.pruebas import presupuesto_ejemplo

from tests.test_complementos import _cargar, _texto_pdf, admin, limpio  # noqa: F401
from tests.test_complementos_incluidos import (  # noqa: F401
    Ui, _accion, _catalogo, _modulo, obra)

TODOS = ('pais-brasil', 'pu-con-indirectos', 'pais-espana', 'pais-argentina',
         'pais-honduras', 'pais-dominicana', 'pais-italia', 'apu-mexico',
         'apu-chile')


def _con(p, **aj):
    return dataclasses.replace(p, ajustes=aj)


def _doc(nombre, clave, p):
    r = next(x for x in _cargar(nombre).de('reporte') if x.clave.endswith(clave))
    doc = r.funcion(p)
    reportes.comprobar(doc)
    return doc


def _celdas(doc):
    out = []
    for b in doc.bloques:
        if isinstance(b, api.Tabla):
            out += [list(getattr(f, 'celdas', f)) for f in b.filas]
    return out


def _texto(doc):
    return "\n".join(b.texto for b in doc.bloques if isinstance(b, api.Parrafo))


# ── Todos ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('nombre', TODOS)
def test_generan_sin_escribir_y_con_ajustes_raros(nombre, obra, admin, tmp_path):
    antes = contexto.presupuesto(obra[0], admin, nombre)
    claves = ('ac', 'sg', 'modo', 'feito', 'impuesto', 'iva', 'situacion',
              'condiciones', 'mat', 'repartir', 'horas', 'jornales', 'tasa', 'utile',
              'ribasso', 'sicurezza', 'exacto')
    for aj in ({}, *({k: r for k in claves} for r in (
            True, 'x', -5, 1e9, float('nan'), float('inf')))):
        p = _con(antes, **aj)
        for r in _cargar(nombre).de('reporte'):
            try:
                reportes.generar(r, p, tmp_path / 'r.pdf')
                reportes.generar(r, p, tmp_path / 'r.xlsx')
            except api.ErrorComplemento:
                pass
    assert contexto.presupuesto(obra[0], admin, nombre) == antes


# ── Brasil (#21) ─────────────────────────────────────────────────────────────

def test_bdi_a_mano():
    m = _modulo('pais-brasil')
    # (1,0477 × 1,0059 × 1,074) / (1 − 0,0665) − 1 = 21,25 %
    assert m.calcular(m.valores({})) == (21.25, 6.65)
    # Fora da faixa: avisa, não proíbe
    assert m.fora(m.valores({})) == []
    assert len(m.fora(m.valores({'ac': 10.0, 'l': 1.0}))) == 2


def test_bdi_pide_calcular_antes_y_guarda(obra, admin, tmp_path):
    with pytest.raises(api.ErrorComplemento):
        _doc('pais-brasil', 'composicao', presupuesto_ejemplo())
    ui = Ui({'ac': 9.0})
    ctx, f = _accion('pais-brasil', obra[0], admin, tmp_path, ui)
    f(ctx)
    assert 'BDI = ' in ui.textos[0] and 'fuera de la referencia' in ui.textos[0]
    assert ctx.presupuesto.total == 600
    v = _cargar('pais-brasil').de('validador')[0].funcion
    assert len(v(ctx.presupuesto)) == 1 and v(presupuesto_ejemplo()) == []


def test_planilha_dos_redondeos():
    m = _modulo('pais-brasil')
    p = _con(presupuesto_ejemplo(), feito=True)
    # 65,30 × 1,2125 = 79,17625 → 79,18 × 10 = 791,80
    assert m.linhas(p, m.valores(p.ajustes))[0] == {2: (79.18, 791.8)}
    q = _con(presupuesto_ejemplo(), feito=True, modo=m.NO_PARCIAL)
    # 10 × 65,30 × 1,2125 = 791,7625 → 791,76
    assert m.linhas(q, m.valores(q.ajustes))[0] == {2: (79.18, 791.76)}
    assert _celdas(_doc('pais-brasil', 'planilha', q))[-1][-1] == 791.76


# ── Precios con indirectos ───────────────────────────────────────────────────

def test_indirectos_repartidos_y_residuo():
    m = _modulo('pu-con-indirectos')
    p = presupuesto_ejemplo()
    # 886,12 − 135,17 = 750,95; × 1,15: 75,095 → 75,10; × 10 = 751; falta −0,05
    lin, residuo, meta, aparte = m.calcular(p, False)
    assert (lin, residuo, meta) == ({2: (75.1, 751.0)}, -0.05, 750.95)
    assert [x.codigo for x in aparte] == ['IGV']
    # Con el impuesto: 88,612 → 88,61; 886,10; falta 0,02
    assert m.calcular(p, True)[:3] == ({2: (88.61, 886.1)}, 0.02, 886.12)
    doc = _doc('pu-con-indirectos', 'presupuesto', p)
    assert _celdas(doc)[-1][-1] == 886.12
    q = dataclasses.replace(p, pie=(dataclasses.replace(
        p.pie[0], nombre='Gastos Generales (10%)'), *p.pie[1:]))
    doc = _doc('pu-con-indirectos', 'presupuesto', _con(q, impuesto=True))
    assert 'Gastos Generales, Utilidad, IGV.' in _texto(doc)
    assert '%' not in _texto(doc)           # con el impuesto dentro, ninguno
    with pytest.raises(api.ErrorComplemento):
        m.calcular(dataclasses.replace(p, costo_directo=0.0), True)


# ── España ───────────────────────────────────────────────────────────────────

def _planilla(part):
    conn = d.get_db()
    conn.execute("UPDATE partidas SET especificaciones='Hormigon HA-25.' WHERE id=?",
                 (part,))
    conn.execute("INSERT INTO metrados_detalle (partida_id, descripcion, n_elementos, "
                 "largo, ancho, alto, parcial, orden) VALUES (?,'EJE A',2,5,1,1,10,1)",
                 (part,))
    conn.commit()
    conn.close()


def test_espana_mediciones_e_iva(obra, admin, tmp_path):
    _planilla(obra[2])
    p = contexto.presupuesto(obra[0], admin)
    x = p.hojas()[0]
    assert x.especificacion == 'Hormigon HA-25.'
    assert x.mediciones == (api.LineaMetrado('EJE A', 2, 5, 1, 1, 10),)
    doc = _doc('pais-espana', 'mediciones', p)
    c = _celdas(doc)
    assert [None, 'EJE A', 2, 5, 1, 1, 10] in c
    assert [None, 'Hormigon HA-25.'] in c
    assert [None] * 7 + [10, 60, 600] in c
    assert c[-1][:3] == [None, 'TOTAL CON IVA', 726]          # 600 + 21 %
    assert 'su pie lleva otro impuesto' in _texto(doc)
    c = _celdas(_doc('pais-espana', 'mediciones', _con(p, iva=10.0)))
    assert c[-1][2] == 660 and c[-2][2] == 60
    with pytest.raises(api.ErrorComplemento):
        _doc('pais-espana', 'condiciones', p)
    doc = _doc('pais-espana', 'condiciones', _con(p, condiciones='Uno\nDos'))
    assert _texto(doc) == 'Uno\nDos'


def test_espana_iva_sobre_el_pie_sin_su_impuesto():
    # 653 + 65,30 + 32,65 = 750,95; 21 % = 157,70 (no se suma el IGV del pie)
    r = _modulo('pais-espana').resumen(presupuesto_ejemplo())
    assert r[2:] == (750.95, 157.7, 908.65)


def test_la_planilla_de_acero_multiplica_sus_tres_cantidades(obra, admin):
    conn = d.get_db()
    conn.execute("INSERT INTO acero_detalle (partida_id, descripcion, diametro, "
                 "n_estructuras, n_elementos, n_veces, longitud, kg_ml, parcial) "
                 "VALUES (?,'VIGA','1/2\"',2,3,4,5,0.994,119.28)", (obra[2],))
    conn.commit()
    conn.close()
    x = contexto.presupuesto(obra[0], admin).hojas()[0]
    assert x.mediciones == (api.LineaMetrado('VIGA 1/2\"', 24, 5, None, None, 119.28,
                                             kg_m=0.994),)


# ── ajustar-total por grupo ──────────────────────────────────────────────────

@pytest.fixture
def dos_capitulos(obra):
    """02.01 usa el mismo cemento que 01.01: 4 × 2 × 25 = 200."""
    conn = d.get_db()
    pid, rec, _ = obra
    conn.execute("INSERT INTO partidas (proyecto_id, item, descripcion, nivel, "
                 "es_titulo) VALUES (?,'02','OTRAS',1,1)", (pid,))
    b = conn.execute(
        "INSERT INTO partidas (proyecto_id, item, descripcion, unidad, metrado, nivel,"
        " rendimiento) VALUES (?,'02.01','OTRO','m3',4,2,8)", (pid,)).lastrowid
    conn.execute("INSERT INTO acu_items (partida_id, recurso_id, cantidad, precio) "
                 "VALUES (?,?,2,25)", (b, rec[0]))
    d._recalcular_pu(conn, b)
    conn.commit()
    conn.close()
    return pid, rec


def test_ajustar_un_grupo(dos_capitulos, admin, tmp_path):
    pid, rec = dos_capitulos
    # El operario solo está en 01: 100 → 110 sin avisar de nada.
    ui = Ui({'objetivo': 810.0, 'grupo': '01 OBRAS', 'MAT': False, 'MO': True})
    ctx, f = _accion('ajustar-total', pid, admin, tmp_path, ui)
    assert ctx.presupuesto.total == 800
    f(ctx)
    assert ctx.presupuesto.total == 810 and 'ATENCIÓN' not in ui.textos[0]
    # El cemento también está en 02: lo avisa y cuenta el total de verdad.
    ui = Ui({'objetivo': 880.0, 'grupo': '01 OBRAS'}, si=False)
    ctx, f = _accion('ajustar-total', pid, admin, tmp_path, ui)
    f(ctx)
    assert 'ATENCIÓN: 1 ' in ui.textos[0] and 'CEMENTO Z' in ui.textos[0]
    assert ctx.presupuesto.total == 810
    # El operario no está en 02: allí no hay nada que escalar.
    m = _modulo('ajustar-total')
    p = ctx.presupuesto
    assert m.precios_de(p, {'MO'}, dict(m.grupos(p))['02 OTRAS'])[0] == {}


# ── Argentina ────────────────────────────────────────────────────────────────

def test_argentina_reparto():
    m = _modulo('pais-argentina')
    p = presupuesto_ejemplo()
    x = dataclasses.replace(p.hojas()[0], abierto=p.hojas()[0].acu)
    # MAT 50; MO 10 + EQ 0,30; SC 5 → aparte, o 40 % a materiales
    assert m.calcular(p, x, None) == {'mat': 50, 'mo': 10.3, 'otros': 5}
    assert m.calcular(p, x, 40.0) == {'mat': 52, 'mo': 13.3, 'otros': 0}
    assert m.calcular(p, dataclasses.replace(x, acu=(), abierto=()), None) == {
        'mat': 0, 'mo': 0, 'otros': 65.3}
    assert 'no se reparten' in _texto(_doc('pais-argentina', 'mat-mo', p))
    doc = _doc('pais-argentina', 'mat-mo', _con(p, repartir=True, mat=40.0))
    assert 'Subcontratos repartidos: 40 %' in _texto(doc)
    assert _celdas(doc)[1][4:] == [52, 13.3, 65.3, 653]


def _dos_sc(**aj):
    """MAT 50 + SC A 10 + SC B 5 = 65; metrado 10."""
    p = presupuesto_ejemplo()
    a, b = (dataclasses.replace(p.hojas()[0].acu[3], recurso_id=n, codigo=c,
                                descripcion=x, parcial=v)
            for n, c, x, v in ((11, 'A1', 'YESERO', 10.0), (12, 'B1', 'PINTOR', 5.0)))
    x = dataclasses.replace(p.hojas()[0], acu=(p.hojas()[0].acu[1], a, b),
                            precio_unitario=65.0, parcial=650.0)
    return dataclasses.replace(p, partidas=(p.partidas[0], x), costo_directo=650.0,
                               ajustes=aj)


A, B = 'A1|YESERO|glb', 'B1|PINTOR|glb'


def _sc(**k):
    import json
    return json.dumps({{'a': A, 'b': B, 'z': 'Z|NO|x'}[c]: v for c, v in k.items()})


def test_argentina_un_porcentaje_por_subcontrato():
    def fila_(**aj):
        doc = _doc('pais-argentina', 'mat-mo', _dos_sc(repartir=True, **aj))
        return _celdas(doc)[1][4:], _texto(doc)
    # Uno a 0 y otro a 100: mat 50 + 5; mo 10
    f, t = fila_(mat=40.0, sc=_sc(a=0, b=100))
    assert f == [55, 10, 65, 650]
    assert 'más de un porcentaje' in t and 'YESERO 0 %; PINTOR 100 %' in t
    # A 30 % propio y B el general 40 %: 50 + 3 + 2; 7 + 3
    f, t = fila_(mat=40.0, sc=_sc(a=30))
    assert f == [55, 10, 65, 650] and 'YESERO 30 %; PINTOR 40 %' in t
    # Vacío, proyecto viejo (sin «sc») e insumo que ya no existe: el general
    for aj in ({'sc': ''}, {}, {'sc': _sc(z=90)}):
        f, t = fila_(mat=40.0, **aj)
        assert f == [56, 9, 65, 650] and 'repartidos: 40 % materiales' in t
    # Los dos con el mismo: un solo porcentaje
    assert 'repartidos: 25 % materiales' in fila_(mat=40.0, sc=_sc(a=25, b=25))[1]
    # Ajustes raros no rompen
    for raro in (5, True, '[]', '{', '[' * 100000, '{"%s": "x"}' % A,
                 '{"%s": 500}' % A, '{"%s": NaN}' % A, '{"%s": true}' % A):
        assert fila_(mat=40.0, sc=raro)[0] == [56, 9, 65, 650]
    # Sin repartir, los propios no cuentan
    doc = _doc('pais-argentina', 'mat-mo', _dos_sc(mat=40.0, sc=_sc(a=0)))
    assert _celdas(doc)[1][4:] == [50, 0, 15, 65, 650]


def test_argentina_cuadra_con_el_precio():
    m = _modulo('pais-argentina')
    p = _dos_sc()
    x = dataclasses.replace(p.hojas()[0], precio_unitario=64.99)
    for a in (0, 33.33, 66.67, 100):
        v = m.calcular(p, x, 12.5, {A: a, B: 33.335})
        assert api.redondear(sum(v.values()), 2) == 64.99


class _Ctx:
    def __init__(self, p, *respuestas):
        self.presupuesto, self.ajustes = p, dict(p.ajustes)
        self.respuestas, self.avisos, self.campos = list(respuestas), [], []

    def pedir_datos(self, titulo, campos, *, texto=''):
        contexto.comprobar_datos(campos)
        self.campos.append(campos)
        r = self.respuestas.pop(0)
        return None if r is None else {**{c.clave: c.valor for c in campos}, **r}

    def avisar(self, t): self.avisos.append(t)
    def guardar_ajustes(self, a): self.ajustes = a


def test_argentina_formulario():
    import json
    m = _modulo('pais-argentina')
    ctx = _Ctx(_dos_sc(repartir=True, mat=40.0, sc=_sc(a=30, z=90)),
               {'sc': [{'insumo': 'YESERO', 'pct': 'x'}]},
               {'sc': [{'insumo': 'YESERO', 'pct': '1'},
                       {'insumo': 'YESERO', 'pct': '2'}]},
               {'sc': [{'insumo': 'YESERO', 'pct': '101'}]},
               {'sc': [{'insumo': 'YESERO', 'pct': ''},
                       {'insumo': 'PINTOR', 'pct': '12,5 %'}]})
    m.configurar(ctx)
    assert ctx.campos[0][2].valor == [{'insumo': 'YESERO', 'pct': '30'},
                                      {'insumo': 'PINTOR', 'pct': ''}]
    assert len(ctx.avisos) == 3 and 'dos veces' in ctx.avisos[1]
    assert ctx.campos[1][2].valor == [{'insumo': 'YESERO', 'pct': 'x'}]
    assert json.loads(ctx.ajustes['sc']) == {B: 12.5}
    # Quitar una fila la devuelve al general; 0 se guarda (no es vacío).
    ctx = _Ctx(_dos_sc(sc=_sc(a=30, b=5)), {'sc': [{'insumo': 'PINTOR', 'pct': '0'}]})
    m.configurar(ctx)
    assert json.loads(ctx.ajustes['sc']) == {B: 0}
    ctx = _Ctx(_dos_sc(sc=_sc(a=30)), None)
    m.configurar(ctx)
    assert ctx.ajustes == {'sc': _sc(a=30)}


# ── Chile ────────────────────────────────────────────────────────────────────

def test_chile_redondeo_opcional():
    m = _modulo('apu-chile')
    x = presupuesto_ejemplo().hojas()[0]
    ins = dataclasses.replace(x.acu[1], cantidad=0.35, precio=101.0, parcial=35.35)
    x = dataclasses.replace(x, acu=(ins, ins, ins), metrado=10.0)
    # Por defecto 35 + 35 + 35 = 105; exacto 3 × 35,35 = 106,05 → 106
    assert (m.calcular(x)['neto'], m.calcular(x)['total']) == (105, 1050)
    e = m.calcular(x, exacto=True)
    assert (round(e['directo'], 2), e['neto'], e['total']) == (106.05, 106, 1060)
    # En «%» manda el importe: 3 %mo de 10 = 0,30, no 3 × 10
    e = m.calcular(presupuesto_ejemplo().hojas()[0], exacto=True)
    assert round(e['directo'], 2) == 65.3


# ── Honduras ─────────────────────────────────────────────────────────────────

def test_honduras_jornales():
    p = presupuesto_ejemplo()
    assert ['OPERARIO', 'hh', 0.5, 20, 10] in _celdas(_doc('pais-honduras', 'apu', p))
    doc = _doc('pais-honduras', 'apu', _con(p, jornales=True, horas=8.0))
    # 0,5 h / 8 = 0,0625 jornales × 160 = 10
    assert ['OPERARIO', 'jornal', 0.0625, 160, 10] in _celdas(doc)
    doc = _doc('pais-honduras', 'apu', _con(p, jornales=True, horas=10.0))
    assert ['OPERARIO', 'jornal', 0.05, 200, 10] in _celdas(doc)
    assert _celdas(doc)[-1][-1] == 65.3 and 'jornales de 10 horas' in _texto(doc)
    assert all('uadrilla' not in c.titulo for b in doc.bloques
               if isinstance(b, api.Tabla) for c in b.columnas)


# ── Dominicana ───────────────────────────────────────────────────────────────

def test_dominicana_itbis(obra, admin):
    p = contexto.presupuesto(obra[0], admin)
    # 50 × 18 % = 9 × 10 = 90; al 16 %, 80
    assert _celdas(_doc('pais-dominicana', 'itbis', p))[-1][-1] == 90
    assert _celdas(_doc('pais-dominicana', 'itbis', _con(p, tasa=16.0)))[-1][-1] == 80


# ── Italia ───────────────────────────────────────────────────────────────────

def test_italia_a_mano(obra, admin):
    m = _modulo('pais-italia')
    p = contexto.presupuesto(obra[0], admin)
    # 60 + 13 % = 7,80; 10 % de 67,80 = 6,78 → 74,58
    assert m.prezzo(60.0, m.valores({}), 2) == (60, 7.8, 6.78, 74.58)
    assert _celdas(_doc('pais-italia', 'elenco', p))[0] == [
        '01.01', 'CONCRETO', 'm3', 74.58]
    # 745,80 − 10 % = 671,22; + 100 de seguridad (sin ribasso) = 771,22; IVA 22 %
    c = m.conti(_con(p, sicurezza=100.0, ribasso=10.0, iva=22.0))
    assert c == {'lavori': 745.8, 'sicurezza': 100, 'base': 845.8, 'ribasso': 74.58,
                 'netto': 671.22, 'contratto': 771.22, 'iva': 169.67,
                 'totale': 940.89}
    assert 'fuori' not in _texto(_doc('pais-italia', 'analisi', p))
    assert 'fuori' in _texto(_doc('pais-italia', 'analisi', _con(p, sg=20.0)))
    assert _celdas(_doc('pais-italia', 'computo', p))[-1][-3:] == [10, 74.58, 745.8]


# ── México: básicos ──────────────────────────────────────────────────────────

def test_mexico_basicos(obra, admin):
    pid, rec, part = obra
    with pytest.raises(api.ErrorComplemento):
        _doc('apu-mexico', 'basicos', contexto.presupuesto(pid, admin))
    conn = d.get_db()
    ids = []
    for item, n in (('B1', 'MORTERO'), ('B2', 'LECHADA')):
        ids.append(conn.execute(
            "INSERT INTO partidas (proyecto_id, item, descripcion, unidad, metrado, "
            "nivel, es_subanalisis) VALUES (?,?,?,'m3',0,1,1)", (pid, item, n)
        ).lastrowid)
    rid = conn.execute("SELECT id FROM recursos WHERE codigo='SUBPARTIDA'").fetchone()
    rid = rid[0] if rid else conn.execute(
        "INSERT INTO recursos (codigo, descripcion, unidad, tipo) "
        "VALUES ('SUBPARTIDA','SUB','und','SC')").lastrowid
    # B2 = 1 cemento (25); B1 = 2 × B2 (50); 01.01 lleva 0,5 de B1
    conn.execute("INSERT INTO acu_items (partida_id, recurso_id, cantidad, precio) "
                 "VALUES (?,?,1,25)", (ids[1], rec[0]))
    d._recalcular_pu(conn, ids[1])
    for donde, cual, cant in ((ids[0], ids[1], 2), (part, ids[0], 0.5)):
        conn.execute("INSERT INTO acu_items (partida_id, recurso_id, cantidad, precio,"
                     " sub_partida_id) VALUES (?,?,?,?,?)", (donde, rid, cant, 25 if cual == ids[1] else 50, cual))
        d._recalcular_pu(conn, donde)
    conn.commit()
    conn.close()
    p = contexto.presupuesto(pid, admin)
    c = _celdas(_doc('apu-mexico', 'basicos', p))
    # B1: 10 × 0,5 = 5 × 50 = 250; B2: 5 × 2 = 10 × 25 = 250
    assert c[0] == ['B1', 'MORTERO', 'm3', 50, 5, 250]
    assert c[1] == ['B2', 'LECHADA', 'm3', 25, 10, 250]


def test_auxiliar_que_se_llama_a_si_mismo_no_cuelga():
    m = _modulo('apu-mexico')
    p = presupuesto_ejemplo()
    i = dataclasses.replace(p.hojas()[0].acu[0], auxiliar_id=9, cantidad=2.0)
    aux = dataclasses.replace(p.hojas()[0], id=9, acu=(i,))
    x = dataclasses.replace(p.partidas[1], acu=(i,))
    q = dataclasses.replace(p, auxiliares=(aux,), partidas=(p.partidas[0], x))
    assert m.cantidades(q) == {9: 20}
