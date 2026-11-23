# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Complementos: esquema, paquete seguro, gestor, registro, API, reportes.

Corre con:  QT_QPA_PLATFORM=offscreen python3 -m pytest tests/test_complementos.py -q
Usa una COPIA temporal del seed y una carpeta de complementos temporal.
"""
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication                          # noqa: E402

import core.config as cfg                                           # noqa: E402
import core.database as d                                           # noqa: E402

_app = QApplication.instance() or QApplication([])
RAIZ = Path(__file__).resolve().parent.parent
_fd, _tmpdb = tempfile.mkstemp(suffix='_compl_test.db')
os.close(_fd)
shutil.copy(RAIZ / 'presupuestos_seed.db', _tmpdb)
d.DB_PATH = _tmpdb
cfg.DB_PATH = _tmpdb
d.init_db()

from core import paises                                             # noqa: E402
from core.complementos import (cargador, cli, contexto, esquema,    # noqa: E402
                               gestor, paquete, plantilla, registro, reportes)
from ingepresupuestos import api                                    # noqa: E402
from utils import i18n                                              # noqa: E402

BASE = {'esquema': 1, 'id': 'de-prueba', 'nombre': 'De prueba', 'version': '1.0',
        'autor': 'Nadie', 'licencia': 'GPL-3.0-or-later'}


def man(**k):
    return {**BASE, **k}


def codigo(**k):
    return man(api_version=1, codigo='complemento.py', **k)


@pytest.fixture(autouse=True)
def limpio(tmp_path, monkeypatch):
    monkeypatch.setattr(gestor, 'raiz', lambda: tmp_path / 'compl')
    monkeypatch.delenv(gestor.VARIABLE_SEGURO, raising=False)
    conn = d.get_db()
    conn.execute("DELETE FROM configuracion WHERE clave IN ('pais','pais_respaldo',"
                 "'etiqueta_id_tributaria','impuesto_nombre','impuesto_pct',"
                 "'monedas_propias')")
    conn.execute("UPDATE configuracion SET valor='Soles' WHERE clave='moneda_defecto'")
    conn.commit()
    conn.close()
    cfg.olvidar_monedas_propias()
    cargador.fallos[:] = []
    for c in cargador.cargados():
        cargador.descargar(c.id)
    gestor.invalidar()
    yield
    for c in cargador.cargados():
        cargador.descargar(c.id)
    cfg.olvidar_monedas_propias()
    i18n.set_idioma('es')
    monkeypatch.undo()
    gestor.invalidar()


def carpeta(tmp_path, m, archivos=None, nombre='fuente'):
    c = tmp_path / nombre
    c.mkdir(exist_ok=True)
    (c / 'complemento.json').write_text(json.dumps(m), encoding='utf-8')
    for r, t in (archivos or {}).items():
        (c / r).parent.mkdir(parents=True, exist_ok=True)
        (c / r).write_text(t, encoding='utf-8')
    return c


def poner(tmp_path, m, archivos=None):
    """Instala y activa."""
    i = gestor.instalar(carpeta(tmp_path, m, archivos))
    return gestor.activar(i.id, i.paquete.huella)


def zip_de(tmp_path, entradas, nombre='x.zip'):
    r = tmp_path / nombre
    with zipfile.ZipFile(r, 'w', zipfile.ZIP_DEFLATED) as z:
        for n, b in entradas:
            z.writestr(n, b)
    return r


# ── Esquema ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('cambio, donde', [
    ({'inventado': 1}, 'desconocido'),
    ({'id': '../x'}, 'id:'),
    ({'id': 'A'}, 'id:'),
    ({'esquema': 2}, 'esquema'),
    ({'web': 'javascript:alert(1)'}, 'web'),
    ({'codigo': '../a.py', 'api_version': 1}, 'codigo'),
    ({'codigo': 'a.py'}, 'api_version'),
    ({'api_version': True}, 'api_version'),
    ({'paises': [{'iso': 'ar', 'nombre': 'A', 'moneda': 'x', 'identificacion': 'x',
                  'impuesto': {'nombre': 'I', 'pct': 1}}]}, 'iso'),
    ({'paises': [{'iso': 'AR', 'nombre': 'A', 'moneda': 'x', 'identificacion': 'x',
                  'impuesto': {'nombre': 'I', 'pct': 99}}]}, 'pct'),
    ({'monedas': [{'nombre': 'X', 'simbolo': 'x', 'miles': '.', 'decimal': '.'}]},
     'separadores'),
    ({'vocabulario': [{'textos': {'{n} nuevos': 'sin marcador'}}]}, 'marcadores'),
    ({'vocabulario': [{'textos': {'Hola': '<img src=x>'}}]}, 'etiquetas'),
    ({'indices': [{'clave': '../x', 'nombre': 'x'}]}, 'clave'),
    ({'indices': [{'clave': 'A', 'nombre': 'x',
                   'valores': [{'periodo': '2026-13', 'valor': 1}]}]}, 'periodo'),
    ({'unidades': ['%xx']}, 'unidades'),
    ({'titulos': ['a', 'a']}, 'repetidos'),
    ({'nombre': 'con\nsalto'}, 'control'),
])
def test_esquema_rechaza(cambio, donde):
    with pytest.raises(esquema.ErrorEsquema) as e:
        esquema.validar(man(**cambio))
    assert donde in str(e.value)


@pytest.mark.parametrize('crudo', [
    b'[]', b'{', b'{"a":NaN}', b'{"esquema":1,"esquema":1}', b'\xff', b'null',
    b'[' * 100_000, b' ' * (esquema.MAX_JSON + 1)])
def test_json_que_no_vale(crudo):
    with pytest.raises(esquema.ErrorEsquema):
        esquema.leer(crudo)


# ── Paquete ──────────────────────────────────────────────────────────────────

OK = ('complemento.json', json.dumps(BASE))


@pytest.mark.parametrize('nombre', [
    '../fuera.txt', '/etc/x.txt', 'a/../../b.txt', 'C:\\x.txt', 'a\\b.txt',
    'C:x.txt', 'con.txt', 'a/nul.md', 'x /y.txt', 'fin./a.txt', 'a//b.txt',
    './a.txt', 'a/b/c/d/e/f/g.txt', 'x' * 300 + '.txt', 'x.exe', 'x.so', 'x.pyc',
    'x.svg', 'x.html', 'sinext', 'malo.py'])
def test_zip_con_rutas_o_tipos_malos(tmp_path, nombre):
    with pytest.raises(paquete.ErrorPaquete):
        paquete.leer_zip(zip_de(tmp_path, [OK, (nombre, 'x')]))


def test_zip_con_enlace(tmp_path):
    i = zipfile.ZipInfo('enlace.txt')
    i.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(paquete.ErrorPaquete, match='enlace'):
        paquete.leer_zip(zip_de(tmp_path, [OK, (i, '/etc/passwd')]))


def test_bombas(tmp_path, monkeypatch):
    with pytest.raises(paquete.ErrorPaquete):
        paquete.leer_zip(zip_de(tmp_path, [OK, ('a.txt', b'0' * 4_000_000)]))
    with pytest.raises(paquete.ErrorPaquete):
        paquete.leer_zip(zip_de(tmp_path, [OK] + [(f'{n}.txt', 'x')
                                                  for n in range(300)]))
    monkeypatch.setattr(paquete, 'MAX_RATIO', 10**9)
    with pytest.raises(paquete.ErrorPaquete, match='MB'):
        paquete.leer_zip(zip_de(tmp_path, [OK, ('a.txt', b'0' * 6_000_000)]))
    with pytest.raises(paquete.ErrorPaquete, match='MB'):
        paquete.leer_zip(zip_de(tmp_path, [OK] + [
            (f'{n}.txt', b'0' * 4_500_000) for n in range(5)]))


def test_zip_dañado_repetido_o_que_choca(tmp_path):
    f = tmp_path / 'no.zip'
    f.write_bytes(b'nada')
    with pytest.raises(paquete.ErrorPaquete):
        paquete.leer_zip(f)
    with pytest.raises(paquete.ErrorPaquete):
        paquete.leer_zip(zip_de(tmp_path, [OK, ('a.txt', '1'), ('A.TXT', '2')]))
    with pytest.raises(paquete.ErrorPaquete):
        paquete.leer_zip(zip_de(tmp_path, [OK, ('LICENSE', '1'),
                                           ('license/x.txt', '2')]))
    with pytest.raises(paquete.ErrorPaquete):
        paquete.leer_zip(zip_de(tmp_path, [('a.txt', 'x')]))


def test_zip_con_tamaño_que_miente(tmp_path):
    r = zip_de(tmp_path, [OK, ('a.txt', b'0' * 50_000)])
    b = bytearray(r.read_bytes())
    i = b.rindex(b'PK\x01\x02')                 # directorio central de a.txt
    b[i + 24:i + 28] = (10).to_bytes(4, 'little')
    r.write_bytes(bytes(b))
    with pytest.raises(paquete.ErrorPaquete):
        paquete.leer_zip(r)


def test_carpeta_con_enlace(tmp_path):
    c = carpeta(tmp_path, BASE)
    (c / 'x.txt').symlink_to('/etc/hostname')
    with pytest.raises(paquete.ErrorPaquete, match='enlace'):
        paquete.leer_carpeta(c)


def test_zip_con_una_carpeta_raiz_y_empaquetar_es_reproducible(tmp_path):
    c = carpeta(tmp_path, codigo(), {'complemento.py': 'x=1', 'datos/a.csv': '1'})
    (c / '__pycache__').mkdir()
    (c / '__pycache__' / 'x.pyc').write_bytes(b'1')
    a = paquete.empaquetar(c, tmp_path / 'a.zip').read_bytes()
    assert a == paquete.empaquetar(c, tmp_path / 'b.zip').read_bytes()
    p = paquete.leer_zip(tmp_path / 'a.zip')
    assert set(p.archivos) == {'complemento.json', 'complemento.py', 'datos/a.csv'}
    assert p.huella == paquete.leer_carpeta(c).huella


# ── Gestor ───────────────────────────────────────────────────────────────────

MARCA = "import os\nos.environ['MARCA_COMPL'] = 'si'\ndef registrar(app): pass\n"


def test_apagado_al_instalar_y_no_ejecuta_nada(tmp_path, monkeypatch):
    monkeypatch.delenv('MARCA_COMPL', raising=False)
    i = gestor.instalar(carpeta(tmp_path, codigo(), {'complemento.py': MARCA}))
    assert i.estado == 'apagado'
    assert cargador.cargar_activos() == [] and 'MARCA_COMPL' not in os.environ
    gestor.activar(i.id, i.paquete.huella)
    assert 'MARCA_COMPL' not in os.environ
    cargador.cargar_activos()
    assert os.environ.pop('MARCA_COMPL') == 'si'


def test_activar_exige_la_huella_enseñada(tmp_path):
    i = gestor.instalar(carpeta(tmp_path, BASE))
    with pytest.raises(gestor.ErrorGestor):
        gestor.activar(i.id, 'otra')
    (gestor.carpeta_de(i.id) / 'nuevo.txt').write_text('x')
    with pytest.raises(gestor.ErrorGestor, match='cambiaron'):
        gestor.activar(i.id, i.paquete.huella)


def test_si_cambia_deja_de_cargarse(tmp_path, monkeypatch):
    monkeypatch.delenv('MARCA_COMPL', raising=False)
    i = poner(tmp_path, codigo(), {'complemento.py': 'def registrar(app): pass\n'})
    (gestor.carpeta_de(i.id) / 'complemento.py').write_text(MARCA)
    gestor.invalidar()
    assert gestor.uno(i.id).estado == 'cambiado'
    cargador.cargar_activos()
    assert 'MARCA_COMPL' not in os.environ


def test_actualizar_lo_deja_apagado(tmp_path):
    i = poner(tmp_path, BASE)
    assert i.activo
    n = gestor.instalar(carpeta(tmp_path, man(version='2.0')))
    assert n.estado == 'apagado' and n.paquete.manifiesto['version'] == '2.0'


def test_estado_ilegible_es_todo_apagado(tmp_path):
    i = poner(tmp_path, BASE)
    (gestor.raiz() / 'estado.json').write_text('{roto')
    gestor.invalidar()
    assert gestor.activos() == [] and gestor.uno(i.id).estado == 'apagado'


def test_modo_seguro(tmp_path, monkeypatch):
    poner(tmp_path, man(titulos=['X']))
    assert registro.titulos() == ['X']
    monkeypatch.setenv(gestor.VARIABLE_SEGURO, '1')
    gestor.invalidar()
    assert registro.titulos() == [] and cargador.cargar_activos() == []


def test_solo_el_administrador(tmp_path, monkeypatch):
    import utils.auth as a
    from models.usuario import Usuario
    monkeypatch.setattr(a, '_usuario_actual', Usuario(id=9, rol='usuario'))
    with pytest.raises(gestor.ErrorGestor, match='administrador'):
        gestor.instalar(carpeta(tmp_path, BASE))
    assert not gestor.puede_gestionar()


@pytest.mark.parametrize('fuente', [
    'esto no compila (', 'raise RuntimeError("bum")', 'import sys; sys.exit(3)',
    'x = 1', 'def registrar(app): app.reporte("", "", None)',
    'def registrar(app): registrar(app)', 'import no_existe_este_modulo'])
def test_un_complemento_que_falla_se_apaga_y_se_explica(tmp_path, fuente):
    i = poner(tmp_path, codigo(), {'complemento.py': fuente})
    f = cargador.cargar_activos()
    assert len(f) == 1 and f[0][0] == i.id and f[0][1]
    i = gestor.uno(i.id)
    assert i.estado == 'error' and i.error
    assert cargador.cargados() == [] and cargador.cargar_activos() == []


def test_si_el_programa_muere_cargando_lo_apaga(tmp_path):
    i = poner(tmp_path, codigo(), {'complemento.py': 'import os\nos._exit(9)\n'})
    r = subprocess.run([sys.executable, '-c', f'''
import sys; sys.path.insert(0, {str(RAIZ)!r})
from pathlib import Path
from core.complementos import gestor, cargador
gestor.raiz = lambda: Path({str(gestor.raiz())!r})
cargador.cargar_activos()'''])
    assert r.returncode == 9
    gestor.invalidar()
    f = cargador.cargar_activos()
    assert f and f[0][0] == i.id and gestor.uno(i.id).estado == 'error'


def test_el_error_dice_la_linea_del_complemento(tmp_path):
    poner(tmp_path, codigo(), {'complemento.py': '\n\n1/0\n'})
    assert 'complemento.py, línea 3' in cargador.cargar_activos()[0][1]


def test_modulos_del_paquete_y_pyc_ajeno(tmp_path):
    i = poner(tmp_path, codigo(), {
        'complemento.py': 'from .sub.otro import V\n'
                          'def registrar(app): app.accion("a", V, print)\n',
        'sub/otro.py': 'V = "bueno"\n'})
    c = gestor.carpeta_de(i.id) / '__pycache__'
    c.mkdir()
    (c / 'complemento.cpython-312.pyc').write_bytes(b'basura')
    gestor.invalidar()
    assert cargador.cargar_activos() == []
    assert cargador.cargados()[0].registros[0].titulo == 'bueno'
    assert not list(gestor.carpeta_de(i.id).glob('sub/__pycache__'))
    gestor.desactivar(i.id)
    assert cargador.cargados() == []
    assert not [m for m in sys.modules if 'de_prueba' in m]


def test_api_mas_nueva_no_se_activa(tmp_path):
    i = gestor.instalar(carpeta(tmp_path, man(api_version=99, codigo='complemento.py'),
                                {'complemento.py': ''}))
    with pytest.raises(gestor.ErrorGestor, match='API 99'):
        gestor.activar(i.id, i.paquete.huella)


def test_recargar_pide_activar_otra_vez_si_cambia(tmp_path):
    i = poner(tmp_path, codigo(), {'complemento.py': 'def registrar(app): pass\n'})
    assert gestor.recargar(i.id).activo           # igual: sigue activo
    (tmp_path / 'fuente' / 'complemento.py').write_text(MARCA)
    assert gestor.recargar(i.id).estado == 'apagado'


# ── Registro: países, moneda, vocabulario, listas ────────────────────────────

def test_los_paises_de_fabrica_dan_lo_mismo_que_antes():
    """Foto tomada con el código anterior al registro (commit cec8ae8)."""
    from core.pie import lineas_por_defecto
    foto = json.loads((RAIZ / 'tests/fixtures/paises_antes_de_complementos.json')
                      .read_text(encoding='utf-8'))
    assert set(foto) == {'', *paises.PAISES}
    proys = ({'igv_pct': None, 'gf_pct': None, 'utilidad_pct': None},
             {'igv_pct': 0.0, 'gf_pct': 0, 'utilidad_pct': 0},
             {'igv_pct': 12.5, 'gf_pct': 7.0, 'utilidad_pct': 3.0})
    for iso, antes in foto.items():
        if iso:
            paises.aplicar_pais(iso)
        p = {k: v for k, v in paises.perfil().items()
             if k not in ('pie', 'indirectos')}
        ahora = dict(iso=paises.pais_actual(), etq=paises.etiqueta_tributaria(),
                     imp=paises.impuesto(), ind=paises.indirectos_defecto(),
                     centro=paises.centro_mapa(), rubro=paises.nombre_rubro_impuesto(),
                     perfil=p, pies=[lineas_por_defecto(x) for x in proys])
        assert json.loads(json.dumps(ahora)) == antes, iso


PAIS_X = {'iso': 'CU', 'nombre': 'Cuba', 'moneda': 'Pesos X', 'identificacion': 'IDX',
          'impuesto': {'nombre': 'IMX', 'pct': 10},
          'pie': [{'codigo': 'GG', 'nombre': 'Indirectos', 'tipo': 'pct_cd',
                   'pct': 'gastos_generales'},
                  {'codigo': 'IGV', 'nombre': '{impuesto_pct}', 'tipo': 'pct_sub',
                   'pct': 'impuesto'}]}
MON_X = {'nombre': 'Pesos X', 'simbolo': 'X$', 'miles': '.', 'decimal': ','}


def test_pais_nuevo_y_desinstalar_no_rompe_nada(tmp_path):
    from core.pie import lineas_por_defecto
    from utils.formatting import fmt
    i = poner(tmp_path, man(paises=[PAIS_X], monedas=[MON_X]))
    paises.aplicar_pais('CU')
    proy = {'igv_pct': 10.0, 'gf_pct': 8.0, 'utilidad_pct': 0}
    assert [l[1] for l in lineas_por_defecto(proy)] == ['Indirectos', 'IMX (10%)']
    assert fmt(1234.5, 'Pesos X') == 'X$ 1.234,50'
    gestor.desinstalar(i.id)
    assert gestor.instalados() == []
    assert paises.pais_configurado() == 'CU'           # no vuelve a preguntar
    assert paises.perfil()['nombre'] == 'Cuba'
    assert paises.etiqueta_tributaria() == 'IDX' and not paises.es_peru()
    assert fmt(1234.5, 'Pesos X') == 'X$ 1.234,50'     # el proyecto imprime igual
    from views.pais_dialog import PaisForm
    assert PaisForm().iso() == 'CU'


def test_avisa_antes_de_pisar_lo_de_fabrica(tmp_path):
    pe = {**PAIS_X, 'iso': 'PE', 'nombre': 'Perú'}
    i = gestor.instalar(carpeta(tmp_path, man(paises=[pe], monedas=[
        {**MON_X, 'nombre': 'Soles'}])))
    c = gestor.conflictos(i.paquete)
    assert len(c) == 2 and 'Perú' in c[0] and 'Soles' in c[1]
    assert paises.perfil('PE')['id'] == 'RUC'          # instalar no pisa
    gestor.activar(i.id, i.paquete.huella)
    assert paises.perfil('PE')['id'] == 'IDX'
    assert cfg.moneda_cfg('Soles')['simbolo'] == 'S/'  # la moneda nunca se pisa
    gestor.desactivar(i.id)
    assert paises.perfil('PE')['id'] == 'RUC'


def test_vocabulario_por_idioma_y_pais(tmp_path):
    i18n.set_idioma('es')
    i = poner(tmp_path, man(vocabulario=[
        {'pais': 'AR', 'textos': {'Título': 'Rubro'}}]))
    assert i18n.tr('Título') == 'Título'
    paises.aplicar_pais('AR')
    assert i18n.tr('Título') == 'Rubro'
    i18n.set_idioma('en')
    assert i18n.tr('Título') == 'Title'
    i18n.set_idioma('es')
    gestor.desactivar(i.id)
    assert i18n.tr('Título') == 'Título'


def test_unidades_y_titulos(tmp_path):
    from core import unidades
    antes = unidades.lista()
    poner(tmp_path, man(unidades=['vara', 'm2'], titulos=['OBRAS DE PRUEBA']))
    ahora = unidades.lista()
    assert 'vara' in ahora and [u for u in ahora if u != 'vara'] == antes
    from views.agregar_titulo_dialog import AgregarTituloDialog
    dlg = AgregarTituloDialog(1, None)
    dlg.inp_buscar.setText('obras de prueba')
    dlg._buscar_titulos()
    assert dlg.lst_titulos.item(dlg.lst_titulos.count() - 1).text() == 'OBRAS DE PRUEBA'


def test_indice_del_usuario_sobrevive_a_desinstalar(tmp_path):
    f = tmp_path / 'cac.csv'
    f.write_text('Periodo;Valor\n2026-01;1.234,50\n02/2026;1300\n')
    src = RAIZ / 'complementos' / 'pais-argentina'
    gestor.instalar(src)
    assert gestor.indice('pais-argentina', 'CAC') == []
    assert gestor.importar_indice('pais-argentina', 'CAC', f) == 2
    esperado = [('2026-01', 1234.5), ('2026-02', 1300.0)]
    assert gestor.indice('pais-argentina', 'CAC') == esperado
    gestor.desinstalar('pais-argentina')
    gestor.instalar(src)
    assert gestor.indice('pais-argentina', 'CAC') == esperado
    for malo in ('', 'a;b', '2026-01;x', '2026-01;1\n2026-01;2', '2026-01;1\nx;2'):
        with pytest.raises(gestor.ErrorGestor):
            gestor.leer_csv_indice(malo)


# ── Importador de Excel: SINAPI ──────────────────────────────────────────────

def _libro_sinapi():
    """La FORMA de la planilla (issue #21) con datos inventados."""
    from core import importar_excel_insumos as imp
    filas = [['Mês de Referência:', '09/2026'], [],
             ['Classificação', 'Código do Insumo', 'Descrição do Insumo', 'Unidade',
              'Origem de Preço', 'AC', 'MG', 'SP'],
             ['MATERIAL', 1.0, 'MATERIAL INVENTADO', 'KG', 'C', 1.0, 2.5, 3.0],
             ['EQUIPAMENTO (LOCAÇÃO)', 2.0, 'EQUIPO INVENTADO', 'H', 'C', 1, 4, 3],
             ['EQUIPAMENTO (AQUISIÇÃO)', 3.0, 'OTRO EQUIPO', 'UN', 'C', 1, 5, 3],
             ['ENCARGOS COMPLEMENTARES', 4.0, 'ENCARGO', 'H', 'C', 1, 6, 3],
             ['SERVIÇOS', 5.0, 'SERVICIO', 'M2', 'C', 1, 7, 3],
             ['ESPECIAIS', 6.0, 'ESPECIAL', 'UN', 'C', 1, 8, 3],
             ['MÃO DE OBRA', 7.0, 'PEDREIRO', 'H', 'C', 1, 9, 3]]
    return imp, imp.Libro('x.xlsx', ['Menu', 'ISD'], {'Menu': [['x']], 'ISD': filas},
                          'Menu')


def test_sinapi_con_y_sin_el_complemento():
    imp, libro = _libro_sinapi()
    filas = libro.filas['ISD']
    op = imp.configuracion_inicial(filas, 'ISD', impuesto_pct=0)
    # Lo que reportó el colaborador: sin ajuste, el precio y el código mal.
    assert op.columnas['precio'] == 4 or op.columnas['descripcion'] == 1
    i = gestor.instalar(RAIZ / 'complementos' / 'pais-brasil')
    gestor.activar(i.id, i.paquete.huella)
    assert imp.hoja_inicial(libro) == 'ISD'
    op = imp.configuracion_inicial(filas, 'ISD', impuesto_pct=0)
    assert op.fila_cabecera == 2
    assert {k: v for k, v in op.columnas.items() if v is not None} == {
        'tipo': 0, 'codigo': 1, 'descripcion': 2, 'unidad': 3}
    assert imp.faltantes(op) == ['precio']         # el estado lo elige el usuario
    op.columnas['precio'] = 6
    ins, omit = imp.preparar_insumos(filas, op)
    assert omit == []
    assert [(x.tipo, x.precio) for x in ins] == [
        ('MAT', 2.5), ('EQ', 4), ('EQ', 5), ('MO', 6), ('SC', 7), ('MAT', 8), ('MO', 9)]
    assert 'tipos_extra' not in json.loads(op.a_json())


def test_el_dialogo_dice_que_reconocio_el_formato():
    _imp, libro = _libro_sinapi()
    i = gestor.instalar(RAIZ / 'complementos' / 'pais-brasil')
    gestor.activar(i.id, i.paquete.huella)
    from PySide6.QtCore import QSettings
    from views.importar_excel_dialog import ImportarExcelDialog
    s = QSettings(os.path.join(tempfile.mkdtemp(), 'x.ini'), QSettings.IniFormat)
    dlg = ImportarExcelDialog(libro, settings=s)
    assert 'SINAPI' in dlg.lbl_aviso.text() and 'estado' in dlg.lbl_aviso.text()
    assert not dlg.b_ok.isEnabled()


def test_un_complemento_no_reemplaza_la_lista_del_mtop(tmp_path):
    from core import importar_excel_insumos as imp
    filas = [['LISTA OFICIAL DE PRECIOS'], ['+', 'DESCRIPCIÓN', 'CANTIDAD',
                                            'PRECIOS MAS IVA'],
             [1, 'ARENA', '1 m3', 122]]
    antes = imp.configuracion_inicial(filas, 'h', impuesto_pct=18)
    poner(tmp_path, man(importadores_excel=[{
        'nombre': 'x', 'detectar': ['DESCRIPCIÓN', 'CANTIDAD'],
        'columnas': {'descripcion': ['CANTIDAD']}}]))
    assert imp.configuracion_inicial(filas, 'h', impuesto_pct=18) == antes


# ── Los entregados ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('d_', sorted((RAIZ / 'complementos').iterdir()),
                         ids=lambda x: x.name)
