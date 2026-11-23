"""Los complementos que vienen con el programa: números hechos a mano."""
import ast
import dataclasses
import importlib
from pathlib import Path

import pytest

import core.database as d
from core.complementos import contexto, esquema, paquete, reportes
from ingepresupuestos import api
from ingepresupuestos.pruebas import presupuesto_ejemplo
from utils import i18n

from tests.test_complementos import (  # noqa: F401 — fixtures
    _cargar, _texto_pdf, admin, limpio)

RAIZ = Path(__file__).resolve().parent.parent
NUEVOS = ('apu-mexico', 'ajustar-total', 'impuesto-materiales',
          'presupuesto-con-datos', 'zapatas', 'pais-brasil', 'pu-con-indirectos',
          'pais-espana', 'pais-argentina', 'pais-honduras', 'pais-dominicana',
          'pais-italia')
#: Reportes que van en el idioma del país, no en el del programa.
EN_SU_IDIOMA = {'pais-brasil', 'pais-italia'}


@pytest.fixture
def obra():
    """01.01: 10 m3 × (cemento 2 × 25 + operario 0,5 × 20 = 60) = 600."""
    conn = d.get_db()
    pid = conn.execute(
        "INSERT INTO proyectos (nombre, cliente, ubicacion, moneda, gf_pct, "
        "utilidad_pct, igv_pct) VALUES ('Obra','Cliente Uno','Lugar','Soles',0,0,0)"
    ).lastrowid
    rec = [conn.execute("INSERT INTO recursos (codigo, descripcion, unidad, tipo, "
                        "precio) VALUES (?,?,?,?,?)", x).lastrowid
           for x in (('Z-CEM', 'CEMENTO Z', 'bls', 'MAT', 25),
                     ('Z-OPE', 'OPERARIO Z', 'hh', 'MO', 20))]
    conn.execute("INSERT INTO partidas (proyecto_id, item, descripcion, nivel, "
                 "es_titulo) VALUES (?,'01','OBRAS',1,1)", (pid,))
    part = conn.execute(
        "INSERT INTO partidas (proyecto_id, item, descripcion, unidad, metrado, nivel,"
        " rendimiento) VALUES (?,'01.01','CONCRETO','m3',10,2,8)", (pid,)).lastrowid
    for r, c, p in ((rec[0], 2, 25), (rec[1], 0.5, 20)):
        conn.execute("INSERT INTO acu_items (partida_id, recurso_id, cantidad, precio)"
                     " VALUES (?,?,?,?)", (part, r, c, p))
    d._recalcular_pu(conn, part)
    conn.commit()
    conn.close()
    yield pid, rec, part
    conn = d.get_db()
    conn.execute("DELETE FROM proyectos WHERE id=?", (pid,))
    conn.execute("DELETE FROM recursos WHERE id IN (?,?)", rec)
    conn.commit()
    conn.close()


class Ui:
    def __init__(self, respuesta=None, si=True):
        self.respuesta, self.si, self.textos, self.pedidos = respuesta, si, [], []

    def avisar(self, t): self.textos.append(t)

    def preguntar(self, t):
        self.textos.append(t)
        return self.si

    def pedir_archivo(self, e=()): return None

    def pedir_datos(self, titulo, campos, texto=''):
        self.pedidos.append(campos)
        if self.respuesta is None:
            return None
        return {**{c.clave: c.valor for c in campos}, **self.respuesta}


def _accion(nombre, pid, admin, tmp_path, ui):
    from core.mcp_deshacer import Pila
    c = _cargar(nombre)
    ctx = contexto.ContextoReal(c, pid, admin, ui, Pila(tmp_path / 'pila'))
    return ctx, c.de('accion')[0].funcion


def _modulo(nombre):
    """El módulo tal como lo carga el programa."""
    return importlib.import_module(_cargar(nombre).de(
        'accion')[0].funcion.__module__)


def _generar(c, pid, admin, tmp_path):
    r = c.de('reporte')[0]
    p = contexto.presupuesto(pid, admin, c.id)
    for ext in ('pdf', 'xlsx'):
        reportes.generar(r, p, tmp_path / f'r.{ext}')
    import openpyxl
    ws = openpyxl.load_workbook(tmp_path / 'r.xlsx').active
    return _texto_pdf(tmp_path / 'r.pdf'), {
        str(f[i]): [v for v in f if v is not None]
        for f in ws.iter_rows(values_only=True) for i in (0, 1) if f[i] is not None}


