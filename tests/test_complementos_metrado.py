"""Complementos de metrado: números hechos a mano."""
import json
import math

import pytest

import core.database as d
from core.complementos import contexto, reportes
from ingepresupuestos import api, piezas

from tests.test_complementos import _cargar, admin, limpio  # noqa: F401
from tests.test_complementos_incluidos import _accion, _modulo, obra  # noqa: F401
from utils import i18n

TODOS = ('acero-facil', 'movimiento-tierras', 'ladrillos', 'dosificacion-concreto')


def datos(m, **k):
    return {**{c.clave: c.valor for c in m.campos()}, **k}


def fila(m, tabla, **k):
    c = next(c for c in m.campos() if c.clave == tabla)
    return {**{x.clave: '' if x.valor is None else x.valor for x in c.columnas},
            **k}


class Ui2:
    """Contesta a los formularios por turno."""

    def __init__(self, *respuestas, si=True):
        self.respuestas, self.si = list(respuestas), si
        self.textos, self.pedidos, self.avisos = [], [], []

    def avisar(self, t): self.avisos.append(t)

    def preguntar(self, t):
        self.textos.append(t)
        return self.si

    def pedir_datos(self, titulo, campos, texto=''):
        self.pedidos.append((campos, texto))
        r = self.respuestas.pop(0) if self.respuestas else None
        return None if r is None else {**{c.clave: c.valor for c in campos}, **r}


# ── Gramática ────────────────────────────────────────────────────────────────

BIEN = [
    ('1@.05, 8@.10, 4@.15, R@.20 c/ext',
     (1, None, [(1, .05), (8, .1), (4, .15)], .2, 'ambos')),
    ('1 a 0.05; resto a 0.20', (1, None, [(1, .05)], .2, None)),
    ('1@0,05,8@0,10,R@0,20 c/e', (1, None, [(1, .05), (8, .1)], .2, 'ambos')),
    ('1@.05,8@,10', (1, None, [(1, .05), (8, .1)], None, None)),
    ('[] Ø3/8": 1@.05, R@.20', (1, '3/8"', [(1, .05)], .2, None)),
    ('[]Ø3/8"1@.05, R@.20', (1, '3/8"', [(1, .05)], .2, None)),
    ('□ 8 mm 1@5 cm, 8@10cm, R@200 mm un extremo',
     (1, '8', [(1, .05), (8, .1)], .2, 'uno')),
    ('2[] 1/2" 1@.05 R@.25 en cada extremo', (2, '1/2"', [(1, .05)], .25, 'ambos')),
    ('Ø12: 5 a 0,1', (1, '12', [(5, .1)], None, None)),
    ('estribos 1 3/8": R c/.2', (1, '1-3/8"', [], .2, None)),
    ('1@1cm,2@.1', (1, None, [(1, .01), (2, .1)], None, None)),
]


@pytest.mark.parametrize('texto,esperado', BIEN)
def test_gramatica(texto, esperado):
    r = _modulo('acero-facil').leer_distribucion(texto)
    assert (r['juegos'], r['diam'], r['grupos'], r['resto'], r['ext']) == esperado


@pytest.mark.parametrize('texto', [
    '', ' ', 'hola', '1@', '@.05', '1@@.05', '1@.05,,8@.1', '1@.05 c/', '1@5, 8@10',
    '1@5,8@10', '0@.1', '1@0', '9999@.05', '1@.05, R@.2, 3@.1', 'R@.2, R@.1',
    '12 1@.05', 'Ø3 1@.05', 'Ø99 1@.05', '1@-.05', '1.5@.05', '1@.05 8', 'x1@.05',
    '1@.05; DROP TABLE', '1@٠٫٠٥', '1@.05' * 60, 'Ø10 1@.0.5', '3/0" 1@.1', '1@2 m',
    '1@1e-2', None, '0[] 1@.05', '1@.05 c/ext c/ext'])
def test_gramatica_lo_que_no_se_entiende_se_dice(texto):
    with pytest.raises(api.ErrorComplemento):
        _modulo('acero-facil').leer_distribucion(texto)


