"""El gestor visual de complementos: tarjetas, filtros e imágenes."""
import io
import json
import struct
import zlib
from pathlib import Path

import pytest
from PySide6.QtCore import QBuffer
from PySide6.QtGui import QImage, QImageReader
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QMessageBox

from core.complementos import cargador, esquema, gestor, paquete, plantilla
from utils import i18n
from views import complementos_dialog as cd

from tests.test_complementos import (  # noqa: F401 — fixtures
    admin, carpeta, codigo, limpio, man, zip_de)

RAIZ = Path(__file__).resolve().parent.parent


@pytest.fixture
def pedidos(monkeypatch):
    """Cada vez que se pide confianza: la huella enseñada. Se acepta."""
    out = []

    def exec_(s):
        out.append(s.info.paquete.huella)
        return QDialog.Accepted
    monkeypatch.setattr(cd.ConsentimientoDialog, 'exec', exec_)
    return out


@pytest.fixture
def fuente(tmp_path, monkeypatch):
    """«Explorar» con dos complementos: uno con código y otro de datos."""
    a = carpeta(tmp_path, codigo(id='uno-codigo', nombre='Uno Código', version='1.0',
                                 categorias=['reportes'], descripcion='Reporte ágil'),
                {'complemento.py': 'def registrar(app): pass\n'}, 'a')
    b = carpeta(tmp_path, man(id='dos-datos', nombre='Dos Datos', version='1.0',
                              categorias=['temas', 'paises']), nombre='b')
    monkeypatch.setattr(gestor, 'incluidos', lambda: [a, b])
    monkeypatch.setattr(cd.QMessageBox, 'exec', lambda s: QMessageBox.Yes)
    return a, b


def _subir(c, **k):
    f = c / 'complemento.json'
    f.write_text(json.dumps({**json.loads(f.read_text()), **k}))