# ── Todos ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('nombre', NUEVOS)
def test_tienen_todos_sus_textos_en_ingles_y_portugues(nombre):
    carpeta = RAIZ / 'complementos' / nombre
    espacio = {}
    exec((carpeta / 'textos.py').read_text(encoding='utf-8'), espacio)
    arbol = ast.parse((carpeta / 'complemento.py').read_text(encoding='utf-8'))
    usados = {n.args[0].value for n in ast.walk(arbol) if isinstance(n, ast.Call)
              and getattr(n.func, 'id', '') in ('t', 'm') and n.args
              and isinstance(n.args[0], ast.Constant)
              and n.func.id == 't' and isinstance(n.args[0].value, str)}
    constantes = {n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant)
                  and isinstance(n.value, str)}
    for idioma in ('en', 'pt_BR'):
        tr = espacio['TEXTOS'][idioma]
        assert usados <= set(tr), usados - set(tr)
        assert set(tr) <= constantes, set(tr) - constantes      # ninguno de sobra
        import re
        for a, b in tr.items():
            assert b and sorted(re.findall(r'{\w+}', a)) == sorted(
                re.findall(r'{\w+}', b)), a
    i18n.set_idioma('en')
    c = _cargar(nombre)
    titulos = [r.titulo for t in ('accion', 'reporte') for r in c.de(t)]
    if nombre in EN_SU_IDIOMA:
        titulos = [r.titulo for r in c.de('accion')]
    assert titulos and all(x in espacio['TEXTOS']['en'].values() for x in titulos)


@pytest.mark.parametrize('nombre', [n for n in NUEVOS if n not in
                                    ('zapatas', 'ajustar-total', 'pais-brasil')])
def test_los_reportes_no_escriben(nombre, obra, admin, tmp_path):
    antes = contexto.presupuesto(obra[0], admin)
    _generar(_cargar(nombre), obra[0], admin, tmp_path)
    assert contexto.presupuesto(obra[0], admin) == antes


@pytest.mark.parametrize('nombre', ['apu-mexico', 'impuesto-materiales',
                                    'presupuesto-con-datos'])
def test_ajustes_raros_no_rompen_el_reporte(nombre):
    c = _cargar(nombre)
    for raro in (True, 'x', -5, 1e9, float('nan')):
        claves = ('oficina', 'campo', 'utilidad', 'tasa', 'nombre', 'numero', 'fecha')
        p = dataclasses.replace(presupuesto_ejemplo(),
                                ajustes={k: raro for k in claves})
        reportes.comprobar(c.de('reporte')[0].funcion(p))


# ── apu-mexico (#30) ─────────────────────────────────────────────────────────

PCT = {'oficina': 5.0, 'campo': 10.0, 'financiamiento': 1.0, 'utilidad': 10.0,
       'cargos': 0.5}


def test_mexico_cascada_a_mano():
    m = _modulo('apu-mexico')
    # 60 + 3 + 6 = 69; 1 % = 0,69 → 69,69; 10 % = 6,97 → 76,66; 0,5 % = 0,38
    assert m.calcular(60.0, PCT, 2) == ([
        ('Indirectos de oficina', 5.0, 3.0), ('Indirectos de campo', 10.0, 6.0),
        ('Financiamiento', 1.0, 0.69), ('Utilidad', 10.0, 6.97),
        ('Cargos adicionales', 0.5, 0.38)], 77.04)
    assert m.calcular(60.0, m.porcentajes({}), 2)[1] == 60.0     # nada inventado


def test_mexico_reporte(obra, admin, tmp_path):
    pid = obra[0]
    ctx, configurar = _accion('apu-mexico', pid, admin, tmp_path, Ui({}))
    configurar(ctx)
    assert set(ctx.ajustes.values()) == {0.0}
    texto, _ = _generar(_cargar('apu-mexico'), pid, admin, tmp_path)
    assert 'Todos los porcentajes están en 0' in texto
    ctx, configurar = _accion('apu-mexico', pid, admin, tmp_path, Ui(PCT))
    configurar(ctx)
    texto, filas = _generar(_cargar('apu-mexico'), pid, admin, tmp_path)
    assert 'no cambia el presupuesto' in texto
    assert 'Utilidad (10 %)' in texto and 'Cargos adicionales (0.5 %)' in texto
    assert filas['COSTO DIRECTO'][-1] == 60 and filas['PRECIO UNITARIO'][-1] == 77.04
    # Manda el PU redondeado: 10 × 77,04
    assert filas['TOTAL'][-1] == 770.4
    assert '170.40' in texto                # 770,40 − 600 del pie sin impuestos
    ctx, configurar = _accion('apu-mexico', pid, admin, tmp_path, Ui(None))
    configurar(ctx)                         # cancelar no cambia nada
    assert dict(ctx.ajustes) == PCT