def test_gramatica_no_pierde_grupos():
    # «1@0,8@.10» son dos grupos (el primero a 0), no uno a 0,8.
    with pytest.raises(api.ErrorComplemento):
        _modulo('acero-facil').leer_distribucion('1@0,8@.10')
    assert _modulo('acero-facil').leer_distribucion('1@.1,8 a .10')['grupos'] == [
        (1, .1), (8, .1)]


@pytest.mark.parametrize('texto,bien', [
    ('3/8"', '3/8"'), ('3/8', '3/8"'), ('1"', '1"'), ('1 3/8"', '1-3/8"'), ('8', '8'),
    ('Ø10', '10'), ('12 mm', '12'), ('1', None), ('', None), ('0', None), ('99', None),
    ('1/0"', None), ('abc', None)])
def test_diametros(texto, bien):
    m = _modulo('acero-facil')
    if bien is None:
        with pytest.raises(api.ErrorComplemento):
            m.leer_diametro(texto)
    else:
        assert m.leer_diametro(texto) == bien


def test_pesos_de_la_tabla_o_de_la_formula():
    m = _modulo('acero-facil')
    assert m.peso('3/8"') == (0.560, True) and m.peso('12') == (0.888, True)
    # 14 mm no está: π/4 × 0,014² × 7850 = 1,2084
    k, tabla = m.peso('14')
    assert round(k, 4) == 1.2084 and not tabla


# ── Posiciones ───────────────────────────────────────────────────────────────

def _cuenta(luz, texto, ambos=True):
    m = _modulo('acero-facil')
    x = m.leer_distribucion(texto)
    return m.posiciones(luz, x['grupos'], x['resto'], ambos)


def test_cuenta_exacta_de_estribos():
    # Cada extremo: 0,05 + 0,8 + 0,6 = 1,45 → 13; hueco 3 − 2,9 = 0,10 ≤ 0,20 → 0
    assert len(_cuenta(3.0, '1@.05, 8@.10, 4@.15, R@.20')) == 26
    # Luz 4: hueco 1,10 → 6 espacios de 0,1833 → 5 más
    pos = _cuenta(4.0, '1@.05, 8@.10, 4@.15, R@.20')
    assert len(pos) == 31
    assert pos == sorted(pos) and len(set(pos)) == 31
    assert round(pos[0], 6) == 0.05 and round(pos[-1], 6) == 3.95
    saltos = [b - a for a, b in zip(pos, pos[1:])]
    assert max(saltos) <= 0.20 + 1e-9
    # Hueco múltiplo exacto: 2,5 − 2 × 0,25 = 2,0 → 10 espacios → 9 (no 10)
    assert len(_cuenta(2.5, '1@.05, 2@.10, R@.20')) == 3 + 9 + 3
    # Un extremo: 1@.05 y el resto hasta la otra cara: 0,95 / 0,20 → 5 → 4
    assert len(_cuenta(1.0, '1@.05, R@.20', False)) == 5
    # Solo resto
    assert len(_cuenta(1.0, 'R@.25')) == 3
    # Sin resto
    assert len(_cuenta(3.0, '1@.05, 5@.10')) == 12


def test_luz_corta():
    # Justo: 0,05 + 4 × 0,10 = 0,45 por lado = 0,90; caben 10 y no 1 de más
    assert len(_cuenta(0.90, '1@.05, 4@.10')) == 9       # el del centro es uno solo
    assert len(_cuenta(1.00, '1@.05, 4@.10')) == 10
    with pytest.raises(api.ErrorComplemento, match='0.900.*0.890'):
        _cuenta(0.89, '1@.05, 4@.10')
    assert len(_cuenta(0.89, '1@.05, 4@.10', False)) == 5
    with pytest.raises(api.ErrorComplemento):
        _cuenta(0.04, '1@.05', False)


# ── acero-facil ──────────────────────────────────────────────────────────────

def _acero(m, **k):
    return datos(m, estribos=[fila(m, 'estribos', **{
        **dict(nombre='C-1', n=2, tramos=3, luz=4.0, b=25.0, h=40.0, recub=4.0,
               dist='3/8" 1@.05, 8@.10, 4@.15, R@.20 c/ext', gancho=0.1), **k})])