def test_los_incluidos_son_validos_y_cargan(d_):
    p = paquete.leer_carpeta(d_)
    errores, avisos = cli.revisar(p)
    assert (errores, avisos) == ([], []) and p.id == d_.name
    i = gestor.instalar(d_)
    gestor.activar(i.id, i.paquete.huella)
    assert cargador.cargar_activos() == []
    assert bool(cargador.cargados()) == p.con_codigo


def test_brasil_avisa_lo_que_cambia_y_argentina_no_pisa():
    br = paquete.leer_carpeta(RAIZ / 'complementos' / 'pais-brasil')
    assert gestor.conflictos(br) == [
        "País Brasil: cambia respecto del de fábrica — identificación tributaria"]
    ar = paquete.leer_carpeta(RAIZ / 'complementos' / 'pais-argentina')
    assert gestor.conflictos(ar) == []
    assert ar.manifiesto['indices'][0]['valores'] == []


# ── API: lectura, escritura, reportes ────────────────────────────────────────

@pytest.fixture
def admin(monkeypatch):
    import utils.auth as a
    from models.usuario import Usuario
    conn = d.get_db()
    r = conn.execute("SELECT id FROM usuarios WHERE rol='admin' LIMIT 1").fetchone()
    conn.close()
    u = Usuario(id=r[0] if r else 1, nombre='A', rol='admin')
    monkeypatch.setattr(a, '_usuario_actual', u)
    return u