# ── ajustar-total (#40) ──────────────────────────────────────────────────────

def _catalogo(rec):
    conn = d.get_db()
    r = [conn.execute("SELECT precio FROM recursos WHERE id=?", (x,)).fetchone()[0]
         for x in rec]
    conn.close()
    return r


def test_ajustar_exacto_y_solo_lo_elegido(obra, admin, tmp_path):
    pid, rec, _ = obra
    # 600 → 650: el cemento (20 bolsas) debe subir 50/20 = 2,50 → 27,50
    ui = Ui({'objetivo': 650.0})
    ctx, f = _accion('ajustar-total', pid, admin, tmp_path, ui)
    assert ctx.presupuesto.total == 600
    f(ctx)
    p = ctx.presupuesto
    precios = {i.recurso_id: i.precio for i in p.hojas()[0].acu}
    assert p.total == 650 and precios == {rec[0]: 27.5, rec[1]: 20}
    assert _catalogo(rec) == [25, 20]
    t = ui.textos[0]
    assert '600.00' in t and '650.00' in t and 'CEMENTO Z' in t
    # Un solo paso de deshacer.
    pila = ctx.operaciones.pila
    ctx.operaciones.undo_last()
    assert ctx.presupuesto.total == 600
    assert pila.resumen() is None


def test_ajustar_dice_cuanto_falta(obra, admin, tmp_path):
    # El total va de 10 en 10 céntimos (20 bolsas × 0,01 = 0,20): 650,07 no sale.
    ui = Ui({'objetivo': 650.07})
    ctx, f = _accion('ajustar-total', obra[0], admin, tmp_path, ui)
    f(ctx)
    total = ctx.presupuesto.total
    assert abs(total - 650.07) < 0.2 and total != 650.07
    assert 'El redondeo no permite llegar exacto' in ui.textos[0]
    assert ctx.presupuesto.moneda.formato(round(650.07 - total, 2), 2) in ui.textos[0]


@pytest.mark.parametrize('objetivo', [1.0, 349.0, 1101.0, 1e9])
def test_ajustar_sin_factores_absurdos(obra, admin, tmp_path, objetivo):
    # Solo con el cemento (500 de 600): de 250+100=350 a 1000+100=1100.
    ctx, f = _accion('ajustar-total', obra[0], admin, tmp_path,
                     Ui({'objetivo': objetivo}))
    with pytest.raises(api.ErrorComplemento, match='350.*1,100'):
        f(ctx)
    assert ctx.presupuesto.total == 600


def test_ajustar_cancelar_o_decir_que_no(obra, admin, tmp_path):
    for ui in (Ui(None), Ui({'objetivo': 650.0}, si=False)):
        ctx, f = _accion('ajustar-total', obra[0], admin, tmp_path, ui)
        f(ctx)
        assert ctx.presupuesto.total == 600
        assert ctx.operaciones.pila.resumen() is None
    ctx, f = _accion('ajustar-total', obra[0], admin, tmp_path,
                     Ui({'objetivo': 650.0, 'MAT': False}))
    with pytest.raises(api.ErrorComplemento, match='al menos un tipo'):
        f(ctx)
    ctx, f = _accion('ajustar-total', obra[0], admin, tmp_path,
                     Ui({'objetivo': 650.0, 'MAT': False, 'EQ': True}))
    with pytest.raises(api.ErrorComplemento, match='No hay insumos'):
        f(ctx)