def test_acero_a_mano():
    m = _modulo('acero-facil')
    c = m.calcular(_acero(m))
    f = c.partes[0].filas[0]
    # 2 × (0,25 − 0,08) + 2 × (0,40 − 0,08) + 2 × 0,10 = 1,18 m
    assert round(f.largo, 6) == 1.18
    assert (f.estructuras, f.elementos, f.veces, f.diametro, f.kg_m) == (
        2, 3, 31, '3/8"', 0.56)
    # 2 × 3 × 31 × 1,18 = 219,48 m × 0,56 = 122,9088 kg
    assert c.partes[0].cantidad == 122.91
    assert '31 estribos' in "\n".join(c.formulas)
    assert '0.050, 0.150' in "\n".join(c.formulas)
    # 219,48 / 9 = 24,39 → 25 varillas
    assert '25 varillas de 9 m' in "\n".join(c.formulas)
    c = m.calcular({**_acero(m), 'desp': 5.0})          # 230,45 m → 26
    assert '26 varillas' in "\n".join(c.formulas) and c.partes[0].cantidad == 122.91


def test_acero_grapas_juegos_y_barras():
    m = _modulo('acero-facil')
    v = _acero(m, n=1, tramos=1, dist='2[] 3/8" 1@.05, R@.20', luz=1.0, gancho=0.0,
               grapas=3, lgrapa=0.35)
    # Cada extremo 1; hueco 0,90 / 0,20 → 5 → 4: 6 posiciones
    v['barras'] = [fila(m, 'barras', nombre='C-1', n=2, barras=4, diam='1/2"',
                        largo=10.0, ancla=0.5, ntras=1, ltras=0.6)]
    f = m.calcular(v).partes[0].filas
    assert [(x.veces, round(x.largo, 3)) for x in f] == [(12, 0.98), (18, 0.35),
                                                          (4, 11.1)]
    # 11,76 × 0,56 + 6,3 × 0,56 + 2 × 4 × 11,1 × 0,994 = 6,5856 + 3,528 + 88,2672
    assert m.calcular(v).partes[0].cantidad == 98.38
    v['barras'][0]['ntras'] = 0
    v['barras'][0]['largo'] = 20.0                      # 3 piezas y ningún traslape
    assert any('3 piezas' in a for a in m.calcular(v).avisos)


@pytest.mark.parametrize('mal', [
    dict(dist='1@.05'), dict(diam='1/2"'), dict(luz=0.0), dict(recub=13.0),
    dict(luz=1.0), dict(dist='basura'), dict(grapas=1)])
def test_acero_errores_dicen_el_elemento(mal):
    m = _modulo('acero-facil')
    with pytest.raises(api.ErrorComplemento, match='C-1'):
        m.calcular(_acero(m, **mal))


def test_acero_entra_en_la_planilla_en_un_paso(obra, admin, tmp_path):
    pid = obra[0]
    conn = d.get_db()
    kg = conn.execute("INSERT INTO partidas (proyecto_id, item, descripcion, unidad, "
                      "metrado, nivel) VALUES (?,'01.02','ACERO','kg',11.2,2)",
                      (pid,)).lastrowid
    conn.execute("INSERT INTO acero_detalle (partida_id, orden, descripcion, diametro, "
                 "n_veces, longitud, kg_ml, parcial) VALUES (?,1,'YA','3/8\"',10,2,0.56,"
                 "11.2)", (kg,))
    conn.commit()
    conn.close()
    m = _modulo('acero-facil')
    ui = Ui2(_acero(m), {'d0': '01.02  ACERO'})
    ctx, f = _accion('acero-facil', pid, admin, tmp_path, ui)
    f(ctx)
    assert 'no diseña' in ui.textos[0]
    assert '01.01  CONCRETO' not in ui.pedidos[1][0][0].opciones       # es m3
    x = [h for h in ctx.presupuesto.hojas() if h.id == kg][0]
    assert [y.descripcion for y in x.mediciones][0] == 'YA 3/8"'
    assert len(x.mediciones) == 2 and x.metrado == 134.11     # 11,20 + 122,9088
    assert ctx.ajustes['agregado'] is True
    # El reporte sale de lo guardado.
    doc = _cargar('acero-facil').de('reporte')[0].funcion(ctx.presupuesto)
    reportes.comprobar(doc)
    # Los mismos datos otra vez: avisa.
    ui = Ui2({}, {})
    ctx2, f = _accion('acero-facil', pid, admin, tmp_path, ui)
    f(ctx2)
    assert 'dos veces' in ui.pedidos[1][1]
    assert len([h for h in ctx2.presupuesto.hojas() if h.id == kg][0].mediciones) == 2