@pytest.fixture
def pid():
    conn = d.get_db()
    r = conn.execute("""SELECT p.proyecto_id FROM partidas p
        JOIN acu_items a ON a.partida_id=p.id GROUP BY p.proyecto_id
        ORDER BY COUNT(*) LIMIT 1""").fetchone()
    conn.execute("UPDATE proyectos SET estado='elaboracion' WHERE id=?", (r[0],))
    conn.commit()
    conn.close()
    return r[0]


def test_la_foto_cuadra_con_el_programa(pid, admin):
    p = contexto.presupuesto(pid, admin)
    t = d.calcular_totales(pid)[1]
    assert p.costo_directo == t['cd'] and p.total == t['total']
    assert sum(x.parcial for x in p.hojas()) == pytest.approx(t['cd'])
    assert any(x.acu for x in p.hojas())
    with pytest.raises(Exception):
        p.total = 1
    with pytest.raises(Exception):
        p.partidas[0].descripcion = 'x'


def test_no_se_lee_un_proyecto_ajeno(pid):
    from models.usuario import Usuario
    conn = d.get_db()
    uid = conn.execute("INSERT INTO usuarios (nombre, email, password_hash, rol)"
                       " VALUES ('A','a@x','x','usuario')").lastrowid
    conn.execute("UPDATE proyectos SET usuario_id=? WHERE id=?", (uid, pid))
    conn.commit()
    conn.close()
    try:
        with pytest.raises(api.ErrorComplemento):
            contexto.presupuesto(pid, Usuario(id=uid + 999, rol='usuario'))
    finally:
        conn = d.get_db()
        conn.execute("UPDATE proyectos SET usuario_id=NULL WHERE id=?", (pid,))
        conn.execute("DELETE FROM usuarios WHERE id=?", (uid,))
        conn.commit()
        conn.close()