def test_ajustar_con_subpartida(obra, admin, tmp_path):
    """El insumo dentro de una sub-partida también se escala."""
    pid, rec, part = obra
    conn = d.get_db()
    sub = conn.execute(
        "INSERT INTO partidas (proyecto_id, item, descripcion, unidad, metrado, nivel,"
        " es_subanalisis) VALUES (?,'S1','MORTERO','m3',0,1,1)", (pid,)).lastrowid
    conn.execute("INSERT INTO acu_items (partida_id, recurso_id, cantidad, precio) "
                 "VALUES (?,?,1,25)", (sub, rec[0]))
    d._recalcular_pu(conn, sub)
    rid = conn.execute("SELECT id FROM recursos WHERE codigo='SUBPARTIDA'").fetchone()
    rid = rid[0] if rid else conn.execute(
        "INSERT INTO recursos (codigo, descripcion, unidad, tipo) "
        "VALUES ('SUBPARTIDA','SUB','und','SC')").lastrowid
    conn.execute("DELETE FROM acu_items WHERE partida_id=? AND recurso_id=?",
                 (part, rec[0]))
    conn.execute("INSERT INTO acu_items (partida_id, recurso_id, cantidad, precio, "
                 "sub_partida_id) VALUES (?,?,2,25,?)", (part, rid, sub))
    d._recalcular_pu(conn, part)
    conn.commit()
    conn.close()
    ctx, f = _accion('ajustar-total', pid, admin, tmp_path, Ui({'objetivo': 650.0}))
    assert ctx.presupuesto.total == 600
    f(ctx)
    assert ctx.presupuesto.total == 650


def test_ajustar_no_toca_un_proyecto_aprobado(obra, admin, tmp_path):
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET estado='aprobado' WHERE id=?", (obra[0],))
    conn.commit()
    conn.close()
    ctx, f = _accion('ajustar-total', obra[0], admin, tmp_path, Ui({'objetivo': 650.0}))
    with pytest.raises(api.ErrorComplemento):
        f(ctx)
    assert ctx.presupuesto.total == 600


# ── impuesto-materiales (#57) ────────────────────────────────────────────────

def test_impuesto_a_mano(obra, admin, tmp_path):
    texto, filas = _generar(_cargar('impuesto-materiales'), obra[0], admin, tmp_path)
    # Materiales 50/m3; 18 % = 9; × 10 = 90. PU con impuesto 69.
    f = filas['01.01']
    assert f[3:] == [10, 60, 50, 9, 69, 90] and filas['TOTAL'][-1] == 90
    assert 'ITBIS (18 %)' in texto and '690.00' in texto
    assert 'dos veces' not in texto
    ctx, configurar = _accion('impuesto-materiales', obra[0], admin, tmp_path,
                              Ui({'tasa': 16.0, 'nombre': 'IVA'}))
    configurar(ctx)
    texto, filas = _generar(_cargar('impuesto-materiales'), obra[0], admin, tmp_path)
    assert filas['TOTAL'][-1] == 80 and 'IVA (16 %)' in texto


def test_impuesto_avisa_si_el_pie_ya_lo_cobra():
    doc = _cargar('impuesto-materiales').de('reporte')[0].funcion(presupuesto_ejemplo())
    assert 'IGV' in doc.bloques[-1].texto and 'dos veces' in doc.bloques[-1].texto


# ── presupuesto-con-datos (#62) ──────────────────────────────────────────────

def test_datos_en_la_primera_pagina(obra, admin, tmp_path):
    ctx, configurar = _accion('presupuesto-con-datos', obra[0], admin, tmp_path, Ui({
        'numero': 'P-014', 'fecha': '23/11/2026', 'descripcion': 'Dos pisos'}))
    configurar(ctx)
    _t, filas = _generar(_cargar('presupuesto-con-datos'), obra[0], admin, tmp_path)
    import pdfplumber
    with pdfplumber.open(tmp_path / 'r.pdf') as f:
        pag = f.pages[0].extract_text()
    for x in ('Cliente Uno', 'P-014', 'Lugar', '23/11/2026', 'Dos pisos'):
        assert x in pag
    assert pag.index('P-014') < pag.index('CONCRETO')
    assert 'Contacto' not in pag                    # vacío no se imprime
    assert filas['01.01'][2:] == ['m3', 10, 60, 600]
    assert filas['PRESUPUESTO TOTAL (S/)'][-1] == 600


def test_datos_total_propio():
    p = dataclasses.replace(presupuesto_ejemplo(), nombre_total='Costo de inversión')
    doc = _cargar('presupuesto-con-datos').de('reporte')[0].funcion(p)
    assert doc.bloques[-1].filas[-1].celdas == ['Costo de inversión (S/)', 886.12]


# ── zapatas (#27) ────────────────────────────────────────────────────────────

