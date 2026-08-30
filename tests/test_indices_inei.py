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
def test_la_semilla_son_72_entradas_con_huecos():
    """Eran 72, no 80. El comentario decía 80 y los docs decían 72."""
    I = _preparar()
    cods = [c for c, _ in I.CATALOGO_INEI]
    assert len(cods) == 72, f"la semilla cambió de tamaño: {len(cods)}"
    assert max(int(c) for c in cods) == 80
    huecos = sorted(set(range(1, 81)) - {int(c) for c in cods})
    assert huecos == [25, 35, 36, 58, 63, 67, 75, 76], huecos


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
    I = _preparar()
    I.crear_indice('91', 'Índice de prueba')
    assert ('91', 'Índice de prueba') in I.catalogo()
    I.actualizar_indice('91', nombre='Renombrado')
    assert ('91', 'Renombrado') in I.catalogo()
    I.eliminar_indice('91')
    assert '91' not in dict(I.catalogo())


def test_no_se_puede_duplicar_un_codigo():
    I = _preparar()
    I.crear_indice('92', 'Uno')
    try:
        I.crear_indice('92', 'Otro')
    except ValueError:
        return
    raise AssertionError("dejó crear dos veces el mismo código")


def test_nombre_vacio_se_rechaza():
    I = _preparar()
    for fn in (lambda: I.crear_indice('93', '   '),
               lambda: I.actualizar_indice('01', nombre='')):
        try:
            fn()
        except ValueError:
            continue
        raise AssertionError("aceptó un nombre vacío")


def test_desactivar_lo_saca_del_catalogo_pero_no_de_la_tabla():
    I = _preparar()
    I.crear_indice('94', 'Desactivable')
    I.actualizar_indice('94', activo=False)
    assert '94' not in dict(I.catalogo())
    assert '94' in dict(I.catalogo(incluir_inactivos=True))


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
    """El archivo del INEI trae códigos > 80; antes entraban invisibles."""
    I = _preparar()
    assert '85' not in dict(I.catalogo())
    ok, err = I.guardar_valores([
        {'codigo': '85', 'anio': 2026, 'mes': 3, 'area': '01', 'valor': 123.45,
         'nombre': 'Índice nuevo del INEI'},
    ])
    assert ok == 1 and err == 0, (ok, err)
    cat = dict(I.catalogo())
    assert '85' in cat, "el valor entró pero el índice siguió invisible"
    assert cat['85'] == 'Índice nuevo del INEI'
    assert I.obtener_valor('85', 2026, 3) == 123.45


def test_el_alta_automatica_usa_nombre_provisional_si_no_viene():
    I = _preparar()
    I.guardar_valores([
        {'codigo': '86', 'anio': 2026, 'mes': 4, 'area': '01', 'valor': 100.0},
    ])
    assert dict(I.catalogo())['86'] == 'Índice 86'


# ── Huérfanos: códigos usados que el catálogo no define ──────────────────────
def test_codigos_huerfanos_encuentra_los_de_la_biblioteca_semilla():
    """La propia semilla trae insumos con IU que el catálogo no tenía."""
    I = _preparar()
    codigos = {h['codigo'] for h in I.codigos_huerfanos()}
    assert '99' in codigos, f"no detectó el 99: {sorted(codigos)}"


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
    I.crear_indice('95', 'Con insumos')
    conn = d.get_db()
    conn.execute("UPDATE recursos SET indice_inei='95' "
                 "WHERE id IN (SELECT id FROM recursos LIMIT 3)")
    conn.commit()
    conn.close()
    usos = I.contar_usos('95')
    assert usos['recursos'] == 3, usos
    I.eliminar_indice('95')
    quedan = _crudo("SELECT COUNT(*) FROM recursos WHERE indice_inei='95'")[0][0]
    assert quedan == 3, "el borrado del catálogo se llevó los insumos"


def test_eliminar_puede_llevarse_el_historico_si_se_pide():
    I = _preparar()
    I.crear_indice('96', 'Con histórico')
    I.guardar_valor('96', 2026, 1, 50.0)
    assert I.contar_usos('96')['valores'] == 1
    I.eliminar_indice('96', borrar_valores=True)
    assert _crudo("SELECT COUNT(*) FROM indices_inei_valores "
                  "WHERE codigo='96'")[0][0] == 0


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