def _png(w, h, reales=True):
    def trozo(t, d):
        return (struct.pack('>I', len(d)) + t + d
                + struct.pack('>I', zlib.crc32(t + d)))
    filas = (b'\0' + b'\x80' * (w * 3)) * h if reales else b''
    return (b'\x89PNG\r\n\x1a\n'
            + trozo(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + trozo(b'IDAT', zlib.compress(filas)) + trozo(b'IEND', b''))


def _qt(formato, w=40, h=20):
    im = QImage(w, h, QImage.Format_RGB32)
    im.fill(0x336699)
    b = QBuffer()
    b.open(QBuffer.WriteOnly)
    return bytes(b.data()) if im.save(b, formato) else b''


def _pulsar(dlg, id_, clave, pag=None):
    (pag or dlg._pagina()).tarjetas[id_].botones[clave].click()


def _menu(t, texto):
    return next(a for a in t.botones['mas'].menu().actions() if a.text() == texto)


# ── El ciclo entero desde las tarjetas ───────────────────────────────────────

def test_ciclo_desde_las_tarjetas(fuente, pedidos):
    g = cd.ComplementosDialog()
    p = g.explorar
    assert list(p.tarjetas['uno-codigo'].botones) == ['instalar', 'detalles']
    _pulsar(g, 'uno-codigo', 'instalar')
    i = gestor.uno('uno-codigo')
    assert i.estado == 'apagado' and not pedidos and not cargador.cargados()
    assert list(p.tarjetas['uno-codigo'].botones) == ['activar', 'detalles', 'mas']
    _pulsar(g, 'uno-codigo', 'activar')
    assert pedidos == [i.paquete.huella]
    assert gestor.uno('uno-codigo').activo and cargador.cargados()
    assert 'Activo' in p.tarjetas['uno-codigo'].lbl_estado.text()
    _pulsar(g, 'uno-codigo', 'desactivar')
    assert gestor.uno('uno-codigo').estado == 'apagado' and not cargador.cargados()
    g.tabs.setCurrentIndex(1)
    assert g.instalados.visibles == ['uno-codigo']
    _menu(g.instalados.tarjetas['uno-codigo'], 'Desinstalar').trigger()
    assert gestor.instalados() == [] and g.instalados.visibles == []
    assert not g.instalados.sin_nada.isHidden()
    g.tabs.setCurrentIndex(0)
    assert 'instalar' in p.tarjetas['uno-codigo'].botones


def test_decir_que_no_al_consentimiento_no_activa(fuente, monkeypatch):
    monkeypatch.setattr(cd.ConsentimientoDialog, 'exec', lambda s: QDialog.Rejected)
    g = cd.ComplementosDialog()
    for id_ in ('uno-codigo', 'dos-datos'):
        _pulsar(g, id_, 'instalar')
        _pulsar(g, id_, 'activar')
        assert not gestor.uno(id_).activo


@pytest.mark.parametrize('activo', [True, False])
def test_actualizar_vuelve_a_pedir_confianza(fuente, pedidos, activo):
    g = cd.ComplementosDialog()
    _pulsar(g, 'uno-codigo', 'instalar')
    if activo:
        _pulsar(g, 'uno-codigo', 'activar')
    vieja = gestor.uno('uno-codigo').paquete.huella
    pedidos.clear()
    _subir(fuente[0], version='1.0.0')                # la misma versión: nada
    assert 'actualizar' not in cd.ComplementosDialog().explorar.tarjetas[
        'uno-codigo'].botones
    _subir(fuente[0], version='1.10')
    g = cd.ComplementosDialog()
    t = g.explorar.tarjetas['uno-codigo']
    assert any('1.0 → 1.10' in x.text() for x in t.findChildren(QLabel))
    _pulsar(g, 'uno-codigo', 'actualizar')
    nueva = gestor.uno('uno-codigo')
    assert nueva.paquete.manifiesto['version'] == '1.10'
    assert nueva.paquete.huella != vieja
    assert pedidos == ([nueva.paquete.huella] if activo else [])
    assert nueva.activo is activo
    assert 'actualizar' not in g.explorar.tarjetas['uno-codigo'].botones


def test_actualizar_y_decir_que_no_lo_deja_apagado(fuente, pedidos, monkeypatch):
    g = cd.ComplementosDialog()
    _pulsar(g, 'uno-codigo', 'instalar')
    _pulsar(g, 'uno-codigo', 'activar')
    _subir(fuente[0], version='2.0')
    monkeypatch.setattr(cd.ConsentimientoDialog, 'exec', lambda s: QDialog.Rejected)
    g = cd.ComplementosDialog()
    _pulsar(g, 'uno-codigo', 'actualizar')
    assert gestor.uno('uno-codigo').estado == 'apagado' and not cargador.cargados()


def test_recargar_lo_que_cambio_vuelve_a_pedir_confianza(fuente, pedidos):
    g = cd.ComplementosDialog()
    _pulsar(g, 'uno-codigo', 'instalar')
    _pulsar(g, 'uno-codigo', 'activar')
    _menu(g.explorar.tarjetas['uno-codigo'], 'Recargar').trigger()
    assert len(pedidos) == 1 and gestor.uno('uno-codigo').activo    # igual: no pide
    (fuente[0] / 'complemento.py').write_text('def registrar(app): x = 1\n')
    _menu(g.explorar.tarjetas['uno-codigo'], 'Recargar').trigger()
    assert len(pedidos) == 2 and len(set(pedidos)) == 2


def test_cambiado_en_disco_se_dice_y_no_carga(fuente, pedidos):
    g = cd.ComplementosDialog()
    _pulsar(g, 'uno-codigo', 'instalar')
    _pulsar(g, 'uno-codigo', 'activar')
    (gestor.carpeta_de('uno-codigo') / 'complemento.py').write_text('#\n')
    g = cd.ComplementosDialog()
    t = g.explorar.tarjetas['uno-codigo']
    assert 'Cambió' in t.lbl_estado.text() and 'activar' in t.botones


def test_error_de_carga_en_la_tarjeta(fuente, pedidos, monkeypatch):
    dichos = []
    monkeypatch.setattr(cd, '_aviso', lambda p, t, *a: dichos.append(t))
    (fuente[0] / 'complemento.py').write_text(
        'def registrar(app): raise ValueError("roto")\n')
    g = cd.ComplementosDialog()
    _pulsar(g, 'uno-codigo', 'instalar')
    _pulsar(g, 'uno-codigo', 'activar')
    t = g.explorar.tarjetas['uno-codigo']
    assert 'roto' in dichos[0]
    assert any('roto' in x.text() for x in t.findChildren(QLabel, 'error'))


def test_zip_y_carpeta_salen_en_instalados_sin_insignia(fuente, tmp_path):
    g = cd.ComplementosDialog()
    g.instalar(zip_de(tmp_path, [('complemento.json',
                                  json.dumps(man(id='de-fuera', nombre='De fuera')))]))
    assert g._pagina() is g.instalados and g.instalados.visibles == ['de-fuera']
    # Uno ajeno con el id de un incluido no pasa por incluido.
    g.instalar(zip_de(tmp_path, [('complemento.json', json.dumps(
        man(id='dos-datos', nombre='Falso', version='9.0')))]))
    g.tabs.setCurrentIndex(1)
    g._mostrar()

    def insignias(id_):
        return [x.text() for x in g.instalados.tarjetas[id_].findChildren(
            QLabel, 'insignia')]
    assert 'INCLUIDO' not in insignias('dos-datos') + insignias('de-fuera')
    assert 'actualizar' not in g.instalados.tarjetas['dos-datos'].botones
    g.desinstalar('dos-datos')
    g.instalar_incluido('dos-datos')
    assert 'INCLUIDO' in insignias('dos-datos') and 'SOLO DATOS' in insignias('dos-datos')


def test_dañado_se_ve_y_se_puede_quitar(fuente):
    r = gestor.raiz() / 'instalados' / 'roto-x'
    r.mkdir(parents=True)
    (r / 'complemento.json').write_text('{')
    g = cd.ComplementosDialog()
    g.tabs.setCurrentIndex(1)
    t = g.instalados.tarjetas['roto-x']
    assert list(t.botones) == ['detalles', 'mas'] and 'Dañado' in t.lbl_estado.text()
    assert cd.DetallesDialog(g.infos['roto-x']).visor.lst.count() == 1
    _menu(t, 'Desinstalar').trigger()
    assert gestor.instalados() == []


# ── Permisos, modo seguro y textos ajenos ────────────────────────────────────

def test_sin_permiso_solo_detalles(fuente, pedidos, monkeypatch):
    gestor.instalar(fuente[1])
    monkeypatch.setattr(gestor, 'puede_gestionar', lambda: False)
    g = cd.ComplementosDialog()
    assert not g.btn_zip.isEnabled() and not g.btn_carpeta.isEnabled()
    for t in g.explorar.tarjetas.values():
        for k, b in t.botones.items():
            assert b.isEnabled() is (k in ('detalles', 'mas')), k
    m = g.explorar.tarjetas['dos-datos'].botones['mas'].menu()
    assert [a.text() for a in m.actions() if a.isEnabled() and a.text()] == [
        'Abrir carpeta']
    assert 'administrador' in g.lbl.text()
    dichos = []
    monkeypatch.setattr(cd, '_aviso', lambda p, t, *a: dichos.append(t))
    g.activar('dos-datos')                       # aunque se llame, el gestor no deja
    g.instalar_incluido('uno-codigo')
    assert len(dichos) == 2 and gestor.uno('uno-codigo') is None
    assert not gestor.uno('dos-datos').activo


def test_modo_seguro_no_carga(fuente, pedidos, monkeypatch):
    monkeypatch.setenv(gestor.VARIABLE_SEGURO, '1')
    g = cd.ComplementosDialog()
    assert 'Modo seguro' in g.lbl.text()
    _pulsar(g, 'uno-codigo', 'instalar')
    _pulsar(g, 'uno-codigo', 'activar')
    assert not cargador.cargados()


def test_los_textos_del_paquete_no_son_html(fuente):
    _subir(fuente[0], nombre='<b>N</b>', autor='<img src=x>', descripcion='<a>d</a>')
    g = cd.ComplementosDialog()
    from PySide6.QtCore import Qt
    for w in g.explorar.tarjetas['uno-codigo'].findChildren(QLabel):
        assert w.textFormat() == Qt.PlainText, w.text()


# ── Buscar, filtrar, ordenar ─────────────────────────────────────────────────

def test_buscar_filtrar_y_ordenar(fuente):
    g = cd.ComplementosDialog()
    p = g.explorar
    assert p.visibles == ['dos-datos', 'uno-codigo']
    assert p.contador.text() == '2 de 2'
    p.buscar.setText('CODIGO  agil')
    assert p.visibles == ['uno-codigo'] and p.contador.text() == '1 de 2'
    p.buscar.setText('zzz')
    assert p.visibles == [] and not p.sin_nada.isHidden() and p.sc.isHidden()
    p.buscar.setText('')
    p.categorias['paises'].click()
    assert p.visibles == ['dos-datos']
    p.categorias['metrados'].click()
    assert p.visibles == []
    p.categorias[''].click()
    g.instalar_incluido('uno-codigo')
    assert p.visibles == ['dos-datos', 'uno-codigo']
    p.orden.setCurrentIndex(1)
    assert p.visibles == ['uno-codigo', 'dos-datos']


def test_columnas_segun_el_ancho(fuente):
    g = cd.ComplementosDialog()
    g.show()
    for ancho, n in ((500, 1), (860, 2), (1240, 3)):
        g.resize(ancho, 600)
        QApplication.processEvents()
        assert g.explorar._columnas == n
        assert g.explorar.sc.horizontalScrollBar().maximum() == 0
    g.hide()


def test_sin_nada(monkeypatch):
    monkeypatch.setattr(gestor, 'incluidos', lambda: [])
    g = cd.ComplementosDialog()
    assert not g.explorar.sin_nada.isHidden() and g.explorar.contador.text() == '0 de 0'


def test_versiones():
    for a, b in (('1.10', '1.9'), ('2', '1.9.9.9'), ('1.0', '1.0-rc1'),
                 ('1.0-rc10', '1.0-rc2'), ('1.0.1', '1.0')):
        assert gestor.es_mas_nueva(a, b) and not gestor.es_mas_nueva(b, a), (a, b)
    assert not gestor.es_mas_nueva('1.0.0', '1')
    assert not gestor.es_mas_nueva('1.0+b', '1.0')


# ── Manifiesto: lo nuevo es opcional ─────────────────────────────────────────

def test_manifiesto_viejo_sigue_valiendo(tmp_path, monkeypatch):
    v = esquema.validar(man())
    assert (v['categorias'], v['traducciones'], v['imagen']) == ([], {}, '')
    c = carpeta(tmp_path, man(id='viejo-x'))
    monkeypatch.setattr(gestor, 'incluidos', lambda: [c])
    g = cd.ComplementosDialog()
    g.explorar.categorias['otros'].click()           # sin categoría → Otros
    assert g.explorar.visibles == ['viejo-x']
    assert cd.imagen_de(g.explorar._datos[0]['info'].paquete) is None
    w = g.explorar.tarjetas['viejo-x'].findChild(cd._Imagen)
    w.resize(350, 140)
    assert len({w.grab().toImage().pixel(x, 60) for x in range(350)}) > 1   # iniciales


@pytest.mark.parametrize('k, donde', [
    ({'categorias': ['raro']}, 'categorias[0]'),
    ({'categorias': ['temas', 'temas']}, 'categorias'),
    ({'categorias': ['temas', 'otros', 'paises', 'precios']}, 'categorias'),
    ({'categorias': 'temas'}, 'categorias'),
    ({'traducciones': {'fr': {}}}, 'traducciones'),
    ({'traducciones': {'en': {'autor': 'x'}}}, 'traducciones.en'),
    ({'traducciones': {'en': {'nombre': ''}}}, 'traducciones.en.nombre'),
    ({'imagen': 'x.svg'}, 'imagen'), ({'imagen': 3}, 'imagen')])
def test_esquema_rechaza_lo_nuevo_mal(k, donde):
    with pytest.raises(esquema.ErrorEsquema) as e:
        esquema.validar(man(**k))
    assert any(x.startswith(donde) for x in e.value.errores), e.value.errores


def test_traducido(tmp_path):
    i = gestor.instalar(carpeta(tmp_path, man(
        nombre='Base', descripcion='D', traducciones={
            'en': {'nombre': 'English'}, 'pt_BR': {'descripcion': 'PT'}})))
    assert (i.nombre, i.descripcion) == ('Base', 'D')
    i18n.set_idioma('en')
    assert (i.nombre, i.descripcion) == ('English', 'D')
    i18n.set_idioma('pt_BR')
    assert (i.nombre, i.descripcion) == ('Base', 'PT')


def test_la_plantilla_trae_categoria(tmp_path):
    assert paquete.leer(plantilla.crear('Nueva cosa', tmp_path)).manifiesto[
        'categorias'] == ['reportes']


# ── Imagen ───────────────────────────────────────────────────────────────────

def _con_imagen(tmp_path, b, nombre='i.png'):
    c = carpeta(tmp_path, man(imagen=nombre))
    (c / nombre).write_bytes(b)
    return paquete.leer(c)


def test_imagenes_que_valen(tmp_path):
    casos = [('i.png', _png(40, 20)), ('i.jpg', _qt('JPG'))]
    if b'webp' in [bytes(x) for x in QImageReader.supportedImageFormats()]:
        casos.append(('i.webp', _qt('WEBP')))
    assert len(casos) == 3
    for nombre, b in casos:
        img = cd.imagen_de(_con_imagen(tmp_path / nombre.replace('.', ''), b, nombre)
                           if (tmp_path / nombre.replace('.', '')).mkdir() is None
                           else None)
        assert (img.width(), img.height()) == (40, 20)


@pytest.mark.parametrize('b', [
    b'', b'no es una imagen', b'<svg xmlns="http://www.w3.org/2000/svg"/>',
    b'GIF89a' + b'\0' * 40,
    _png(30000, 30000, False),                       # bomba: 2,7 GB al abrirla
    _png(1601, 10), _png(0, 10, False), _png(10, 10) + b'\0' * 1_000_000,
    b'RIFF\0\0\0\0WEBPVP8X\0\0\0\0\0\0\0\0' + b'\xff' * 10,
    b'RIFF\0\0\0\0WEBPVP8 ', b'RIFF\0\0\0\0WEBP' + b'\0' * 40])
def test_imagen_mala_o_grande_se_rechaza_sin_abrirla(tmp_path, b, monkeypatch):
    monkeypatch.setattr(cd.QImageReader, 'read', lambda s: pytest.fail('la abrió'))
    with pytest.raises(paquete.ErrorPaquete):
        _con_imagen(tmp_path, b)
    assert cd._decodificar(b).isNull()


def test_imagen_rota_por_dentro_sale_con_iniciales(tmp_path):
    p = _con_imagen(tmp_path, _png(40, 20, False)[:60] + b'basura')
    assert cd.imagen_de(p) is None
    w = cd._Imagen(gestor.Info(p.id, p, False, 'disponible', '', ''))
    w.resize(350, 140)
    assert not w.grab().isNull()


def test_el_formato_se_fija_por_contenido(tmp_path):
    """Un .png que por dentro es SVG o GIF no llega a ningún otro decodificador."""
    with pytest.raises(paquete.ErrorPaquete):
        _con_imagen(tmp_path, _qt('BMP'))
    b = b'\x89PNG\r\n\x1a\n' + b'\0' * 4 + b'IHDR' + struct.pack('>II', 9, 9) + b'<svg/>'
    assert cd._decodificar(b).isNull()


def test_falta_la_imagen(tmp_path):
    with pytest.raises(paquete.ErrorPaquete, match='falta el archivo'):
        paquete.leer(carpeta(tmp_path, man(imagen='no.png')))


# ── Los incluidos ────────────────────────────────────────────────────────────

@pytest.mark.parametrize('d_', sorted((RAIZ / 'complementos').iterdir()),
                         ids=lambda x: x.name)
def test_incluidos_con_categoria_traducciones_e_imagen(d_):
    p = paquete.leer(d_)
    m = p.manifiesto
    assert m['categorias'] and set(m['traducciones']) == {'en', 'pt_BR'}
    assert all(set(t) == {'nombre', 'descripcion'} for t in m['traducciones'].values())
    assert len(p.archivos[m['imagen']]) < 150_000
    assert not cd.imagen_de(p).isNull()


def test_solo_se_decodifica_lo_que_se_pinta(fuente, monkeypatch):
    monkeypatch.setattr(cd, '_IMAGENES', {})
    (fuente[0] / 'i.png').write_bytes(_png(40, 20))
    _subir(fuente[0], imagen='i.png')
    g = cd.ComplementosDialog()
    assert not cd._IMAGENES
    g.show()
    QApplication.processEvents()
    assert len(cd._IMAGENES) == 1
    g.hide()