def _ctx(pid, admin, tmp_path):
    from core.mcp_deshacer import Pila

    class Ui:
        textos = []
        def avisar(self, t): self.textos.append(t)
        def preguntar(self, t): return True
        def pedir_archivo(self, e=()): return None
    c = cargador.Cargado('de-prueba', 'De prueba', '', paquete.Paquete(
        BASE, {'datos/a.csv': b'1'}, ''))
    return contexto.ContextoReal(c, pid, admin, Ui(), Pila(tmp_path / 'pila'))


def test_escribir_entra_en_el_deshacer_y_falla_entero(pid, admin, tmp_path):
    from core import mcp_deshacer
    ctx = _ctx(pid, admin, tmp_path)
    antes = len(ctx.presupuesto.partidas)
    ids = ctx.editar.agregar([
        api.PartidaNueva('TITULO NUEVO', es_titulo=True, item='90'),
        api.PartidaNueva('PARTIDA NUEVA', 'm2', 12.5, padre='90')])
    p = ctx.presupuesto
    assert len(ids) == 2 and len(p.partidas) == antes + 2
    nueva = next(x for x in p.partidas if x.id == ids[1])
    assert (nueva.item, nueva.metrado) == ('90.01', 12.5)
    pila = ctx.operaciones.pila
    assert pila.resumen()['herramienta'] == 'complemento:de-prueba'
    with pytest.raises(api.ErrorComplemento):
        ctx.editar.agregar([api.PartidaNueva('BUENA', 'm2'),
                            api.PartidaNueva('MALA', '', padre='no-existe')])
    assert len(ctx.presupuesto.partidas) == antes + 2
    assert mcp_deshacer.deshacer_ultima(pila)['undone'] == 'complemento:de-prueba'
    assert len(ctx.presupuesto.partidas) == antes


