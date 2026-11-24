"""El catálogo del repositorio: solo copia archivos comprobados."""
import hashlib
import json

import pytest
from PySide6.QtTest import QTest

from core.complementos import cargador, catalogo, cli, gestor
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
    def __init__(self, base):
        self.base, self.pedidas, self.fuentes = base / 'repo', [], base / 'fuentes'
        self.fuentes.mkdir()

    def poner(self, id_='del-repo', version='1.0', py='def registrar(app): pass\n'):
        d = self.fuentes / id_
        if not d.exists():
            carpeta(self.fuentes, codigo(id=id_, nombre=id_, version=version),
                    {'complemento.py': py}, id_)
        _subir(d, version=version)
        catalogo.publicar(self.fuentes, self.base)
        return d

    def pedir(self, ruta, tope):
        self.pedidas.append(ruta)
        try:
            return (self.base / ruta).read_bytes()
        except OSError as e:
            raise ErrorGestor(str(e)) from None

    def cambiar(self, **k):
        f = self.base / 'catalogo.json'
        d = json.loads(f.read_text())
        d['complementos'][0].update(k)
        f.write_text(json.dumps(d))


@pytest.fixture
def repo(tmp_path, monkeypatch, limpio, admin):  # noqa: F811
    r = Repo(tmp_path)
    monkeypatch.setattr(catalogo, '_pedir', r.pedir)
    return r


def _ids():
    return {i.id: i for _d, i in gestor.explorar()}


def test_sincronizar_ofrece_y_no_instala_ni_ejecuta(repo, fuente, tmp_path):
    trampa = tmp_path / 'trampa'
    repo.poner(py=f"open({str(trampa)!r}, 'w')\ndef registrar(app): pass\n")
    assert 'del-repo' not in _ids() and catalogo.toca()
    assert catalogo.sincronizar() == {'nuevos': ['del-repo'], 'fallos': []}
    assert _ids()['del-repo'].estado == 'disponible' and not catalogo.toca()
    assert gestor.instalados() == [] and not cargador.cargados()
    assert not trampa.exists()
    # Otra vez: solo el catálogo.
    repo.pedidas.clear()
    assert catalogo.sincronizar()['nuevos'] == []
    assert repo.pedidas == ['catalogo.json']


def test_la_version_mas_nueva_gana_y_a_igual_el_incluido(repo, fuente):
    repo.poner('uno-codigo', '1.0')
    catalogo.sincronizar()
    d = {i.id: d for d, i in gestor.explorar()}
    assert d['uno-codigo'] == fuente[0]
    repo.poner('uno-codigo', '1.1')
    assert catalogo.sincronizar()['nuevos'] == ['uno-codigo']
    assert _ids()['uno-codigo'].paquete.manifiesto['version'] == '1.1'
    assert len(list(catalogo.carpeta().glob('*.zip'))) == 1     # la vieja se borra
    repo.poner('uno-codigo', '0.9')
    catalogo.sincronizar()
    assert _ids()['uno-codigo'].paquete.manifiesto['version'] == '1.0'


def test_un_archivo_que_no_es_el_del_catalogo_no_entra(repo, fuente):
    repo.poner()
    z = repo.base / 'zips' / 'del-repo-1.0.zip'
    bueno = z.read_bytes()
    z.write_bytes(bueno + b'x')
    r = catalogo.sincronizar()
    assert not r['nuevos'] and 'huella' in r['fallos'][0]
    assert 'del-repo' not in _ids() and not list(catalogo.carpeta().glob('*.zip'))
    # Con la huella bien, pero de otro complemento.
    z.write_bytes(bueno)
    repo.poner('otro-distinto')
    ajeno = (repo.base / 'zips' / 'otro-distinto-1.0.zip').read_bytes()
    z.write_bytes(ajeno)
    repo.cambiar(sha256=hashlib.sha256(ajeno).hexdigest())
    r = catalogo.sincronizar()
    assert r['nuevos'] == ['otro-distinto'] and 'no es lo que dice' in r['fallos'][0]
    # La copia local cambiada después deja de ofrecerse.
    f = next(catalogo.carpeta().glob('otro-distinto*.zip'))
    f.write_bytes(bueno)
    assert 'otro-distinto' not in _ids()
    assert catalogo.sincronizar()['nuevos'] == ['otro-distinto']


@pytest.mark.parametrize('malo', [
    {'id': '../../x'}, {'id': 5}, {'version': '../1'}, {'sha256': 'x'}, {'api': 99},
    {'api': True}, {'api': None}])
def test_entradas_malas_o_de_otra_api_se_saltan(repo, fuente, malo):
    repo.poner()
    repo.cambiar(**malo)
    assert catalogo.sincronizar() == {'nuevos': [], 'fallos': []}
    assert repo.pedidas == ['catalogo.json'] and 'del-repo' not in _ids()


def test_sin_red_o_con_un_catalogo_roto_queda_lo_de_antes(repo, fuente, monkeypatch):
    repo.poner()
    catalogo.sincronizar()
    for b in (b'{', b'[]', b'{"formato": 2, "complementos": []}', b'[' * 99999, b'\xff'):
        (repo.base / 'catalogo.json').write_bytes(b)
        with pytest.raises(ErrorGestor):
            catalogo.sincronizar()
        assert 'del-repo' in _ids()


def test_en_la_store_no_hay_catalogo(repo, fuente, monkeypatch):
    repo.poner()
    catalogo.sincronizar()
    monkeypatch.setattr(catalogo, 'disponible', lambda: False)
    assert 'del-repo' not in _ids()
    with pytest.raises(ErrorGestor):
        catalogo.sincronizar()


def test_publicar_no_admite_la_misma_version_con_otro_contenido(repo, capsys):
    d = repo.poner()
    (d / 'complemento.py').write_text('def registrar(app): return\n')
    with pytest.raises(ErrorGestor):
        catalogo.publicar(repo.fuentes, repo.base)
    assert cli.main(['--catalogo-complemento', str(repo.fuentes),
                     str(repo.base)]) == 1
    _subir(d, version='1.1')
    assert cli.main(['--catalogo-complemento', str(repo.fuentes),
                     str(repo.base)]) == 0
    assert not list((repo.base / 'zips').glob('.*'))


def test_desde_la_ventana(repo, fuente, pedidos):  # noqa: F811
    repo.poner('uno-codigo', '2.0')
    repo.poner('del-repo')
    g = cd.ComplementosDialog()
    _pulsar(g, 'uno-codigo', 'instalar')
    g.btn_sinc.click()
    assert not g.btn_sinc.isEnabled()
    assert _esperar(lambda: g.btn_sinc.isEnabled(), 5000)
    assert '2' in g.lbl.text() and not cd._hilos
    t = g.explorar.tarjetas
    # El del repositorio no lleva la insignia; el instalado, que es el incluido, sí.
    from PySide6.QtWidgets import QLabel

    def insignia(x):
        return any(w.text() == 'INCLUIDO' for w in x.findChildren(QLabel))
    assert not insignia(t['del-repo']) and insignia(t['dos-datos'])
    _pulsar(g, 'uno-codigo', 'actualizar')
    i = gestor.uno('uno-codigo')
    assert i.paquete.manifiesto['version'] == '2.0' and not i.activo and not pedidos
    _pulsar(g, 'del-repo', 'instalar')
    assert gestor.uno('del-repo').estado == 'apagado'


def test_cerrar_mientras_sincroniza(repo, fuente, monkeypatch):
    import threading
    paso = threading.Event()
    real = repo.pedir

    def lento(ruta, tope):
        paso.wait(5)
        return real(ruta, tope)
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
