"""El catálogo del repositorio: solo copia archivos comprobados."""
import hashlib
import json

import pytest
from PySide6.QtTest import QTest

from core.complementos import cargador, catalogo, gestor, paquete
from core.complementos.gestor import ErrorGestor
from tests.test_complementos import admin, carpeta, codigo, limpio  # noqa: F401
from tests.test_complementos_gestor import _pulsar, _subir, fuente, pedidos  # noqa: F401
from views import complementos_dialog as cd


def _esperar(cond, ms=5000):
    while not cond() and ms > 0:
        QTest.qWait(20)
        ms -= 20
    return cond()


class Repo:
    """El catálogo, y los .zip como si estuvieran en la página de cada autor."""

    def __init__(self, base):
        self.base, self.pedidas, self.fuentes = base, [], base / 'fuentes'
        self.fuentes.mkdir()
        self.web, self.entradas = {}, {}

    def poner(self, id_='del-repo', version='1.0', py='def registrar(app): pass\n',
              **k):
        d = self.fuentes / id_
        if not d.exists():
            carpeta(self.fuentes, codigo(id=id_, nombre=id_, version=version),
                    {'complemento.py': py}, id_)
        _subir(d, version=version)
        z = paquete.empaquetar(d, self.base / f'{id_}-{version}.zip')
        p = paquete.leer_zip(z)
        url = f'https://autor.example/{z.name}'
        self.web[url] = z.read_bytes()
        self.entradas[id_] = {
            'ficha': {c: v for c, v in p.manifiesto.items()
                      if c in catalogo.CAMPOS_FICHA and v not in (None, '')},
            'repositorio': 'https://autor.example/r', 'descarga': url,
            'sha256': hashlib.sha256(self.web[url]).hexdigest(),
            'huella': p.huella, 'revisado': False, **k}
        self.escribir()
        return url

    def escribir(self):
        self.web[catalogo.URL + 'catalogo.json'] = json.dumps(
            {'formato': 1, 'complementos': list(self.entradas.values())}).encode()

    def pedir(self, url, tope):
        self.pedidas.append(url)
        if url not in self.web:
            raise ErrorGestor(url)
        return self.web[url]


LISTA = catalogo.URL + 'catalogo.json'


@pytest.fixture
def repo(tmp_path, monkeypatch, limpio, admin):  # noqa: F811
    r = Repo(tmp_path)
    monkeypatch.setattr(catalogo, '_pedir', r.pedir)
    return r


def _ids():
    return {i.id: i for _d, i in gestor.explorar()}


def _entrada(id_='del-repo'):
    return next(d for d, i in gestor.explorar() if i.id == id_)


def test_sincronizar_solo_trae_la_lista(repo, fuente, tmp_path):
    trampa = tmp_path / 'trampa'
    url = repo.poner(py=f"open({str(trampa)!r}, 'w')\ndef registrar(app): pass\n")
    assert 'del-repo' not in _ids() and catalogo.toca()
    assert catalogo.sincronizar() == 1 and repo.pedidas == [LISTA]
    i = _ids()['del-repo']
    assert i.estado == 'disponible' and not i.paquete.archivos and not catalogo.toca()
    assert catalogo.sincronizar() == 0
    # Descargar no instala ni ejecuta, y la segunda vez no pide nada.
    z = catalogo.descargar(_entrada())
    assert repo.pedidas[-1] == url and _ids()['del-repo'].paquete.archivos
    repo.pedidas.clear()
    assert catalogo.descargar(_entrada()) == z and not repo.pedidas
    assert gestor.instalados() == [] and not cargador.cargados() and not trampa.exists()


def test_la_version_mas_nueva_gana_y_a_igual_el_incluido(repo, fuente):
    repo.poner('uno-codigo', '1.0')
    catalogo.sincronizar()
    assert _entrada('uno-codigo') == fuente[0]
    repo.poner('uno-codigo', '1.1')
    assert catalogo.sincronizar() == 1
    assert _ids()['uno-codigo'].paquete.manifiesto['version'] == '1.1'
    catalogo.descargar(_entrada('uno-codigo'))
    repo.poner('uno-codigo', '1.2')
    catalogo.sincronizar()
    assert not list(catalogo.carpeta().glob('*.zip'))           # la vieja se borra
    repo.poner('uno-codigo', '0.9')
    catalogo.sincronizar()
    assert _ids()['uno-codigo'].paquete.manifiesto['version'] == '1.0'


def test_si_el_autor_cambia_el_archivo_no_entra(repo, fuente):
    url = repo.poner()
    catalogo.sincronizar()
    bueno = repo.web[url]
    repo.web[url] = bueno + b'x'
    with pytest.raises(ErrorGestor, match='huella'):
        catalogo.descargar(_entrada())
    assert not list(catalogo.carpeta().glob('*.zip'))
    # La copia local cambiada después tampoco vale.
    repo.web[url] = bueno
    z = catalogo.descargar(_entrada())
    z.write_bytes(bueno + b'x')
    assert not _ids()['del-repo'].paquete.archivos