def test_lo_que_escribe_entra_en_ctrl_z(pid, admin, tmp_path):
    from core.historial import Historial
    h = Historial(pid)
    ctx = _ctx(pid, admin, tmp_path)
    antes = len(ctx.presupuesto.partidas)
    ctx.editar.agregar([api.PartidaNueva('A', 'm2', 1), api.PartidaNueva('B', 'm2')])
    assert h.revisar() and len(h.hechos) == 1            # una acción, un paso
    h.deshacer()
    assert len(ctx.presupuesto.partidas) == antes
    h.rehacer()
    assert len(ctx.presupuesto.partidas) == antes + 2


def test_los_ejemplos_de_la_guia_son_validos():
    t = (RAIZ / 'docs' / 'complementos.md').read_text(encoding='utf-8')
    for b in re.findall(r'```json\n(.*?)```', t, re.S):
        x = json.loads(b)
        seccion = ('paises' if 'iso' in x else 'vocabulario' if 'idioma' in x
                   else 'importadores_excel')
        esquema.validar(x if 'esquema' in x else man(**{seccion: [x]}))
    ns = {}
    exec(re.search(r'```python\n(.*?)```', t, re.S)[1], ns)
    from ingepresupuestos.pruebas import presupuesto_ejemplo
    reportes.comprobar(ns['generar'](presupuesto_ejemplo()))
    faltan = [k for k in esquema._LISTAS if f'`{k}`' not in t]
    assert faltan == [], faltan