def test_un_solo_deshacer(obra, admin, tmp_path):
    m = _modulo('acero-facil')
    ui = Ui2(_acero(m), {'d0': 'Partida nueva, sin precio'})
    ctx, f = _accion('acero-facil', obra[0], admin, tmp_path, ui)
    f(ctx)
    p = ctx.presupuesto
    assert [(x.item, x.unidad, x.metrado, x.precio_unitario) for x in p.partidas[2:]
            ] == [('02', '', 0, 0), ('02.01', 'kg', 122.91, 0)]
    assert p.total == 600
    ctx.operaciones.undo_last()
    assert len(ctx.presupuesto.partidas) == 2 and dict(ctx.ajustes) == {}
    assert ctx.operaciones.pila.resumen() is None


def test_un_error_vuelve_al_formulario_con_lo_escrito(obra, admin, tmp_path):
    m = _modulo('acero-facil')
    ui = Ui2(_acero(m, dist='basura'), None)
    ctx, f = _accion('acero-facil', obra[0], admin, tmp_path, ui)
    f(ctx)
    assert 'basura' in ui.avisos[0] and len(ui.pedidos) == 2
    assert ui.pedidos[1][0][0].valor[0]['dist'] == 'basura'
    assert len(ctx.presupuesto.partidas) == 2 and dict(ctx.ajustes) == {}


# ── agregar_metrados: nunca pisa ─────────────────────────────────────────────

F = api.FilaMetrado


def test_filas_no_pisan_lo_que_hay(obra, admin, tmp_path):
    pid, _r, part = obra
    ctx, _f = _accion('ladrillos', pid, admin, tmp_path, Ui2())
    acero = F('X', veces=1, largo=1, diametro='8', kg_m=0.395)
    # metrado a mano 10, sin planilla
    with pytest.raises(api.ErrorComplemento, match='a mano'):
        ctx.editar.agregar_metrados([api.Metrado([F('A', largo=2)], part)])
    conn = d.get_db()
    conn.execute("INSERT INTO metrados_detalle (partida_id, descripcion, largo, "
                 "parcial, orden) VALUES (?,'YA',10,10,1)", (part,))
    conn.commit()
    conn.close()
    with pytest.raises(api.ErrorComplemento, match='otra clase'):
        ctx.editar.agregar_metrados([api.Metrado([acero], part)])
    ctx.editar.agregar_metrados([api.Metrado([F('A', largo=2, alto=3)], part)])
    x = ctx.presupuesto.hojas()[0]
    assert x.metrado == 16 and [y.parcial for y in x.mediciones] == [10, 6]
    titulo = ctx.presupuesto.partidas[0].id
    for malo in (api.Metrado([F('A', largo=2)], titulo),
                 api.Metrado([F('A', largo=2), acero], part),
                 api.Metrado([F('A', largo=float('nan'))], part),
                 api.Metrado([F('A', largo='2')], part),
                 api.Metrado([F('A', largo=2)], 999999),
                 api.Metrado([F('A', largo=2)])):
        with pytest.raises(api.ErrorComplemento):
            ctx.editar.agregar_metrados([malo])
    # Si uno falla no queda nada de los demás.
    with pytest.raises(api.ErrorComplemento):
        ctx.editar.agregar_metrados([
            api.Metrado(nueva=api.PartidaNueva('N', 'm2'), filas=[F('A', largo=2)]),
            api.Metrado([acero], part)], ajustes={'x': 1})
    assert len(ctx.presupuesto.partidas) == 2 and dict(ctx.ajustes) == {}