@pytest.mark.parametrize('campo', ['nombre', 'autor', 'licencia', 'version', 'id'])
def test_la_ficha_tiene_que_ser_la_del_archivo(repo, fuente, campo):
    repo.poner()
    repo.entradas['del-repo']['ficha'][campo] = {'version': '9.9',
                                                 'id': 'otro-id'}.get(campo, 'Otro')
    repo.escribir()
    catalogo.sincronizar()
    with pytest.raises(ErrorGestor, match='no es lo que dice'):
        catalogo.descargar(_entrada('otro-id' if campo == 'id' else 'del-repo'))
    assert not list(catalogo.carpeta().glob('*.zip'))


def test_ni_la_huella_de_otro_contenido(repo, fuente):
    repo.poner(huella='0' * 64, revisado=True)
    catalogo.sincronizar()
    with pytest.raises(ErrorGestor, match='no es lo que dice'):
        catalogo.descargar(_entrada())


@pytest.mark.parametrize('malo', [
    {'ficha': None}, {'ficha': {'id': '../../x'}}, {'sha256': 'x'}, {'huella': 5},
    {'descarga': 'http://autor.example/x.zip'}, {'descarga': 'file:///etc/passwd'},
    {'descarga': 'https://a@b.example/x.zip'}, {'descarga': 'https://a.example/x y'}])
def test_entradas_malas_se_saltan(repo, fuente, malo):
    repo.poner('bueno-uno')
    repo.poner(**malo)
    assert catalogo.sincronizar() == 1
    assert 'del-repo' not in _ids() and 'bueno-uno' in _ids()


def test_de_otra_api_no_se_ofrece(repo, fuente):
    repo.poner()
    repo.entradas['del-repo']['ficha']['api_version'] = 99
    repo.escribir()
    catalogo.sincronizar()
    assert 'del-repo' not in _ids()


def test_sin_red_o_con_un_catalogo_roto_queda_lo_de_antes(repo, fuente):
    repo.poner()
    catalogo.sincronizar()
    for b in (b'{', b'[]', b'{"formato": 2, "complementos": []}', b'[' * 99999, b'\xff'):
        repo.web[LISTA] = b
        with pytest.raises(ErrorGestor):
            catalogo.sincronizar()
        assert 'del-repo' in _ids()


def test_en_la_store_no_hay_catalogo(repo, fuente, monkeypatch):
    repo.poner()
    catalogo.sincronizar()
    x = _entrada()
    monkeypatch.setattr(catalogo, 'disponible', lambda: False)
    assert 'del-repo' not in _ids()
    for fn in (catalogo.sincronizar, lambda: catalogo.descargar(x)):
        with pytest.raises(ErrorGestor):
            fn()


def _insignias(t):
    from PySide6.QtWidgets import QLabel
    return {w.text() for w in t.findChildren(QLabel) if w.objectName() == 'insignia'}


def test_desde_la_ventana(repo, fuente, pedidos):  # noqa: F811
    repo.poner('uno-codigo', '2.0', revisado=True)
    url = repo.poner('del-repo')
    g = cd.ComplementosDialog()
    _pulsar(g, 'uno-codigo', 'instalar')
    g.btn_sinc.click()
    assert not g.btn_sinc.isEnabled()
    assert _esperar(lambda: g.btn_sinc.isEnabled())
    assert '2' in g.lbl.text() and not cd._hilos and repo.pedidas == [LISTA]
    t = g.explorar.tarjetas
    assert 'COMUNIDAD' in _insignias(t['del-repo'])
    assert 'INCLUIDO' not in _insignias(t['del-repo'])
    assert 'REVISADO' in _insignias(t['uno-codigo'])
    assert 'INCLUIDO' in _insignias(t['dos-datos'])
    _pulsar(g, 'uno-codigo', 'actualizar')
    assert _esperar(lambda: gestor.uno('uno-codigo').paquete.manifiesto['version']
                    == '2.0')
    assert not gestor.uno('uno-codigo').activo and not pedidos
    # Dos clics: una descarga. Si falla, se dice y no queda nada.
    bueno = repo.web.pop(url)
    _pulsar(g, 'del-repo', 'instalar')
    assert _esperar(lambda: pedidos or not g._bajando)
    assert gestor.uno('del-repo') is None
    repo.web[url] = bueno
    repo.pedidas.clear()
    _pulsar(g, 'del-repo', 'instalar')
    _pulsar(g, 'del-repo', 'instalar')
    assert _esperar(lambda: gestor.uno('del-repo') is not None)
    assert gestor.uno('del-repo').estado == 'apagado' and repo.pedidas == [url]


