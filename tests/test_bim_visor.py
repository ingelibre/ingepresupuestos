# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Visor BIM: geometría en proceso aparte, caché, selección y colores.

Lo que necesita IfcOpenShell se salta si no está instalado (es opcional); lo
demás usa una geometría escrita a mano con el mismo formato de la caché.

Corre con:  QT_QPA_PLATFORM=offscreen venv/bin/python3 -m pytest tests/test_bim_visor.py -q
"""
import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

np = pytest.importorskip('numpy')

from core import bim_geometria as bg  # noqa: E402

con_ifc = pytest.mark.skipif(not bg.disponible(), reason='sin ifcopenshell')


def _ifc(ruta):
    """Dos cajas: un muro de 4×0,2×3 en «Piso 1» y una losa de 4×4×0,2 en
    «Piso 2» pintada de azul; todo a 500 km del origen (georreferenciado)."""
    g = ['1xS3BCk291UvhgP2a6eflN', '1xS3BCk291UvhgP2a6eflM',
         '1xS3BCk291UvhgP2a6eflP', '1xS3BCk291UvhgP2a6eflQ',
         '1xS3BCk291UvhgP2a6eflR', '1xS3BCk291UvhgP2a6eflS',
         '1xS3BCk291UvhgP2a6eflT', '1xS3BCk291UvhgP2a6eflU',
         '1xS3BCk291UvhgP2a6eflV', '1xS3BCk291UvhgP2a6eflW',
         '1xS3BCk291UvhgP2a6eflX']
    ruta.write_text(f"""ISO-10303-21;