Z = {'nombre': 'Z-2', 'n': 4, 'largo': 2.0, 'ancho': 1.5, 'alto': 0.5, 'prof': 1.2,
     'sobre': 0.25, 'recub': 7.5, 'nl': 8, 'dl': 12.0, 'na': 10, 'da': 16.0,
     'desp': 5.0}


def test_zapata_a_mano():
    m = _modulo('zapatas')
    # 12 mm = 0,8878 kg/m; 16 mm = 1,5783 kg/m (π/4 · d² · 7850)
    assert (round(m.kg_por_m(12), 4), round(m.kg_por_m(16), 4)) == (0.8878, 1.5783)
    r, formulas = m.calcular(Z)
    # 4 × 2,5 × 2,0 × 1,2 = 24 | 4 × 2 × 1,5 × 0,5 = 6 | 4 × 2 × 3,5 × 0,5 = 14
    # 4 × (8 × 1,85 × 0,8878 + 10 × 1,35 × 1,5783) × 1,05 = 144,68
    assert r == {'excavacion': 24.0, 'concreto': 6.0, 'encofrado': 14.0,
                 'acero': 144.68}
    assert '4 × 2.5 × 2 × 1.2 = 24.00 m3' in formulas[0]
    assert m.calcular({**Z, 'prof': 0.0, 'sobre': 0.0})[0]['excavacion'] == 6.0
    for malo in ({'recub': 75.0}, {'prof': 0.2}, {'nl': 0, 'na': 0}):
        with pytest.raises(api.ErrorComplemento):
            m.calcular({**Z, **malo})


def test_zapata_agrega_en_un_paso(obra, admin, tmp_path):
    ui = Ui(Z)
    ctx, f = _accion('zapatas', obra[0], admin, tmp_path, ui)
    f(ctx)
    p = ctx.presupuesto
    assert [(x.item, x.unidad, x.metrado, x.precio_unitario)
            for x in p.partidas[2:]] == [
        ('02', '', 0, 0), ('02.01', 'm3', 24, 0), ('02.02', 'm3', 6, 0),
        ('02.03', 'm2', 14, 0), ('02.04', 'kg', 144.68, 0)]
    assert p.partidas[2].descripcion == 'ZAPATAS Z-2' and p.total == 600
    assert 'no diseña' in ui.textos[0] and '144.68 kg' in ui.textos[0]
    ctx.operaciones.undo_last()
    assert len(ctx.presupuesto.partidas) == 2
    ctx, f = _accion('zapatas', obra[0], admin, tmp_path, Ui(Z, si=False))
    f(ctx)
    assert len(ctx.presupuesto.partidas) == 2


# ── Espera y cancelar, con la ventana de verdad ─────────────────────────────

def test_ajustar_muestra_la_espera_y_se_puede_cancelar(obra, admin, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QProgressDialog, QWidget
    import views.complementos_menu as cm
    pid, _rec, _part = obra
    QApplication.instance() or QApplication([])
    padre = QWidget()
    padre.show()
    c = _cargar('ajustar-total')
    monkeypatch.setattr(cm, '_usuario', lambda: admin)
    monkeypatch.setattr(cm.Interfaz, 'pedir_datos', lambda self, t, campos, x='': {
        **{k.clave: k.valor for k in campos}, 'objetivo': 650.0})
    preguntas, vistos = [], []

    def preguntar(self, texto):
        self.fin()
        preguntas.append(texto)
        return False
    monkeypatch.setattr(cm.Interfaz, 'preguntar', preguntar)
    errores = []
    monkeypatch.setattr(cm.Interfaz, 'error', lambda self, t: errores.append(t))
    normal = cm.Interfaz.trabajando

    def espia(self):
        normal(self)
        vistos.append(self._espera is not None and self._espera.isVisible())
    monkeypatch.setattr(cm.Interfaz, 'trabajando', espia)
    r = c.de('accion')[0]
    assert cm.ejecutar_accion(padre, padre, c, r, pid)
    assert preguntas and vistos and all(vistos) and not errores
    assert not any(d.isVisible() for d in padre.findChildren(QProgressDialog))

    def cancela(self):
        normal(self)
        self._espera.cancel()
    monkeypatch.setattr(cm.Interfaz, 'trabajando', cancela)
    preguntas.clear()
    assert not cm.ejecutar_accion(padre, padre, c, r, pid)
    assert not preguntas and not errores
    assert not any(d.isVisible() for d in padre.findChildren(QProgressDialog))