def test_escribir_respeta_estado_invitado_y_proyecto(pid, admin, tmp_path):
    from models.usuario import Usuario
    ctx = _ctx(pid, admin, tmp_path)
    for malo in (-1, float('nan'), '3', None, True):
        with pytest.raises(api.ErrorComplemento):
            ctx.editar.fijar_precio(1, malo)
    conn = d.get_db()
    otra = conn.execute("SELECT id FROM partidas WHERE proyecto_id<>? LIMIT 1",
                        (pid,)).fetchone()[0]
    with pytest.raises(api.ErrorComplemento, match='otro proyecto'):
        ctx.editar.renombrar(otra, 'x')
    conn.execute("UPDATE proyectos SET estado='aprobado' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    with pytest.raises(api.ErrorComplemento, match='Aprobado'):
        ctx.editar.agregar([api.PartidaNueva('X', 'm2')])
    inv = _ctx(pid, Usuario(id=admin.id, rol='invitado'), tmp_path)
    with pytest.raises(api.ErrorComplemento):
        inv.editar.agregar([api.PartidaNueva('X', 'm2')])


def test_recursos_del_complemento(pid, admin, tmp_path):
    ctx = _ctx(pid, admin, tmp_path)
    assert ctx.recurso('datos/a.csv') == b'1'
    with pytest.raises(api.ErrorComplemento):
        ctx.recurso('../../etc/passwd')


def _cargar(nombre):
    i = gestor.instalar(RAIZ / 'complementos' / nombre)
    gestor.activar(i.id, i.paquete.huella)
    assert cargador.cargar_activos() == []
    return next(c for c in cargador.cargados() if c.id == nombre)


def _texto_pdf(ruta):
    import pdfplumber
    with pdfplumber.open(ruta) as f:
        return "\n".join(x.extract_text() or '' for x in f.pages)


def test_apu_chile_en_pdf_y_excel(pid, admin, tmp_path):
    conn = d.get_db()
    conn.execute("UPDATE proyectos SET moneda='Pesos Chilenos' WHERE id=?", (pid,))
    conn.commit()
    conn.close()
    c = _cargar('apu-chile')
    p = contexto.presupuesto(pid, admin)
    import dataclasses
    con_acu = next(x for x in p.hojas() if x.acu)
    chico = dataclasses.replace(p, partidas=tuple(
        x for x in p.partidas if x.es_titulo) + (con_acu,))
    r = c.de('reporte')[0]
    reportes.generar(r, chico, tmp_path / 'a.pdf')
    t = _texto_pdf(tmp_path / 'a.pdf')
    for s in ('A.- MATERIALES', 'B.- EQUIPOS, MAQUINARIAS Y TRANSPORTE',
              'C.- MANO DE OBRA', 'D.- VARIOS', 'COSTO DIRECTO UNITARIO NETO',
              'PRECIO UNITARIO NETO', 'Total Neto Partida'):
        assert s in t, s
    assert 'uadrilla' not in t and 'endimiento' not in t
    assert t.index('A.- MAT') < t.index('B.- EQ') < t.index('C.- MANO') < t.index('D.- V')
    assert not re.search(r'\$ [\d.]+,\d', t)              # pesos enteros
    reportes.generar(r, p, tmp_path / 'a.xlsx')
    from openpyxl import load_workbook
    ws = load_workbook(tmp_path / 'a.xlsx').active
    f = next(f for f in ws.iter_rows() if f[0].value == 'PRECIO UNITARIO NETO PARTIDA')
    assert f[4].value == round(f[4].value) and f[4].number_format == '#,##0'


def test_apu_chile_lo_impreso_suma_y_el_neto_lleva_gg_y_utilidad(pid, admin):
    c = _cargar('apu-chile')
    p = contexto.presupuesto(pid, admin)
    mod = sys.modules[c.registros[0].funcion.__module__]
    for x in p.hojas():
        r = mod.calcular(x)
        for _l, _n, lineas, sub in r['bloques']:
            assert sub == sum(t for _i, t in lineas)
        assert r['directo'] == int(r['directo'])
        if x.acu:
            assert sum(len(b[2]) for b in r['bloques']) == len(x.acu)
    doc = c.de('reporte')[1].funcion(p)
    assert isinstance(doc, api.Documento)


def test_reporte_de_ejemplo(pid, admin, tmp_path):
    c = _cargar('reporte-ejemplo')
    reportes.generar(c.de('reporte')[0], contexto.presupuesto(pid, admin),
                     tmp_path / 'r.pdf')
    assert 'Diez insumos' in _texto_pdf(tmp_path / 'r.pdf')


def test_el_reporte_no_inyecta_html_ni_formulas(pid, admin, tmp_path):
    doc = api.Documento('T', [api.Parrafo('<b>hola</b><img src="file:///etc/passwd">'),
                              api.Tabla([api.Columna('a')], [['=1+1'], ['<i>x</i>']])])
    r = api._Registro('reporte', 'x', 'X', lambda p: doc, {'formatos': ('pdf', 'xlsx')})
    p = contexto.presupuesto(pid, admin)
    reportes.generar(r, p, tmp_path / 'x.xlsx')
    from openpyxl import load_workbook
    celdas = [c for f in load_workbook(tmp_path / 'x.xlsx').active.iter_rows()
              for c in f if c.value == '=1+1']
    assert celdas and celdas[0].data_type == 's'
    reportes.generar(r, p, tmp_path / 'x.pdf')
    assert '<img src=' in _texto_pdf(tmp_path / 'x.pdf')


@pytest.mark.parametrize('malo', [
    None, 'x', api.Documento('T', ['x']),
    api.Documento('T', [api.Tabla([api.Columna('a')], [[1, 2]])]),
    api.Documento('T', [api.Tabla([], [])]),
    api.Documento('T', [api.Parrafo('x', alinear='" onload="')])])
def test_un_reporte_malo_no_pisa_el_archivo(pid, admin, tmp_path, malo):
    r = api._Registro('reporte', 'x', 'X', lambda p: malo, {'formatos': ('pdf',)})
    f = tmp_path / 'x.pdf'
    f.write_text('de antes')
    with pytest.raises(api.ErrorComplemento):
        reportes.generar(r, contexto.presupuesto(pid, admin), f)
    assert f.read_text() == 'de antes' and len(list(tmp_path.glob('.ingeppto*'))) == 0


# ── Menú, gestor (ventana) y línea de comandos ───────────────────────────────

FUENTE_MENU = '''
from ingepresupuestos import api
def registrar(app):
    app.accion("a", "Acción", lambda ctx: ctx.editar.renombrar(
        ctx.presupuesto.partidas[0].id, "RENOMBRADA"))
    app.accion("b", "Rota", lambda ctx: 1/0)
    app.reporte("r", "Reporte", lambda p: api.Documento("R", [api.Parrafo("x")]))
    app.importador("i", "Cosas", lambda ruta, ctx: [api.PartidaNueva("IMPORTADA", "m2")],
                   extensiones=("csv",))
    app.validador("v", "Cosas", lambda p: [api.Aviso("ojo")])
'''


def test_menu(tmp_path, pid, admin, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from core import mcp_deshacer
    from views import complementos_menu as cm
    pila = mcp_deshacer.Pila(tmp_path / 'pila')
    monkeypatch.setattr(cm, '_puente', lambda v: None)
    monkeypatch.setattr(mcp_deshacer, 'Pila', lambda *a, **k: pila)
    padre = QWidget()
    assert cm.menu_complementos(padre, None, pid) is None
    poner(tmp_path, codigo(), {'complemento.py': FUENTE_MENU})
    assert cargador.cargar_activos() == []
    m = cm.menu_complementos(padre, None, pid)
    assert [a.text() for a in m.actions()] == [
        'Acción', 'Rota', 'Reporte (PDF)', 'Reporte (Excel)', 'Importar: Cosas…',
        'Revisar: Cosas']
    dichos = []
    for n in ('avisar', 'error'):
        monkeypatch.setattr(cm.Interfaz, n, lambda s, t: dichos.append(t))
    monkeypatch.setattr(cm.Interfaz, 'preguntar', lambda s, t: True)
    c = cargador.cargados()[0]
    a, b = c.de('accion')
    assert cm.ejecutar_accion(padre, None, c, a, pid)
    assert contexto.presupuesto(pid, admin).partidas[0].descripcion == 'RENOMBRADA'
    assert not cm.ejecutar_accion(padre, None, c, b, pid)
    assert 'ZeroDivisionError' in dichos[-1] and 'línea' in dichos[-1]
    assert cm.ejecutar_reporte(padre, c, c.de('reporte')[0], pid, 'pdf',
                               str(tmp_path / 'z.pdf'))
    assert (tmp_path / 'z.pdf').stat().st_size > 500
    assert cm.ejecutar_importador(padre, None, c, c.de('importador')[0], pid, 'x.csv')
    assert any(x.descripcion == 'IMPORTADA'
               for x in contexto.presupuesto(pid, admin).partidas)
    assert cm.ejecutar_validador(padre, c, c.de('validador')[0], pid)
    assert dichos[-1] == '• ojo'


def test_consentimiento_y_gestor(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from views import complementos_dialog as cd
    i = gestor.instalar(carpeta(tmp_path, codigo(autor='<b>X</b>'),
                                {'complemento.py': 'def registrar(app): pass\n'}))
    c = cd.ConsentimientoDialog(i)
    assert not c.btn.isEnabled() and len(c.chks) == 1
    ver = c.ver.toPlainText()
    for s in ('<b>X</b>', 'GPL-3.0-or-later', 'complemento.py', i.paquete.huella):
        assert s in ver
    c.chks[0].setChecked(True)
    assert c.btn.isEnabled()


def test_gestor_explica_lo_que_no_se_puede_instalar(tmp_path, monkeypatch):
    from views import complementos_dialog as cd
    dichos = []
    monkeypatch.setattr(cd, '_aviso', lambda p, t, *a: dichos.append(t))
    g = cd.ComplementosDialog()
    g.instalar(zip_de(tmp_path, [('a.txt', 'x')]))
    assert 'complemento.json' in dichos[0]
    assert gestor.instalados() == []


def test_configuracion_tiene_su_seccion():
    from views.configuracion_view import ConfiguracionView
    v = ConfiguracionView()
    v.set_tab('complementos')
    assert ConfiguracionView._ultima_seccion == 'complementos'


@pytest.mark.parametrize('nombre, datos', [
    ('Mi "reporte" ñandú {x}', False), ('123', False), ('Solo datos', True), ('é', True)])
def test_plantilla_valida_y_funciona(tmp_path, nombre, datos):
    c = plantilla.crear(nombre, tmp_path, datos=datos)
    p = paquete.leer_carpeta(c)
    assert cli.revisar(p)[0] == []
    i = gestor.instalar(c)
    gestor.activar(i.id, i.paquete.huella)
    assert cargador.cargar_activos() == []
    if not datos:
        from ingepresupuestos.pruebas import presupuesto_ejemplo
        doc = cargador.cargados()[0].de('reporte')[0].funcion(presupuesto_ejemplo())
        reportes.comprobar(doc)
    with pytest.raises(FileExistsError):
        plantilla.crear(nombre, tmp_path)


def test_linea_de_comandos(tmp_path, capsys):
    assert cli.main(['--nuevo-complemento', 'Hola', str(tmp_path)]) == 0
    assert cli.main(['--validar-complemento', str(tmp_path / 'hola')]) == 0
    assert 'Válido' in capsys.readouterr().out
    z = tmp_path / 'h.zip'
    assert cli.main(['--empaquetar-complemento', str(tmp_path / 'hola'), str(z)]) == 0
    assert cli.main(['--validar-complemento', str(z)]) == 0
    (tmp_path / 'hola' / 'complemento.py').write_text('import core.database\n')
    assert cli.main(['--validar-complemento', str(tmp_path / 'hola')]) == 1
    out = capsys.readouterr().out
    assert 'no define registrar' in out and 'core.database' in out
    assert cli.main(['--textos-de-complemento', 'título']) == 0
    assert '"Agregar título"' in capsys.readouterr().out
    assert cli.main(['--validar-complemento']) == 2


def test_main_atiende_la_linea_de_comandos_sin_qt(tmp_path):
    r = subprocess.run([sys.executable, str(RAIZ / 'main.py'), '--nuevo-complemento',
                        'Por main', str(tmp_path)], capture_output=True, text=True,
                       env={**os.environ, 'XDG_DATA_HOME': str(tmp_path / 'xdg')})
    assert r.returncode == 0 and (tmp_path / 'por-main' / 'complemento.py').exists()
    assert not (tmp_path / 'xdg').exists()      # ni base de datos ni carpeta


# ── Barreras ─────────────────────────────────────────────────────────────────

def test_la_ia_no_puede_instalar_ni_activar():
    from core import mcp_esquemas
    for h in mcp_esquemas.HERRAMIENTAS:
        assert not re.search('complement|plugin|addon|extension', json.dumps(h), re.I)
    for f in [*RAIZ.glob('core/mcp_*.py'), RAIZ / 'views/mcp_puente.py']:
        assert 'complementos' not in f.read_text(encoding='utf-8'), f.name


def test_nada_usa_la_red():
    for f in [*RAIZ.glob('core/complementos/*.py'), *RAIZ.glob('ingepresupuestos/*.py'),
              *RAIZ.glob('views/complementos_*.py'), *RAIZ.glob('complementos/*/*.py')]:
        t = f.read_text(encoding='utf-8')
        assert not re.search(r'import (urllib|socket|requests|http)\b|QtNetwork', t), f


def test_va_en_todos_los_paquetes():
    spec = (RAIZ / 'ingepresupuestos.spec').read_text(encoding='utf-8')
    assert "('complementos', " in re.sub(r' +', ' ', spec)
    assert "'ingepresupuestos.api'" in spec
    for y in RAIZ.glob('installer/*/com.ingepresupuestos.IngePresupuestos.yml'):
        t = y.read_text(encoding='utf-8')
        assert 'cp -a complementos core ingepresupuestos ' in t, y


# ── API 2: pedir_datos, ajustes por proyecto y varios precios a la vez ────────

def test_ajustes_por_proyecto_sobreviven_a_exportar_e_importar(pid, admin, tmp_path):
    ctx = _ctx(pid, admin, tmp_path)
    assert dict(ctx.ajustes) == {}
    ctx.guardar_ajustes({'tasa': 18.0, 'nombre': 'ITBIS', 'si': True})
    assert dict(ctx.ajustes) == dict(ctx.presupuesto.ajustes) == {
        'tasa': 18.0, 'nombre': 'ITBIS', 'si': True}
    # Otro complemento no los ve.
    assert dict(contexto.presupuesto(pid, admin, 'otro').ajustes) == {}
    assert dict(contexto.presupuesto(pid, admin).ajustes) == {}
    conn = d.get_db()
    crudo = conn.execute("SELECT complementos_ajustes FROM proyectos WHERE id=?",
                         (pid,)).fetchone()[0]
    conn.close()
    from core import exporter
    from core.ingepresupuestos_db_importer import importar_proyecto_db_directo
    exporter.exportar_proyecto_db(pid, str(tmp_path / 'p.db'))
    nuevo = importar_proyecto_db_directo(str(tmp_path / 'p.db'), pid)
    conn = d.get_db()
    assert conn.execute("SELECT complementos_ajustes FROM proyectos WHERE id=?",
                        (nuevo,)).fetchone()[0] == crudo
    conn.close()
    with pytest.raises(api.ErrorComplemento):
        ctx.guardar_ajustes({'x': [1]})
    with pytest.raises(api.ErrorComplemento):
        ctx.guardar_ajustes({'x': 'a' * 20_000})
    with pytest.raises(api.ErrorComplemento):
        ctx.guardar_ajustes({'x': float('nan')})
    ctx.guardar_ajustes({})
    assert dict(ctx.ajustes) == {}


@pytest.mark.parametrize('crudo', ['', 'no json', '[1]', '{"de-prueba": 3}',
                                   '{"de-prueba": {"a": [1], "b": NaN}}', None])
def test_ajustes_ilegibles_de_un_db_ajeno(crudo):
    assert dict(contexto.ajustes_de({'complementos_ajustes': crudo},
                                    'de-prueba')) == {}


def test_fijar_y_simular_precios(pid, admin, tmp_path):
    ctx = _ctx(pid, admin, tmp_path)
    p = ctx.presupuesto
    ins = [i for x in p.hojas() for i in x.acu if not i.es_subpartida
           and not i.unidad.startswith('%') and i.precio > 0]
    a, b = ins[0], next(i for i in ins if i.recurso_id != ins[0].recurso_id)
    cambio = {a.recurso_id: a.precio + 1, b.recurso_id: b.precio + 2}
    sim = ctx.editar.simular_precios(cambio)
    igual = ctx.presupuesto
    assert (igual.costo_directo, igual.total) == (p.costo_directo, p.total)
    assert ctx.operaciones.pila.resumen() is None
    ctx.editar.fijar_precios(cambio)
    q = ctx.presupuesto
    assert (q.costo_directo, q.total) == (sim.costo_directo, sim.total)
    assert q.total > p.total
    conn = d.get_db()
    cat = conn.execute("SELECT precio FROM recursos WHERE id=?",
                       (a.recurso_id,)).fetchone()[0]
    conn.close()
    assert ctx.operaciones.pila.resumen()['herramienta'] == 'complemento:de-prueba'
    # Si uno falla, no queda ninguno.
    with pytest.raises(api.ErrorComplemento):
        ctx.editar.fijar_precios({a.recurso_id: 999, 10**9: 1})
    with pytest.raises(api.ErrorComplemento):
        ctx.editar.simular_precios({a.recurso_id: -1})
    assert ctx.presupuesto.total == q.total
    assert not ctx.operaciones.simular
    ctx.editar.fijar_precios({a.recurso_id: a.precio, b.recurso_id: b.precio})
    conn = d.get_db()
    assert conn.execute("SELECT precio FROM recursos WHERE id=?",
                        (a.recurso_id,)).fetchone()[0] == cat
    conn.close()


def test_pedir_datos_comprueba_y_el_formulario_devuelve_tipos():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from views.complementos_menu import DatosDialog
    campos = [api.Dato('n', 'Número', valor=12.5, maximo=20),
              api.Dato('e', 'Entero', 'entero', 3, 1, 9),
              api.Dato('t', 'Texto', 'texto', '<b>x</b>'),
              api.Dato('o', 'Opción', 'opcion', 'B', opciones=('A', 'B')),
              api.Dato('s', 'Sí', 'si_no', True)]
    dlg = DatosDialog('T', contexto.comprobar_datos(campos), 'texto')
    assert dlg.valores() == {'n': 12.5, 'e': 3, 't': '<b>x</b>', 'o': 'B', 's': True}
    dlg._w['n'].setValue(500)
    assert dlg.valores()['n'] == 20
    for malo in ([], [api.Dato('a', 'A', 'raro')], [api.Dato('a', 'A')] * 2, [3],
                 [api.Dato('a', 'A', 'opcion')],
                 [api.Dato('a', 'A', minimo=5, maximo=1)]):
        with pytest.raises(api.ErrorComplemento):
            contexto.comprobar_datos(malo)