HEADER;
FILE_DESCRIPTION((''),'2;1');
FILE_NAME('','',(''),(''),'','','');
FILE_SCHEMA(('IFC4'));
ENDSEC;
DATA;
#1=IFCPROJECT('{g[0]}',$,'P',$,$,$,$,(#4),#2);
#2=IFCUNITASSIGNMENT((#3));
#3=IFCSIUNIT(*,.LENGTHUNIT.,$,.METRE.);
#4=IFCGEOMETRICREPRESENTATIONCONTEXT($,'Model',3,1.E-5,#5,$);
#5=IFCAXIS2PLACEMENT3D(#6,$,$);
#6=IFCCARTESIANPOINT((0.,0.,0.));
#10=IFCBUILDING('{g[1]}',$,'E',$,$,$,$,$,.ELEMENT.,$,$,$);
#11=IFCBUILDINGSTOREY('{g[2]}',$,'Piso 1',$,$,$,$,$,.ELEMENT.,0.);
#12=IFCBUILDINGSTOREY('{g[3]}',$,'Piso 2',$,$,$,$,$,.ELEMENT.,3.);
#13=IFCRELAGGREGATES('{g[4]}',$,$,$,#1,(#10));
#14=IFCRELAGGREGATES('{g[5]}',$,$,$,#10,(#12,#11));
#20=IFCCARTESIANPOINT((500000.,8000000.,0.));
#21=IFCAXIS2PLACEMENT3D(#20,$,$);
#22=IFCLOCALPLACEMENT($,#21);
#23=IFCRECTANGLEPROFILEDEF(.AREA.,$,$,4.,0.2);
#24=IFCDIRECTION((0.,0.,1.));
#25=IFCEXTRUDEDAREASOLID(#23,#5,#24,3.);
#26=IFCSHAPEREPRESENTATION(#4,'Body','SweptSolid',(#25));
#27=IFCPRODUCTDEFINITIONSHAPE($,$,(#26));
#28=IFCWALL('{g[6]}',$,'Muro',$,$,#22,#27,$,$);
#30=IFCCARTESIANPOINT((500000.,8000000.,3.));
#31=IFCAXIS2PLACEMENT3D(#30,$,$);
#32=IFCLOCALPLACEMENT($,#31);
#33=IFCRECTANGLEPROFILEDEF(.AREA.,$,$,4.,4.);
#35=IFCEXTRUDEDAREASOLID(#33,#5,#24,0.2);
#36=IFCSHAPEREPRESENTATION(#4,'Body','SweptSolid',(#35));
#37=IFCPRODUCTDEFINITIONSHAPE($,$,(#36));
#38=IFCSLAB('{g[7]}',$,'Losa',$,$,#32,#37,$,$);
#40=IFCCOLOURRGB($,0.,0.,1.);
#41=IFCSURFACESTYLERENDERING(#40,0.,$,$,$,$,$,$,.FLAT.);
#42=IFCSURFACESTYLE('azul',.BOTH.,(#41));
#43=IFCSTYLEDITEM(#35,(#42),$);
#50=IFCRELCONTAINEDINSPATIALSTRUCTURE('{g[8]}',$,$,$,(#28),#11);
#51=IFCRELCONTAINEDINSPATIALSTRUCTURE('{g[9]}',$,$,$,(#38),#12);
ENDSEC;
END-ISO-10303-21;
""", 'utf-8')
    return g[6], g[7]


@pytest.fixture
def cache(tmp_path, monkeypatch):
    d = tmp_path / 'cache'
    monkeypatch.setattr(bg, 'carpeta_cache', lambda: d)
    return d


def _cubo(x):
    """Cubo de lado 2 centrado en (x,0,0): vértices Nx3 y 12 triángulos."""
    v = np.array([[x + a, b, c] for a in (-1, 1) for b in (-1, 1) for c in (-1, 1)], float)
    t = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
         (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    return v, np.array(t)


def _geometria(carpeta, clases=('IfcWall', 'IfcWindow', 'IfcSpace')):
    """Tres cubos en x = 0, 5 y 10; el segundo es translúcido."""
    carpeta.mkdir(parents=True, exist_ok=True)
    v, i, partes, cajas, elem = [], [], [], [], []
    for k, clase in enumerate(clases):
        a, t = _cubo(5 * k)
        fila = np.zeros((8, 8), np.float32)
        fila[:, :3] = a
        fila[:, 6] = (k + .5) / bg.ANCHO_PALETA
        fila[:, 7] = .5
        partes.append((k, 8 * k, 8, 12 * k, 12))
        i.append(t + 8 * k)
        v.append(fila)
        cajas.append([*a.min(0), *a.max(0)])
        elem.append([f'gid{k}', clase, f'E{k}', 'Piso 1' if k else '', [k]])
    np.concatenate(v).tofile(carpeta / 'v.bin')
    np.concatenate(i).astype(np.uint32).tofile(carpeta / 'i.bin')
    n = len(clases)
    np.save(carpeta / 'partes.npy', np.array(partes, np.int64))
    np.save(carpeta / 'cajas.npy', np.array(cajas, np.float32))
    col = np.array([[200, 100, 50, 255]] * n, np.uint8)
    if n > 1:
        col[1, 3] = 110
    np.save(carpeta / 'colores.npy', col)
    (carpeta / 'meta.json').write_text(json.dumps({
        'formato': bg.FORMATO, 'nombre': 'x.ifc', 'avisos': [], 'centro': [0, 0, 0],
        'pisos': ['Piso 1'], 'elementos': elem, 'n_partes': n,
        'n_vertices': 8 * n, 'n_triangulos': 12 * n}))
    return bg.Geometria(carpeta)


# ── Sin ifcopenshell ─────────────────────────────────────────────────────────

def test_el_rayo_da_con_el_primero_y_respeta_lo_oculto(tmp_path):
    g = _geometria(tmp_path / 'g')
    assert g.elemento_bajo_rayo((-10, 0, 0), (1, 0, 0)) == 0
    assert g.elemento_bajo_rayo((20, 0.3, 0.2), (-1, 0, 0)) == 2
    # oculto el 0, el rayo lo atraviesa
    assert g.elemento_bajo_rayo((-10, 0, 0), (1, 0, 0),
                                np.array([False, True, True])) == 1
    assert g.elemento_bajo_rayo((0, 10, 0), (0, 1, 0)) is None      # detrás
    assert g.elemento_bajo_rayo((2.5, 10, 0), (0, -1, 0)) is None   # entre dos


def test_los_bloques_cubren_todo_con_indices_locales(tmp_path):
    g = _geometria(tmp_path / 'g')
    trozos = list(g.bloques(max_tri=12))
    assert len(trozos) == 3
    for v, i in trozos:
        assert len(v) == 8 and i.min() == 0 and i.max() == 7
    assert sum(len(i) for _v, i in g.bloques()) == 36


def test_la_cache_se_limpia_por_uso_y_no_borra_lo_recien_hecho(cache):
    for n, hace in (('viejo', 900), ('medio', 500), ('nuevo', 10)):
        _geometria(cache / n)
        os.utime(cache / n, (time.time() - hace,) * 2)
    peso = sum(f.stat().st_size for f in (cache / 'nuevo').iterdir())
    bg.limpiar_cache(max_bytes=2 * peso, conservar='nuevo')
    assert sorted(d.name for d in cache.iterdir()) == ['medio', 'nuevo']


def test_una_cache_rota_se_descarta(cache, tmp_path):
    f = tmp_path / 'a.ifc'
    f.write_text('x')
    d = cache / bg.huella(f)
    _geometria(d)
    (d / 'meta.json').write_text('{roto')
    assert bg.abrir_cache(f) is None
    assert not d.exists()


def test_sin_ifcopenshell_el_error_es_claro(cache, tmp_path, monkeypatch):
    f = tmp_path / 'a.ifc'
    f.write_text('x')
    monkeypatch.setattr(bg, 'disponible', lambda: False)
    with pytest.raises(bg.ErrorGeometria, match='IfcOpenShell'):
        bg.convertir(f)


def test_si_el_proceso_hijo_se_cae_hay_mensaje_y_no_quedan_restos(
        cache, tmp_path, monkeypatch):
    f = tmp_path / 'a.ifc'
    f.write_text('x')
    monkeypatch.setattr(bg, 'disponible', lambda: True)
    monkeypatch.setattr(bg, 'comando', lambda r, d: [
        sys.executable, '-c', 'import os, signal; os.kill(os.getpid(), 11)'])
    with pytest.raises(bg.ErrorGeometria, match='se cerró'):
        bg.convertir(f)
    assert list(cache.iterdir()) == []


# ── Con ifcopenshell ─────────────────────────────────────────────────────────

@con_ifc
def test_convierte_un_ifc_con_pisos_colores_y_coordenadas_grandes(cache, tmp_path):
    f = tmp_path / 'casa.ifc'
    muro, losa = _ifc(f)
    avance = []
    g = bg.convertir(f, progreso=avance.append)
    assert {e.global_id: (e.clase, e.nombre, e.piso) for e in g.elementos} == {
        muro: ('IfcWall', 'Muro', 'Piso 1'), losa: ('IfcSlab', 'Losa', 'Piso 2')}
    assert g.pisos == ['Piso 1', 'Piso 2']       # por elevación, no por orden
    assert avance
    # coordenadas de 8 000 km: en float32 crudas se perderían los 20 cm
    a, b = g.caja_de([muro])
    assert [round(y - x, 3) for x, y in zip(a, b)] == [4.0, 3.0, 0.2]
    azul = g.colores[g.elementos[g.por_id[losa]].partes[0]]
    assert azul.tolist() == [0, 0, 255, 255]
    # segunda vez: de la caché, sin lanzar nada
    sin = bg.comando
    try:
        bg.comando = lambda *_a: pytest.fail('volvió a convertir')
        assert bg.convertir(f).n_triangulos == g.n_triangulos
    finally:
        bg.comando = sin


@con_ifc
def test_un_archivo_que_no_es_ifc_da_mensaje(cache, tmp_path):
    f = tmp_path / 'a.ifc'
    f.write_text('esto no es un IFC')
    with pytest.raises(bg.ErrorGeometria, match='no es un IFC válido'):
        bg.convertir(f)


@con_ifc
def test_main_atiende_el_proceso_auxiliar_sin_abrir_la_app(tmp_path):
    """El binario se relanza a sí mismo: debe convertir sin Qt ni BD."""
    import subprocess
    f, d = tmp_path / 'casa.ifc', tmp_path / 'd'
    _ifc(f)
    d.mkdir()
    main = os.path.join(os.path.dirname(__file__), '..', 'main.py')
    datos = tmp_path / 'datos'
    r = subprocess.run([sys.executable, main, bg.OPCION_PROCESO, str(f), str(d)],
                       timeout=60, env={**os.environ, 'XDG_DATA_HOME': str(datos)})
    assert r.returncode == 0 and (d / 'meta.json').exists()
    assert not list(datos.rglob('*.db'))


@con_ifc
def test_un_modelo_enorme_se_recorta_con_aviso(tmp_path):
    """Al pasar del tope se corta el iterador y queda lo leído, con aviso."""
    import subprocess
    f, d = tmp_path / 'casa.ifc', tmp_path / 'd'
    _ifc(f)
    d.mkdir()
    raiz = os.path.join(os.path.dirname(__file__), '..')
    r = subprocess.run([sys.executable, '-c', (
        'import sys; sys.path.insert(0, sys.argv[1])\n'
        'from core import bim_geometria as bg\n'
        'bg.MAX_TRIANGULOS = 12\n'
        'bg.proceso_hijo(sys.argv[2:])'), raiz, str(f), str(d)], timeout=60)
    assert r.returncode == 0
    g = bg.Geometria(d)
    assert len(g.elementos) == 1 and 'muy grande' in g.avisos[0]


# ── Vista ────────────────────────────────────────────────────────────────────

@pytest.fixture
def visor(tmp_path, monkeypatch, cache):
    pytest.importorskip('PySide6.QtQuick3D')
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import utils.i18n
    monkeypatch.setattr(utils.i18n, '_idioma_actual', 'es')
    from views import bim_visor as bv
    monkeypatch.setattr(bv, 'motivo_no_disponible', lambda: '')
    f = tmp_path / 'x.ifc'
    f.write_text('x')
    _geometria(cache / bg.huella(f))
    v = bv.BimVisor()
    v.abrir(f, {'gid0': 'vinculado'})
    v.ruta_prueba = f
    yield v
    v.cerrar()
    v.deleteLater()


def test_abre_y_los_ambientes_arrancan_ocultos(visor):
    assert visor._geo is not None
    assert visor.mascara_visibles().tolist() == [True, True, False]
    solida, vidrio = visor.paletas()
    assert solida[:, 3].tolist() == [255, 0, 0]
    assert vidrio[:, 3].tolist() == [0, 110, 0]


def test_color_por_estado(visor):
    from views.bim_visor import COLOR_ESTADO
    visor._combo_color.setCurrentIndex(1)
    assert tuple(visor.paletas()[0][0, :3]) == COLOR_ESTADO['vinculado']
    assert tuple(visor.paletas()[1][1, :3]) == COLOR_ESTADO['sin']
    visor.set_estados({'gid0': 'cambio'})
    assert tuple(visor.paletas()[0][0, :3]) == COLOR_ESTADO['cambio']


def test_resaltar_no_emite_y_el_clic_si(visor):
    from PySide6.QtGui import QVector3D
    from views.bim_visor import COLOR_SELECCION
    salio = []
    visor.seleccion_cambiada.connect(salio.append)
    visor.resaltar(['gid1', 'no-existe'], encuadrar=True)
    assert visor.seleccion() == ['gid1'] and salio == []
    assert tuple(visor.paletas()[0][1]) == (*COLOR_SELECCION, 255)
    visor._tocado(QVector3D(-10, 0, 0), QVector3D(1, 0, 0), False)
    assert salio == [['gid0']]
    visor._tocado(QVector3D(5, 10, 0), QVector3D(0, -1, 0), True)     # Ctrl
    assert salio[-1] == ['gid0', 'gid1']
    visor._tocado(QVector3D(0, 50, 50), QVector3D(0, 1, 0), False)    # al vacío
    assert salio[-1] == []


def test_aislar_ocultar_y_mostrar_todo(visor):
    visor.aislar(['gid1'])
    assert visor.mascara_visibles().tolist() == [False, True, False]
    visor.mostrar_todo()
    visor.ocultar(['gid0'])
    assert visor.mascara_visibles().tolist() == [False, True, False]
    visor.aislar(['no-existe'])            # no deja la vista en blanco
    assert visor.mascara_visibles().any()


def test_resto_transparente(visor):
    from views.bim_visor import ALFA_RESTO
    visor._chk_transp.setChecked(True)
    assert visor.paletas()[0][0, 3] == 255      # sin selección no cambia nada
    visor.resaltar(['gid1'])
    solida, vidrio = visor.paletas()
    assert solida[:, 3].tolist() == [0, 255, 0]
    assert vidrio[0, 3] == ALFA_RESTO


def test_el_arbol_agrupa_y_selecciona_el_grupo(visor):
    salio = []
    visor.seleccion_cambiada.connect(salio.append)
    raices = [visor._arbol.topLevelItem(i) for i in range(visor._arbol.topLevelItemCount())]
    assert [r.text(0) for r in raices] == ['Piso 1  (2)', 'Sin piso  (1)']
    raices[0].setSelected(True)
    assert salio == [['gid1', 'gid2']]
    visor._combo_orden.setCurrentIndex(1)
    assert visor._arbol.topLevelItemCount() == 3
    assert visor.seleccion() == ['gid1', 'gid2']


def test_cerrar_y_reabrir_deja_todo_limpio(visor):
    visor.resaltar(['gid0'])
    visor.cerrar()
    assert visor.seleccion() == [] and visor._geo is None
    visor.abrir(visor.ruta_prueba)
    assert len(visor._mallas) == 3             # un bloque + dos paletas
    assert len(visor._items) == 3


def test_sin_ifcopenshell_la_vista_avisa_y_no_revienta(visor, monkeypatch, tmp_path):
    from views import bim_visor as bv
    monkeypatch.undo()
    import utils.i18n
    monkeypatch.setattr(utils.i18n, '_idioma_actual', 'es')
    monkeypatch.setattr(bg, 'disponible', lambda: False)
    avisos = []
    visor.fallo.connect(avisos.append)
    visor.abrir(tmp_path / 'x.ifc')
    assert len(avisos) == 1 and 'IfcOpenShell' in avisos[0]
    assert visor._paginas.currentWidget() is visor._pag_msj
    assert bv.motivo_no_disponible()


def test_sin_gpu_muestra_el_motivo(visor):
    """Con `offscreen` Qt dibuja por software, que es el caso sin GPU."""
    from PySide6.QtWidgets import QApplication
    avisos = []
    visor.fallo.connect(avisos.append)
    visor.resize(600, 400)
    visor.show()
    fin = time.time() + 5
    while not avisos and time.time() < fin:
        QApplication.processEvents()
        visor._revisar_gpu()
    if QApplication.platformName() != 'offscreen':
        pytest.skip('hay GPU')
    assert avisos and 'aceleración gráfica' in avisos[0]


def _esperar(visor, segundos=60):
    from PySide6.QtWidgets import QApplication
    ok, mal = [], []
    visor.cargado.connect(lambda: ok.append(1))
    visor.fallo.connect(mal.append)
    fin = time.time() + segundos
    while not ok and not mal and time.time() < fin:
        QApplication.processEvents()
        time.sleep(.01)
    return bool(ok), mal


@con_ifc
def test_la_vista_convierte_en_segundo_plano(visor, tmp_path):
    f = tmp_path / 'casa.ifc'
    muro, losa = _ifc(f)
    visor.abrir(f)
    ok, _mal = _esperar(visor)
    assert ok
    visor.resaltar([losa])
    assert visor.seleccion() == [losa]


@con_ifc
def test_cancelar_a_media_carga_no_deja_restos(visor, tmp_path, cache):
    f = tmp_path / 'casa.ifc'
    _ifc(f)
    visor.abrir(f)
    assert visor._proc is not None
    visor.cerrar()
    assert visor._proc is None
    assert not [d for d in cache.iterdir() if d.name.startswith('tmp')]


def test_archivo_que_ya_no_existe(visor, tmp_path):
    avisos = []
    visor.fallo.connect(avisos.append)
    visor.abrir(tmp_path / 'no.ifc')
    assert avisos and 'no.ifc' in avisos[0]