def test_partida_de_otro_proyecto_o_bim(obra, admin, tmp_path, monkeypatch):
    pid, _r, part = obra
    conn = d.get_db()
    otro = conn.execute("INSERT INTO proyectos (nombre) VALUES ('O')").lastrowid
    ajena = conn.execute("INSERT INTO partidas (proyecto_id, item, descripcion, unidad,"
                         " metrado, nivel) VALUES (?,'01','A','m',0,1)", (otro,)
                         ).lastrowid
    conn.commit()
    conn.close()
    ctx, _f = _accion('ladrillos', pid, admin, tmp_path, Ui2())
    with pytest.raises(api.ErrorComplemento):
        ctx.editar.agregar_metrados([api.Metrado([F('A', largo=2)], ajena)])
    monkeypatch.setattr(type(ctx.operaciones), '_filas_bim',
                        staticmethod(lambda c, i: {1: 'x'}))
    with pytest.raises(api.ErrorComplemento, match='BIM'):
        ctx.editar.agregar_metrados([api.Metrado([F('A', largo=2)], part)])
    conn = d.get_db()
    conn.execute("DELETE FROM proyectos WHERE id=?", (otro,))
    conn.commit()
    conn.close()


def test_proyecto_aprobado_no_se_toca(obra, admin, tmp_path):
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET estado='aprobado' WHERE id=?", (obra[0],))
    conn.commit()
    conn.close()
    ctx, _f = _accion('ladrillos', obra[0], admin, tmp_path, Ui2())
    with pytest.raises(api.ErrorComplemento):
        ctx.editar.agregar_metrados([api.Metrado(
            nueva=api.PartidaNueva('N', 'm2'), filas=[F('A', largo=2)])])
    assert len(ctx.presupuesto.partidas) == 2


# ── movimiento-tierras ───────────────────────────────────────────────────────

def _tierras(m, exc=(), sec=(), **k):
    return datos(m, exc=[fila(m, 'exc', **x) for x in exc],
                 sec=[fila(m, 'sec', prog=a, corte=b, relleno=c) for a, b, c in sec],
                 **k)


def test_zanja_y_zapata_a_mano():
    m = _modulo('movimiento-tierras')
    c = m.calcular(_tierras(m, [
        dict(nombre='Z', n=2, largo=10.0, ancho=0.6, prof=1.0, sobre=0.2, talud=0.5,
             ocupado=3.0)], esp=25.0))
    # ((0,6 + 0,4) + 0,5 × 1) × 1 × 10 = 15; × 2 = 30; relleno 2 × 12 = 24
    # eliminación 30 − 24 = 6 × 1,25 = 7,5
    assert [(p.nombre, p.cantidad) for p in c.partes] == [
        ('EXCAVACIÓN', 30), ('RELLENO COMPACTADO', 24),
        ('ELIMINACIÓN DE MATERIAL EXCEDENTE (SUELTO)', 7.5)]
    # Zapata 2 × 2 × 1 con talud 0,5: 1/6 (4 + 4 × 6,25 + 9) = 6,3333
    c = m.calcular(_tierras(m, [dict(
        nombre='P', tipo='Zapata o pozo (talud en 4 lados)', largo=2.0, ancho=2.0,
        prof=1.0, talud=0.5)]))
    assert c.partes[0].cantidad == 6.33
    # Sin talud las dos son el prisma
    for tipo in (m.ZANJA, m.POZO):
        c = m.calcular(_tierras(m, [dict(tipo=tipo, largo=2.0, ancho=3.0, prof=1.5)]))
        assert c.partes[0].cantidad == 9


def test_secciones_medias_y_paso():
    m = _modulo('movimiento-tierras')
    # 0–20: (4 + 6) / 2 × 20 = 100 de corte
    # 20–40: 6 de corte a 2 de relleno: 20 × 6 / 8 = 15 → 45; 5 → 5
    # 40–60: (2 + 4) / 2 × 20 = 60 de relleno
    c = m.calcular(_tierras(m, sec=[(0, 4, 0), (20, 6, 0), (40, 0, 2), (60, 0, 4)]))
    q = {p.nombre: p.cantidad for p in c.partes}
    assert q['EXCAVACIÓN'] == 145 and q['RELLENO COMPACTADO'] == 65
    assert q['ELIMINACIÓN DE MATERIAL EXCEDENTE (SUELTO)'] == 80
    # Al revés da lo mismo
    c = m.calcular(_tierras(m, sec=[(0, 0, 2), (20, 6, 0)]))
    assert {p.nombre: p.cantidad for p in c.partes}['EXCAVACIÓN'] == 45
    # Sección mixta: media de cada área
    c = m.calcular(_tierras(m, sec=[(0, 4, 2), (10, 0, 2)]))
    q = {p.nombre: p.cantidad for p in c.partes}
    assert q['EXCAVACIÓN'] == 20 and q['RELLENO COMPACTADO'] == 20
    assert any('áreas extremas' in a for a in c.avisos)