def test_detalles_descarga_para_ensenar_los_archivos(repo, fuente, monkeypatch):
    repo.poner()
    catalogo.sincronizar()
    vistos = []

    class Falso:
        def __init__(self, info, _padre):
            vistos.append(sorted(info.paquete.archivos))

        def exec(self):
            pass
    monkeypatch.setattr(cd, 'DetallesDialog', Falso)
    g = cd.ComplementosDialog()
    _pulsar(g, 'del-repo', 'detalles')
    assert _esperar(lambda: vistos)
    assert vistos == [['complemento.json', 'complemento.py']]
    assert gestor.uno('del-repo') is None


def test_el_consentimiento_dice_si_se_reviso_ese_contenido(repo, fuente):
    from PySide6.QtWidgets import QLabel
    repo.poner(revisado=True)
    catalogo.sincronizar()
    i = gestor.instalar(catalogo.descargar(_entrada()))
    assert i.paquete.huella in catalogo.revisados()

    def texto(rev):
        w = cd.ConsentimientoDialog(i, None, rev)
        return " ".join(x.text() for x in w.findChildren(QLabel))
    assert 'no es una garantía' in texto(True) and 'no lo ha revisado' in texto(False)


def test_publicar_prepara_la_ficha(repo, fuente, tmp_path):
    import tomllib
    import urllib.parse
    repo.poner()
    p = paquete.leer_carpeta(repo.fuentes / 'del-repo')
    z = paquete.escribir_zip(p, tmp_path / 'x.zip')
    d = catalogo.publicacion(p, ' https://github.com/ana/mi.repo.git ', z)
    f = tomllib.loads(d['ficha'])
    assert f['cuenta'] == 'ana' and f['repositorio'] == 'https://github.com/ana/mi.repo'
    assert f['descarga'] == ('https://github.com/ana/mi.repo/releases/download/v1.0/'
                             'del-repo-1.0.zip')
    assert f['sha256'] == hashlib.sha256(z.read_bytes()).hexdigest()
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(d['pagina']).query)
    assert q == {'filename': ['del-repo.toml'], 'value': [d['ficha']]}
    for malo in ('', 'http://github.com/a/b', 'https://github.com/a',
                 'https://gitlab.com/a/b', 'https://github.com/a/b"\nx="'):
        with pytest.raises(ErrorGestor):
            catalogo.publicacion(p, malo, z)
    # Ya publicado: se edita la suya.
    catalogo.sincronizar()
    assert '/edit/main/fichas/del-repo.toml' in catalogo.publicacion(
        p, 'https://github.com/ana/r', z)['pagina']


def test_la_ventana_de_publicar(repo, fuente, tmp_path, monkeypatch):
    repo.poner()
    i = gestor.instalar(repo.fuentes / 'del-repo')
    g = cd.ComplementosDialog()

    def entradas(id_):
        return [a.text() for a in g.menu_de(gestor.uno(id_), g).actions()]
    assert 'Publicar…' in entradas('del-repo')
    gestor.instalar(fuente[0])                      # el incluido no se publica
    assert 'Publicar…' not in entradas('uno-codigo')
    w = cd.PublicarDialog(i, g)
    assert not w.btn_ficha.isEnabled()
    z = tmp_path / 'sale.zip'
    monkeypatch.setattr(cd.QFileDialog, 'getSaveFileName', lambda *a: (str(z), ''))
    abiertas = []
    monkeypatch.setattr(cd.QDesktopServices, 'openUrl',
                        lambda u: abiertas.append(u.toString()))
    w.btn_zip.click()
    assert paquete.leer_zip(z).huella == i.paquete.huella
    w.repo.setText('https://github.com/ana/r')
    w.btn_version.click()
    w.btn_ficha.click()
    assert abiertas[0].startswith('https://github.com/ana/r/releases/new?tag=v1.0')
    assert abiertas[1].startswith(catalogo.REPOSITORIO + '/new/main/fichas?')
    assert not repo.pedidas                         # el programa no sube nada


def test_cerrar_mientras_sincroniza(repo, fuente, monkeypatch):
    import threading
    paso = threading.Event()
    real = repo.pedir

    def lento(url, tope):
        paso.wait(5)
        return real(url, tope)
    monkeypatch.setattr(catalogo, '_pedir', lento)
    repo.poner()
    g = cd.ComplementosDialog()
    g.btn_sinc.click()
    g.reject()
    g.deleteLater()
    QTest.qWait(50)
    paso.set()
    cd.esperar_hilos()
    QTest.qWait(50)
    assert all(h.isFinished() for h in cd._hilos)
    g = cd.ComplementosDialog()
    g.btn_sinc.click()
    assert _esperar(lambda: g.btn_sinc.isEnabled(), 5000)
    assert 'del-repo' in g.explorar.tarjetas
