# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Tests del catálogo editable de Índices Unificados de Precios (INEI).

Corre con:  venv/bin/python3 tests/test_indices_inei.py

Un usuario pidió por correo poder «modificar, añadir o actualizar la relación
de los índices unificados», porque los que trae la app no le alcanzan para su
fórmula polinómica. Al mirarlo aparecieron tres cosas:

* la lista no tenía 80 entradas sino **72** (la numeración oficial va del 01 al
  80 con huecos), y estaba escrita DOS veces —en el módulo y en la vista;
* `indices_inei_valores` no tiene clave foránea, así que los valores de un
  código ausente del catálogo **sí se guardaban** pero la lista, que sale de
  `indices_inei`, no los mostraba nunca: invisibles e inservibles;
* la semilla corría en cada arranque con INSERT OR IGNORE, o sea que un índice
  borrado por el usuario **resucitaba** al reiniciar.

Usa una COPIA temporal de presupuestos_seed.db, nunca la BD activa.
"""
import os
import shutil
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import core.config as cfg
import core.database as d

SEED = os.path.join(os.path.dirname(__file__), '..', 'presupuestos_seed.db')
_tmpdb = None


def _preparar():
    global _tmpdb
    if _tmpdb is None:
        fd, _tmpdb = tempfile.mkstemp(suffix='_inei.db')
        os.close(fd)
        shutil.copy(SEED, _tmpdb)
        d.DB_PATH = _tmpdb
        cfg.DB_PATH = _tmpdb
        d.init_db()
    import core.indices_inei as I
    I.asegurar_seed()
    return I


def _crudo(sql, params=()):
    c = sqlite3.connect(_tmpdb)
    r = c.execute(sql, params).fetchall()
    c.close()
    return r


# ── La lista que se enviaba ──────────────────────────────────────────────────
def test_las_dos_series_conviven_con_sus_propias_areas():
    """La RJ 016-2026-INEI cambió la base: 6 áreas y 68 índices pasan a 13 y 77.

    Las dos series tienen que coexistir; una fórmula de 2024 se lee con la
    tabla vieja y una de 2026 con la nueva.
    """
    I = _preparar()
    assert len(I.catalogo(serie=I.SERIE_2025)) >= 77
    assert len(I.listar_areas(serie=I.SERIE_2025)) == 13
    assert len(I.listar_areas(serie=I.SERIE_1992)) == 6
    # la serie histórica conserva los códigos descontinuados que la nueva no trae
    viejos = dict(I.catalogo(serie=I.SERIE_1992))
    assert '22' in viejos, "se perdió el Cemento Portland Tipo II histórico"


def test_el_mismo_codigo_significa_cosas_distintas_en_cada_serie():
    """El 21 era «Cemento Portland Tipo I» y ahora absorbió al 22 y al 23."""
    I = _preparar()
    n92 = dict(I.catalogo(serie=I.SERIE_1992)).get('21', '')
    n25 = dict(I.catalogo(serie=I.SERIE_2025)).get('21', '')
    assert n92 and n25 and n92 != n25, (n92, n25)


def test_la_serie_sale_de_la_fecha():
    """Diciembre de 2025 es el corte: antes 1992, desde ahí 2025."""
    I = _preparar()
    assert I.serie_de(2025, 11) == I.SERIE_1992
    assert I.serie_de(2025, 12) == I.SERIE_2025
    assert I.serie_de(2026, 3) == I.SERIE_2025


def test_el_diccionario_oficial_viene_empaquetado():
    """Anexo 2 de la resolución: ~1930 elementos con su índice unificado."""
    I = _preparar()
    d = I.diccionario_oficial()
    assert len(d) > 1500, f"solo {len(d)} entradas"
    assert set(d.values()) <= set(dict(I.catalogo(serie=I.SERIE_2025))), \
        "el diccionario apunta a índices que no están en la relación"


def test_el_catalogo_tiene_un_solo_dueno():
    """La vista de insumos ya no lleva su propia copia de la lista."""
    _preparar()
    import inspect
    import views.recursos_view as RV
    assert not hasattr(RV, 'INEI_CATALOG'), \
        "volvió la lista hardcodeada en recursos_view"
    src = inspect.getsource(RV.catalogo_inei)
    assert 'core.indices_inei' in src, "catalogo_inei dejó de leer la tabla"


# ── Alta, edición y baja ─────────────────────────────────────────────────────
def test_el_codigo_se_normaliza_a_la_forma_del_inei():
    """'7' es el 07: dos dígitos, que es como lo referencian los insumos."""
    I = _preparar()
    assert I._norm_codigo('7') == '07'
    assert I._norm_codigo(25) == '25'
    assert I._norm_codigo(' 8 ') == '08'
    for malo in ('', 'ab', '100', None):
        try:
            I._norm_codigo(malo)
        except ValueError:
            continue
        raise AssertionError(f"aceptó un código inválido: {malo!r}")


def test_crear_acepta_un_codigo_sin_cero_a_la_izquierda():
    """25 es uno de los huecos de la numeración oficial, así que está libre."""
    I = _preparar()
    assert I.crear_indice(25, 'Hueco de la numeración') == '25'
    assert dict(I.catalogo())['25'] == 'Hueco de la numeración'


def test_crear_editar_eliminar():
    """CRUD sobre la serie histórica, donde el 90-99 está libre entero."""
    I = _preparar()
    S = I.SERIE_1992
    I.crear_indice('90', 'Índice de prueba', serie=S)
    assert ('90', 'Índice de prueba') in I.catalogo(serie=S)
    I.actualizar_indice('90', nombre='Renombrado', serie=S)
    assert ('90', 'Renombrado') in I.catalogo(serie=S)
    I.eliminar_indice('90', serie=S)
    assert '90' not in dict(I.catalogo(serie=S))


def test_no_se_puede_duplicar_un_codigo():
    I = _preparar()
    S = I.SERIE_1992
    I.crear_indice('91', 'Uno', serie=S)
    try:
        I.crear_indice('91', 'Otro', serie=S)
    except ValueError:
        return
    raise AssertionError("dejó crear dos veces el mismo código")


def test_nombre_vacio_se_rechaza():
    I = _preparar()
    S = I.SERIE_1992
    for fn in (lambda: I.crear_indice('92', '   ', serie=S),
               lambda: I.actualizar_indice('01', nombre='', serie=S)):
        try:
            fn()
        except ValueError:
            continue
        raise AssertionError("aceptó un nombre vacío")


def test_desactivar_lo_saca_del_catalogo_pero_no_de_la_tabla():
    I = _preparar()
    S = I.SERIE_1992
    I.crear_indice('93', 'Desactivable', serie=S)
    I.actualizar_indice('93', activo=False, serie=S)
    assert '93' not in dict(I.catalogo(serie=S))
    assert '93' in dict(I.catalogo(incluir_inactivos=True, serie=S))


# ── La resurrección ──────────────────────────────────────────────────────────
def test_la_semilla_no_resucita_un_indice_borrado():
    """El bug de fondo: sin esto, borrar no servía de nada."""
    I = _preparar()
    I.eliminar_indice('01')
    I.asegurar_seed()          # como si la app reiniciara
    I.asegurar_seed()
    assert '01' not in dict(I.catalogo()), "el índice borrado volvió"


def test_borrar_antes_de_que_corra_la_semilla_igual_manda():
    """El borrado tiene que asentarse aunque la semilla no haya corrido nunca.

    Bug real: `asegurar_seed` marca `seed_inei_ver` recién cuando siembra. Si
    el usuario borraba un índice en una BD donde todavía no había corrido, la
    PRIMERA lectura posterior ejecutaba la semilla y devolvía la fila — el
    borrado se deshacía solo. Por eso el alta, la edición y la baja llaman a
    `asegurar_seed` antes de escribir.
    """
    I = _preparar()
    conn = d.get_db()
    conn.execute("DELETE FROM configuracion WHERE clave='seed_inei_ver'")
    conn.commit()
    conn.close()
    I.eliminar_indice('44')
    assert '44' not in dict(I.catalogo()), "la semilla resucitó el borrado"


def test_la_semilla_respeta_un_renombre():
    I = _preparar()
    I.actualizar_indice('02', nombre='Acero liso (mi nombre)')
    I.asegurar_seed()
    assert dict(I.catalogo())['02'] == 'Acero liso (mi nombre)'


# ── Lo que hacía inservible la importación oficial ───────────────────────────
def test_guardar_valores_da_de_alta_el_codigo_que_no_estaba():
    """El archivo del INEI trae códigos nuevos; antes entraban invisibles."""
    I = _preparar()
    assert '97' not in dict(I.catalogo(serie=I.SERIE_1992))
    ok, err = I.guardar_valores([
        {'codigo': '97', 'anio': 2020, 'mes': 3, 'area': '01', 'valor': 123.45,
         'nombre': 'Índice nuevo del INEI'},
    ])
    assert ok == 1 and err == 0, (ok, err)
    cat = dict(I.catalogo(serie=I.SERIE_1992))
    assert '97' in cat, "el valor entró pero el índice siguió invisible"
    assert cat['97'] == 'Índice nuevo del INEI'
    assert I.obtener_valor('97', 2020, 3) == 123.45


def test_el_alta_automatica_usa_nombre_provisional_si_no_viene():
    I = _preparar()
    I.guardar_valores([
        {'codigo': '94', 'anio': 2020, 'mes': 4, 'area': '01', 'valor': 100.0},
    ])
    assert dict(I.catalogo(serie=I.SERIE_1992))['94'] == 'Índice 94'


# ── Huérfanos: códigos usados que el catálogo no define ──────────────────────
def test_codigos_huerfanos_encuentra_los_que_el_catalogo_no_define():
    """Un insumo que apunta a un código inexistente tiene que salir a la luz.

    Pasa de verdad: la biblioteca semilla trae insumos con códigos que el
    catálogo no definía, y con el cambio de base pasa más —el 22 y el 23
    existen en la serie 1992 y desaparecieron en la de 2025.
    """
    I = _preparar()
    rid = _crudo("SELECT id FROM recursos LIMIT 1")[0][0]
    conn = d.get_db()
    conn.execute("UPDATE recursos SET indice_inei='73' WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    assert '73' not in dict(I.catalogo(serie=I.SERIE_2025)), \
        "el 73 dejó de ser un hueco de la numeración"
    codigos = {h['codigo'] for h in I.codigos_huerfanos(serie=I.SERIE_2025)}
    assert '73' in codigos, f"no detectó el huérfano: {sorted(codigos)}"


def test_los_huerfanos_distinguen_descontinuado_de_desconocido():
    """La respuesta correcta es distinta según de dónde venga el código.

    El 22 y el 23 —«Cemento Portland Tipo II» y «Tipo V»— existían en la base
    1992 y el INEI los retiró al absorberlos el 21: son DESCONTINUADOS. El 99,
    que en la biblioteca semilla son 319 subcontratos, no figura en ninguna
    relación oficial: es DESCONOCIDO.

    Importa porque darlos de alta crearía índices que el INEI no publica y que
    nunca tendrán valores; lo que corresponde es reasignar sus insumos.
    """
    I = _preparar()
    por_codigo = {h['codigo']: h for h in I.codigos_huerfanos()}
    if '22' in por_codigo:
        h = por_codigo['22']
        assert h['descontinuado'], h
        assert 'cemento' in h['nombre_anterior'].lower(), h['nombre_anterior']
        assert h['serie_anterior'] == I.SERIE_1992
    if '99' in por_codigo:
        h = por_codigo['99']
        assert not h['descontinuado'], h
        assert h['nombre_anterior'] == ''


def test_codigos_huerfanos_ignora_el_centinela_00():
    """'00' no es un índice del INEI: lo usa parte_diario para lo sin clasificar."""
    I = _preparar()
    assert '00' not in {h['codigo'] for h in I.codigos_huerfanos()}


def test_dar_de_alta_los_huerfanos_los_saca_de_la_lista():
    I = _preparar()
    pendientes = [h['codigo'] for h in I.codigos_huerfanos()]
    assert pendientes, "el fixture ya no tiene huérfanos que probar"
    I.asegurar_codigos(pendientes)
    assert I.codigos_huerfanos() == []


# ── Borrar no debe arrastrar los insumos ─────────────────────────────────────
def test_eliminar_un_indice_no_toca_los_insumos():
    """Se enumeran en el aviso, pero conservan su código: reasignar es del usuario."""
    I = _preparar()
    S = I.SERIE_1992
    I.crear_indice('95', 'Con insumos', serie=S)
    conn = d.get_db()
    conn.execute("UPDATE recursos SET indice_inei='95' "
                 "WHERE id IN (SELECT id FROM recursos LIMIT 3)")
    conn.commit()
    conn.close()
    usos = I.contar_usos('95', serie=S)
    assert usos['recursos'] == 3, usos
    I.eliminar_indice('95', serie=S)
    quedan = _crudo("SELECT COUNT(*) FROM recursos WHERE indice_inei='95'")[0][0]
    assert quedan == 3, "el borrado del catálogo se llevó los insumos"


def test_eliminar_puede_llevarse_el_historico_si_se_pide():
    I = _preparar()
    S = I.SERIE_1992
    I.crear_indice('96', 'Con histórico', serie=S)
    I.guardar_valor('96', 2020, 1, 50.0)
    assert I.contar_usos('96', serie=S)['valores'] == 1
    I.eliminar_indice('96', borrar_valores=True, serie=S)
    assert _crudo("SELECT COUNT(*) FROM indices_inei_valores "
                  "WHERE codigo='96'")[0][0] == 0


# ── La vista, consistente con el resto del programa ──────────────────────────
def test_la_vista_cabe_en_una_pantalla_de_portatil():
    """La barra metía título, dos selectores y OCHO botones en una sola fila:
    pedía 1872 px y en 1366 el combo de la base salía cortado. Ahora las
    importaciones van en un menú, como en el Catálogo de Insumos."""
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    _preparar()
    from views.indices_inei_view import IndicesINEIView

    v = IndicesINEIView()
    v.resize(1366, 768)
    v.show()
    app.processEvents()
    # Sin el QSS global los paddings por defecto son mayores, así que el
    # umbral es holgado: lo que se fija es que quepa en un portátil de 1366,
    # no el píxel exacto. Con el tema aplicado son ~900.
    ancho = v.minimumSizeHint().width()
    assert ancho <= 1200, f"la vista pide {ancho} px de ancho mínimo"

    # Las cinco importaciones, en un solo menú.
    acciones = [a.text() for a in v.btn_import.menu().actions() if a.text()]
    assert len(acciones) == 5, acciones

    # Y la lista no saca barra horizontal por los nombres largos.
    assert v.lst.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff


def test_la_vista_sigue_funcionando_tras_el_rediseno():
    """Buscar, cambiar de base y seleccionar un índice."""
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    I = _preparar()
    from views.indices_inei_view import IndicesINEIView

    v = IndicesINEIView()
    v.resize(1200, 700)
    v.show()
    app.processEvents()
    n_2025 = v.lst.count()
    assert n_2025 > 0

    v.inp_q.setText("cemento")
    v._refrescar_lista()
    app.processEvents()
    assert 0 < v.lst.count() < n_2025, v.lst.count()
    v.inp_q.setText("")
    v._refrescar_lista()
    app.processEvents()

    # Cambiar de base recarga catálogo y áreas.
    v.cmb_serie.setCurrentIndex(1)
    app.processEvents()
    assert v._serie_actual == I.SERIE_1992
    assert v.cmb_area.count() == 6
    v.cmb_serie.setCurrentIndex(0)
    app.processEvents()
    assert v.cmb_area.count() == 13

    # Seleccionar un índice carga su matriz.
    for i in range(v.lst.count()):
        if v.lst.item(i).data(Qt.UserRole) == '21':
            v.lst.setCurrentRow(i)
            break
    app.processEvents()
    assert '21' in v.lbl_titulo_matriz.text()


def test_el_editor_de_celda_ocupa_la_celda_entera():
    """Reportado probando: «al editar o agregar un índice a mano, el texto se
    entrecorta y solo se ve cuando termino».

    El `padding: 4px 6px` de la celda recorta también el rectángulo del EDITOR:
    en una celda de 57×27 salía uno de 45×19, y «1234.56» —47 px— no cabía.
    """
    import os as _os
    _os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication, QLineEdit
    from PySide6.QtCore import Qt
    app = QApplication.instance() or QApplication([])
    _preparar()
    from views.indices_inei_view import IndicesINEIView

    v = IndicesINEIView()
    v.resize(1200, 700)
    v.show()
    app.processEvents()
    for i in range(v.lst.count()):
        if v.lst.item(i).data(Qt.UserRole) == '21':
            v.lst.setCurrentRow(i)
            break
    app.processEvents()
    if v.tbl.rowCount() == 0:
        v._agregar_anio()
        app.processEvents()
    assert v.tbl.rowCount() > 0, "no hay fila de año para editar"

    it = v.tbl.item(0, 0)
    celda = v.tbl.visualItemRect(it)
    v.tbl.editItem(it)
    app.processEvents()
    editores = v.tbl.viewport().findChildren(QLineEdit)
    assert editores, "no se creó editor"
    e = editores[0]
    assert e.width() >= celda.width() - 1, (e.width(), celda.width())
    assert e.height() >= celda.height() - 1, (e.height(), celda.height())

    # Y un valor típico cabe.
    fm = e.fontMetrics()
    assert e.contentsRect().width() >= fm.horizontalAdvance('99999.99')


# ── Sincronización con las dos fuentes del INEI ──────────────────────────────
# El Excel acumulado del INEI se actualiza cuando ellos quieren (en agosto de
# 2026 seguía con datos hasta marzo), mientras que las resoluciones jefaturales
# mensuales sí salen puntuales y gob.pe las publica en PDF. Sincronizar solo
# con el Excel dejaba la app clavada cuatro meses atrás.

def test_gobpe_reconoce_el_mes_de_la_resolucion():
    """El título de la resolución es lo único que dice de qué mes es."""
    from core.indices_inei import _mes_del_titulo
    casos = [
        ("ÍNDICES MES DE JULIO 2026", (2026, 7)),
        ("Índices Unificados - Mes de Enero 2026", (2026, 1)),
        ("ÍNDICES MES DE DICIEMBRE 2025", (2025, 12)),
        ("Índices mes de setiembre 2026", (2026, 9)),
        ("Factor de liquidación F", None),
        ("Mano de obra 2026", None),
    ]
    for titulo, esperado in casos:
        assert _mes_del_titulo(titulo) == esperado, titulo


def test_sin_internet_la_sincronizacion_avisa_en_vez_de_reventar():
    """Las dos fuentes son de red: caídas, el usuario debe ver un aviso."""
    _preparar()
    import urllib.request
    from PySide6.QtWidgets import QApplication, QMessageBox
    from views.indices_inei_view import IndicesINEIView
    import core.indices_inei as ii

    QApplication.instance() or QApplication([])
    real_open, real_warn = urllib.request.urlopen, QMessageBox.warning
    avisos = []

    def caido(*a, **k):
        raise OSError("sin red")

    urllib.request.urlopen = caido
    QMessageBox.warning = staticmethod(
        lambda p, t, m, *a, **k: avisos.append(m) or QMessageBox.Ok)
    try:
        # La descarga de una resolución nunca lanza: informa el motivo.
        res = ii.descargar_resolucion_gobpe("https://x/y.pdf")
        assert res['ok'] is False and 'sin red' in res['msg'], res

        v = IndicesINEIView()
        v._sincronizar_inei()          # no debe propagar la excepción
        assert avisos, "no avisó al usuario"
        assert v.btn_auto.isEnabled(), "el botón quedó bloqueado"
        assert v.btn_auto.text() == "Sincronizar con INEI"
    finally:
        urllib.request.urlopen = real_open
        QMessageBox.warning = real_warn


def test_los_huecos_de_meses_se_detectan():
    """Si falta el mes de la valorización no hay K que calcular: hay que avisar."""
    _preparar()
    from PySide6.QtWidgets import QApplication
    from views.indices_inei_view import IndicesINEIView
    QApplication.instance() or QApplication([])
    v = IndicesINEIView()
    v._serie_actual = '__vacia__'          # serie sin nada en la BD
    filas = [{'anio': 2026, 'mes': m, 'area': '01', 'codigo': '01',
              'valor': 100.0} for m in (1, 2, 3, 7)]
    assert v._meses_faltantes(filas) == [(2026, 4), (2026, 5), (2026, 6)]
    # Sin huecos, nada que avisar.
    seguidos = [dict(f, mes=m) for m, f in zip((1, 2, 3), filas)]
    assert v._meses_faltantes(seguidos) == []
    # Un solo mes tampoco tiene huecos posibles.
    assert v._meses_faltantes(filas[:1]) == []


def test_el_rango_resume_los_periodos_importados():
    """El diálogo dice qué trae cada fuente, para poder contrastarlo."""
    from views.indices_inei_view import IndicesINEIView
    r = IndicesINEIView._rango_de
    assert r([{'anio': 2026, 'mes': 7}]) == "2026-07"
    assert r([{'anio': 2026, 'mes': 1}, {'anio': 2026, 'mes': 3}]) == \
        "2026-01 a 2026-03 (2 meses)"
    assert r([]) == "sin períodos"


# ── El histórico viaja con el programa ───────────────────────────────────────
# Los índices cambian todos los meses y un release sale cada tanto, así que sin
# esto una instalación nueva arrancaba sin la base vigente: el Excel del INEI
# lleva meses congelado y gob.pe solo deja el PDF del mes en curso.

def test_set_es_septiembre():
    """El INEI rotula sus hojas «Set-2013»: sin esa grafía se perdía el mes."""
    from core.indices_inei import _parse_mes, _parse_hoja_periodo
    assert _parse_mes('Set') == 9
    assert _parse_mes('set') == 9
    assert _parse_mes('Setiembre') == 9
    assert _parse_mes('Sep') == 9
    assert _parse_hoja_periodo('Set-2013') == (2013, 9)
    assert _parse_hoja_periodo('Set_2025') == (2025, 9)


def test_una_instalacion_nueva_trae_las_dos_bases():
    """Sin datos no hay reajuste que calcular: tienen que venir en el paquete."""
    _preparar()
    import core.database as d
    conn = d.get_db()
    try:
        for serie, desde, areas in (('1992', (2013, 1), 6), ('2025', (2026, 1), 13)):
            n, na = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT area) FROM indices_inei_valores "
                "WHERE serie=?", (serie,)).fetchone()
            assert n > 3000, f"serie {serie}: solo {n} valores"
            assert na == areas, f"serie {serie}: {na} áreas, se esperaban {areas}"
            hay = conn.execute(
                "SELECT 1 FROM indices_inei_valores WHERE serie=? AND anio=? "
                "AND mes=? LIMIT 1", (serie, *desde)).fetchone()
            assert hay, f"serie {serie}: falta {desde}"
        # La base 1992 no puede tener un solo mes vacío entre 2013 y 2025:
        # con un hueco, una valorización de ese mes se queda sin K.
        faltan = [(y, m) for y in range(2013, 2026) for m in range(1, 13)
                  if not conn.execute(
                      "SELECT 1 FROM indices_inei_valores WHERE serie='1992' "
                      "AND anio=? AND mes=? LIMIT 1", (y, m)).fetchone()]
        assert not faltan, f"meses sin datos: {faltan}"
    finally:
        conn.close()


def test_la_siembra_no_pisa_lo_que_el_usuario_ya_tiene():
    """INSERT OR IGNORE, nunca REPLACE: una corrección a mano manda."""
    _preparar()
    import core.database as d
    import core.indices_inei as I
    conn = d.get_db()
    try:
        conn.execute("UPDATE indices_inei_valores SET valor=1.23 WHERE serie='1992' "
                     "AND anio=2020 AND mes=6 AND codigo='01' AND area='01'")
        conn.execute("DELETE FROM configuracion WHERE clave='seed_inei_valores_1992'")
        conn.commit()
        I.asegurar_seed(conn, '1992')
        v = conn.execute(
            "SELECT valor FROM indices_inei_valores WHERE serie='1992' AND anio=2020 "
            "AND mes=6 AND codigo='01' AND area='01'").fetchone()['valor']
        assert v == 1.23, f"la siembra pisó el valor del usuario: {v}"
    finally:
        conn.close()


def test_la_correccion_de_2018_viaja_aplicada():
    """El INEI rectificó 6 índices de ene-mar 2018 en una hoja aparte que sus
    propias hojas mensuales nunca incorporaron. Corresponde al área 02."""
    _preparar()
    import core.database as d
    conn = d.get_db()
    try:
        for codigo, esperado in (('43', 662.98), ('17', 665.25), ('04', 935.68)):
            v = conn.execute(
                "SELECT valor FROM indices_inei_valores WHERE serie='1992' "
                "AND anio=2018 AND mes=1 AND area='02' AND codigo=?",
                (codigo,)).fetchone()
            assert v and abs(v['valor'] - esperado) < 0.005, \
                f"código {codigo}: {v['valor'] if v else None}, se esperaba {esperado}"
    finally:
        conn.close()


def test_el_historico_empaquetado_esta_donde_lo_busca_el_spec():
    """Si el recurso no viaja, la app degrada en silencio a no tener nada."""
    import gzip
    import json
    from pathlib import Path
    from core.config import BASE_DIR
    ruta = Path(BASE_DIR) / "resources" / "indices_inei_valores.json.gz"
    assert ruta.exists(), f"no está {ruta}"
    with gzip.open(ruta, 'rt', encoding='utf-8') as f:
        doc = json.load(f)
    assert doc.get('_fuente') and doc.get('generado')
    assert set(doc['series']) == {'1992', '2025'}
    assert len(doc['series']['1992']['areas']) == 6
    assert len(doc['series']['2025']['areas']) == 13


# ── Las cuatro fuentes y el refresco de lo que el seed viejo dejó mal ────────

def test_el_paquete_cubre_2026_sin_huecos():
    """Abril, mayo y junio no salen del INEI ni de gob.pe: van de El Peruano."""
    _preparar()
    import core.database as d
    conn = d.get_db()
    try:
        faltan = [m for m in range(1, 8) if not conn.execute(
            "SELECT 1 FROM indices_inei_valores WHERE serie='2025' AND anio=2026 "
            "AND mes=? LIMIT 1", (m,)).fetchone()]
        assert not faltan, f"meses de 2026 sin datos: {faltan}"
        n = conn.execute("SELECT COUNT(DISTINCT area) FROM indices_inei_valores "
                         "WHERE serie='2025' AND anio=2026 AND mes=6").fetchone()[0]
        assert n == 13, f"junio trae {n} áreas, se esperaban 13"
    finally:
        conn.close()


def test_el_refresco_corrige_la_basura_del_seed_viejo():
    """Hasta la 3.0.4 el seed traía marcadores (100, 500, 1000) que la siembra,
    al ser INSERT OR IGNORE, no podía corregir nunca."""
    _preparar()
    import core.database as d
    import core.indices_inei as I
    conn = d.get_db()
    try:
        conn.execute("UPDATE indices_inei_valores SET valor=1000.0 WHERE serie='1992' "
                     "AND anio=2024 AND mes=1 AND codigo='47' AND area='01'")
        conn.execute("INSERT OR REPLACE INTO indices_inei_valores "
                     "(codigo, serie, anio, mes, area, valor) VALUES "
                     "('01','1992',2026,3,'01',999.0)")
        conn.execute("DELETE FROM configuracion WHERE clave='indices_refresco_oficial'")
        conn.commit()
        I.refrescar_valores_oficiales(conn)
        v = conn.execute("SELECT valor FROM indices_inei_valores WHERE serie='1992' "
                         "AND anio=2024 AND mes=1 AND codigo='47' AND area='01'").fetchone()
        assert abs(v['valor'] - 742.39) < 0.005, v['valor']
        # La base 1992 no existe después de dic-2025: eso se borra.
        assert not conn.execute(
            "SELECT 1 FROM indices_inei_valores WHERE serie='1992' AND anio=2026"
        ).fetchone(), "quedaron valores de 1992 en 2026"
        # Y corre UNA sola vez: después vuelve a mandar el usuario.
        conn.execute("UPDATE indices_inei_valores SET valor=1.5 WHERE serie='1992' "
                     "AND anio=2024 AND mes=1 AND codigo='47' AND area='01'")
        conn.commit()
        I.refrescar_valores_oficiales(conn)
        v = conn.execute("SELECT valor FROM indices_inei_valores WHERE serie='1992' "
                         "AND anio=2024 AND mes=1 AND codigo='47' AND area='01'").fetchone()
        assert v['valor'] == 1.5, f"volvió a pisar al usuario: {v['valor']}"
    finally:
        conn.close()


def test_una_url_de_el_peruano_no_se_trata_como_excel():
    """«Desde una URL» tiene que reconocer las tres formas oficiales."""
    import core.indices_inei as ii
    llamadas = []
    reales = (ii.importar_html_elperuano, ii.descargar_resolucion_gobpe)
    ii.importar_html_elperuano = lambda u, **k: llamadas.append('peruano') or {'ok': True, 'rows': []}
    ii.descargar_resolucion_gobpe = lambda u, **k: llamadas.append('pdf') or {'ok': True, 'rows': []}
    try:
        ii.descargar_desde_url("https://busquedas.elperuano.pe/dispositivo/NL/2516442-1")
        ii.descargar_desde_url("https://cdn.www.gob.pe/uploads/document/file/1/x.pdf")
        assert llamadas == ['peruano', 'pdf'], llamadas
    finally:
        ii.importar_html_elperuano, ii.descargar_resolucion_gobpe = reales


def test_el_historico_publicado_degrada_si_no_responde():
    """La app no puede depender de que GitHub conteste."""
    import urllib.request
    import core.indices_inei as ii
    real = urllib.request.urlopen
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(OSError("sin red"))
    try:
        r = ii.descargar_indices_publicados()
        assert r['ok'] is False and 'sin red' in r['msg']
        assert r['rows'] == []
    finally:
        urllib.request.urlopen = real


def test_la_url_publicada_apunta_donde_el_repo_guarda_el_archivo():
    """La raíz del repositorio ES la app: no hay prefijo `app/`.

    Se escribió mal la primera vez y no se nota probando la app —la fuente
    degrada en silencio a las otras tres—; solo se ve cuando la Action falla o
    cuando alguien mira por qué el histórico nunca se actualiza. Lo mismo valía
    para el `working-directory` del workflow, que apuntaba a un directorio
    inexistente.
    """
    import subprocess
    from pathlib import Path
    from core.indices_inei import URL_INDICES_PUBLICADOS

    raiz = Path(subprocess.run(
        ['git', 'rev-parse', '--show-toplevel'],
        cwd=Path(__file__).parent, capture_output=True, text=True,
        check=True).stdout.strip())
    archivo = raiz / "resources" / "indices_inei_valores.json.gz"
    assert archivo.exists(), f"no está {archivo}"
    rel = archivo.relative_to(raiz).as_posix()
    assert URL_INDICES_PUBLICADOS.endswith(rel), (
        f"la URL termina en …{URL_INDICES_PUBLICADOS[-45:]!r} pero el archivo "
        f"vive en {rel!r}")

    wf = raiz / ".github" / "workflows" / "indices-inei.yml"
    assert wf.exists(), "falta el workflow que mantiene el histórico"
    assert 'working-directory' not in wf.read_text(encoding='utf-8'), \
        "el workflow apunta a un subdirectorio: la app está en la raíz"


if __name__ == "__main__":
    fallos = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print(f"  OK  {name}")
            except AssertionError as e:
                fallos += 1
                print(f"  FAIL {name}: {e}")
            except Exception as e:
                fallos += 1
                print(f"  ERROR {name}: {type(e).__name__}: {e}")
    if _tmpdb and os.path.exists(_tmpdb):
        os.unlink(_tmpdb)
    sys.exit(1 if fallos else 0)