def test_balance_sin_doble_conteo():
    m = _modulo('movimiento-tierras')
    # 100 excavados; 145 de relleno × 1,2 = 174 en banco; sirve el 50 % = 50
    c = m.calcular(_tierras(m, sec=[(0, 10, 14.5), (10, 10, 14.5)], aprov=50.0,
                            banco=1.2, esp=30.0))
    q = {p.nombre: p.cantidad for p in c.partes}
    assert q['EXCAVACIÓN'] == 100 and q['RELLENO COMPACTADO'] == 145
    assert q['MATERIAL DE PRÉSTAMO (EN BANCO)'] == 124
    assert q['ELIMINACIÓN DE MATERIAL EXCEDENTE (SUELTO)'] == 65      # 50 × 1,3
    assert '50.00 + 50.00 = 100.00' in c.formulas[-1]


@pytest.mark.parametrize('exc,sec', [
    ([], []), ([], [(0, 1, 1)]), ([], [(10, 1, 0), (0, 1, 0)]),
    ([], [(0, 1, 0), (0, 1, 0)]), ([dict(largo=1.0)], []),
    ([dict(largo=1.0, ancho=1.0, prof=1.0, ocupado=2.0)], [])])
def test_tierras_errores(exc, sec):
    m = _modulo('movimiento-tierras')
    with pytest.raises(api.ErrorComplemento):
        m.calcular(_tierras(m, exc, sec))


# ── ladrillos ────────────────────────────────────────────────────────────────

def _muros(m, vanos=(), **k):
    return datos(m, muros=[fila(m, 'muros', nombre='M1', n=2, largo=5.0, alto=2.4)],
                 vanos=[fila(m, 'vanos', **x) for x in vanos], **k)


def test_ladrillos_por_aparejo():
    m = _modulo('ladrillos')
    # 24 × 13 × 9, juntas 1,5: soga 1/(0,255 × 0,105) = 37,35; cabeza
    # 1/(0,145 × 0,105) = 65,68; canto 1/(0,255 × 0,145) = 27,05
    for ap, n, e in (('Soga', 37.35, .13), ('Cabeza', 65.68, .24), ('Canto', 27.05, .09)):
        r = m.por_m2(datos(m, aparejo=ap))
        assert (round(r[0], 2), round(r[2], 2)) == (n, e)
    # Mortero en soga: 0,13 − 37,3483 × 0,002808 = 0,0251
    assert round(m.por_m2(datos(m, aparejo='Soga'))[1], 4) == 0.0251
    # Sin juntas no hay mortero
    assert abs(m.por_m2(datos(m, jh=0.0, jv=0.0))[1]) < 1e-12


def test_muros_con_vanos_y_desperdicio():
    m = _modulo('ladrillos')
    v = _muros(m, [dict(muro='m1', n=1, largo=1.0, alto=2.0)], dl=5.0, dm=10.0)
    c = m.calcular(v)
    q = {p.nombre: p.cantidad for p in c.partes}
    # 2 × (12 − 2) = 20 m2; 20 × 37,3483 = 746,97 × 1,05 = 784,3 → 785
    assert q['MURO DE LADRILLO'] == 20 and q['LADRILLOS'] == 785
    # 20 × 0,025126 × 1,1 = 0,5528
    assert q['MORTERO'] == 0.55
    assert sum(math.prod(x for x in (f.estructuras, f.elementos, f.largo, f.alto)
                         if x is not None) for f in c.partes[0].filas) == 20


def test_mortero_por_volumenes_absolutos():
    m = _modulo('ladrillos')
    kg, arena, litros, _f = m.mortero(datos(m))
    # 1500/3150 + 4 × 1600/2600 + 0,8 × 1,5 = 0,47619 + 2,46154 + 1,2 = 4,13773
    assert (round(kg, 2), round(arena, 4), round(litros, 1)) == (362.52, 0.9667, 290.0)


@pytest.mark.parametrize('vano', [dict(muro='M9', largo=1.0, alto=1.0),
                                  dict(muro='M1', largo=9.0, alto=2.0),
                                  dict(muro='M1', largo=1.0)])
def test_vanos_que_no_cuadran(vano):
    m = _modulo('ladrillos')
    with pytest.raises(api.ErrorComplemento):
        m.calcular(_muros(m, [vano]))


# ── dosificacion-concreto ────────────────────────────────────────────────────

def test_dosificacion_a_mano():
    m = _modulo('dosificacion-concreto')
    v = datos(m, wa=4.0, aba=1.0, wp=1.0, abp=1.5)
    x = m.mezcla(v)
    # 350/3150 + 0,175 + 0,02 = 0,30611; agregados 0,69389; arena 45 % = 0,31225
    assert round(x['agr'], 5) == 0.69389
    assert abs(sum(x['vol'].values()) - 1) < 1e-12
    # seca 827,46 y 1011,34; húmeda 860,56 y 1021,46
    assert (round(x['arena_s'], 2), round(x['piedra_s'], 2)) == (827.46, 1011.34)
    assert (round(x['arena'], 2), round(x['piedra'], 2)) == (860.56, 1021.46)
    # aporte 24,824 − 5,057 = 19,767; agua 155,23
    assert (round(x['aporte'], 2), round(x['neta'], 2)) == (19.77, 155.23)
    # 8,24 bolsas; 1 : 2,22 : 2,89; una bolsa 0,1214 m3
    assert round(x['bolsas'], 2) == 8.24 and round(x['rinde'], 4) == 0.1214
    assert [round(y, 2) for y in x['prop']] == [2.22, 2.89]
    c = m.calcular({**v, 'vol': [{'nombre': 'Z', 'm3': 12.0}], 'desp': 5.0,
                    'tanda': 2.0})
    assert c.partes[0].cantidad == 12
    # 12,6 / 0,24286 = 51,88 → 52 tandas
    assert c.formulas[-1].endswith(': 52')


@pytest.mark.parametrize('mal', [dict(cemento=900.0, ac=2.0),
                                 dict(wa=30.0, wp=30.0)])
def test_dosificacion_imposible(mal):
    m = _modulo('dosificacion-concreto')
    with pytest.raises(api.ErrorComplemento):
        m.calcular(datos(m, **mal))


def test_dosificacion_avisa_y_no_trae_resistencias():
    m = _modulo('dosificacion-concreto')
    assert 'laboratorio' in m.AVISO and 'EJEMPLO' in m.AVISO
    assert not any('kg/cm' in c.titulo or "f'c" in c.titulo for c in m.campos())


# ── Los cuatro ───────────────────────────────────────────────────────────────

def _ejemplo(nombre, m):
    return {'acero-facil': lambda: _acero(m),
            'movimiento-tierras': lambda: _tierras(m, [dict(
                nombre='Z', tipo=m.t(m.POZO), largo=2.0, ancho=2.0, prof=1.0,
                talud=0.5)]),
            'ladrillos': lambda: _muros(m, [dict(muro='M1', largo=1.0, alto=2.0)]),
            'dosificacion-concreto': lambda: datos(
                m, vol=[{'nombre': 'A', 'm3': 5.0}])}[nombre]()


@pytest.mark.parametrize('nombre', TODOS)
def test_accion_reporte_y_deshacer(nombre, obra, admin, tmp_path):
    m = _modulo(nombre)
    with pytest.raises(api.ErrorComplemento):          # todavía no hay datos
        _cargar(nombre).de('reporte')[0].funcion(
            contexto.presupuesto(obra[0], admin, nombre))
    m = _modulo(nombre)
    ui = Ui2(_ejemplo(nombre, m), {f'd{n}': 'Partida nueva, sin precio'
                                  for n in range(5)})
    ctx, f = _accion(nombre, obra[0], admin, tmp_path, ui)
    f(ctx)
    p = ctx.presupuesto
    assert len(p.partidas) > 3 and p.total == 600
    calculado = {x.nombre: x.cantidad for x in _modulo(nombre).calcular(
        _ejemplo(nombre, _modulo(nombre))).partes}
    assert {x.descripcion: x.metrado for x in p.hojas()[1:]} == calculado
    antes = contexto.presupuesto(obra[0], admin, nombre)
    r = _cargar(nombre).de('reporte')[0]
    reportes.generar(r, antes, tmp_path / 'r.pdf')
    reportes.generar(r, antes, tmp_path / 'r.xlsx')
    assert contexto.presupuesto(obra[0], admin, nombre) == antes
    ctx.operaciones.undo_last()
    assert len(ctx.presupuesto.partidas) == 2 and dict(ctx.ajustes) == {}


@pytest.mark.parametrize('nombre', TODOS)
def test_datos_guardados_por_otro_no_rompen(nombre):
    m = _modulo(nombre)
    claves = [c.clave for c in m.campos()]
    for raro in (None, True, 'x', -5, 1e300, float('nan'), [], [1], [{}], {'a': 1},
                 [{c.clave: float('inf') for t in m.campos() for c in t.columnas}]):
        aj = {'datos': json.dumps({k: raro for k in claves})}
        v = piezas.datos_guardados(aj, m.campos())
        try:
            m.calcular(v)
        except api.ErrorComplemento:
            pass
    for crudo in ('', '{', '[]', '1', '[' * 100000, 5):
        assert piezas.datos_guardados({'datos': crudo}, m.campos()) is None


def test_las_opciones_sobreviven_al_cambio_de_idioma(obra, admin, tmp_path):
    m = _modulo('movimiento-tierras')
    ui = Ui2(_tierras(m, [dict(tipo=m.POZO, largo=2.0, ancho=2.0, prof=1.0, talud=0.5)]),
             {})
    ctx, f = _accion('movimiento-tierras', obra[0], admin, tmp_path, ui)
    f(ctx)
    aj = dict(ctx.ajustes)
    i18n.set_idioma('en')
    v = piezas.datos_guardados(aj, m.campos())
    assert v['exc'][0]['tipo'] == 'Footing or pit (slope on 4 sides)'
    assert m.calcular(v).partes[0].cantidad == 6.33


# ── El formulario con tabla ──────────────────────────────────────────────────

def test_tabla_agregar_duplicar_quitar():
    import views.complementos_menu as cm
    cols = [api.Dato('a', 'A', 'texto'), api.Dato('n', 'N', 'numero', 1.5),
            api.Dato('o', 'O', 'opcion', 'y', opciones=('x', 'y')),
            api.Dato('s', 'S', 'si_no', True), api.Dato('e', 'E', 'entero', 2)]
    campos = contexto.comprobar_datos([api.Dato('t', 'T', 'tabla', [{'a': 'uno'}],
                                                columnas=cols)])
    dlg = cm.DatosDialog('X', campos)
    w = dlg._w['t']
    uno = {'a': 'uno', 'n': 1.5, 'o': 'y', 's': True, 'e': 2}
    assert dlg.valores() == {'t': [uno]}
    w._duplicar()
    w.poner({'a': 'tres', 'n': 4.0})
    assert [f['a'] for f in w.filas()] == ['uno', 'uno', 'tres']
    w.t.selectRow(0)
    w._quitar()
    assert [(f['a'], f['n']) for f in w.filas()] == [('uno', 1.5), ('tres', 4.0)]
    for _ in range(300):
        w.poner({})
    assert len(w.filas()) == w.MAX_FILAS
    for malo in ((), [api.Dato('z', 'Z', 'tabla', columnas=cols)],
                 [api.Dato('z', 'Z', 'parrafo')]):
        with pytest.raises(api.ErrorComplemento):
            contexto.comprobar_datos([api.Dato('t', 'T', 'tabla', columnas=malo)])


def test_texto_largo_se_lee_entero(monkeypatch):
    import views.complementos_menu as cm
    ui, vistos = cm.Interfaz(None, 'X'), []

    def exec_(self):
        vistos.append(self.txt.toPlainText())
        return cm.QDialog.Accepted
    monkeypatch.setattr(cm.VistaDialog, 'exec', exec_)
    largo = "\n".join(f"línea {n}" for n in range(500))
    assert ui.preguntar(largo) is True
    assert vistos == [largo]
