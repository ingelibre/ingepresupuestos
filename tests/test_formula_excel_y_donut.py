"""Issues #46 (Excel de la fórmula y «Editar símbolo») y #47 (donut)."""
import io
import os
import shutil
import sys
import tempfile

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, '..'))

from PySide6.QtGui import QFont, QFontMetrics                     # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu      # noqa: E402

_app = QApplication.instance() or QApplication([])

import core.database as d                                         # noqa: E402

_fd, _tmpdb = tempfile.mkstemp(suffix='_formula_excel_test.db')
os.close(_fd)
shutil.copy(os.path.join(AQUI, '..', 'presupuestos_seed.db'), _tmpdb)
d.DB_PATH = _tmpdb
d.init_db()

import core.exporter as ex                                        # noqa: E402

MONOMIOS = [('J', 'MANO DE OBRA', '47', .35), ('C', 'CEMENTO', '21', .25),
            ('A', 'ACERO', '03', .20), ('M', 'MAQUINARIA', '48', .12),
            ('GU', 'GASTOS GENERALES Y UTILIDAD', '39', .08)]

_c = d.get_db()
PID = _c.execute("SELECT id FROM proyectos ORDER BY id DESC").fetchone()['id']
_c.execute("DELETE FROM formula_monomios WHERE proyecto_id=?", (PID,))
for _i, (_s, _d2, _ix, _k) in enumerate(MONOMIOS):
    _c.execute("INSERT INTO formula_monomios (proyecto_id, simbolo, descripcion,"
               " indice_inei, coeficiente, orden) VALUES (?,?,?,?,?,?)",
               (PID, _s, _d2, _ix, _k, _i + 1))
_c.commit()
_c.close()


def test_el_excel_lista_todos_los_monomios():
    import openpyxl
    ws = openpyxl.load_workbook(
        io.BytesIO(ex.exportar_formula_polinomica(PID).getvalue())).active
    filas = [[c.value for c in r] for r in ws.iter_rows()]
    ini = next(i for i, r in enumerate(filas) if r[0] == 'Símbolo')
    assert [tuple(f[:4]) for f in filas[ini + 1:ini + 6]] == MONOMIOS
    assert filas[ini + 6][0] == 'TOTAL' and filas[ini + 6][3] == pytest.approx(1.0)


def test_editar_simbolo_con_clic_derecho():
    from views.formula_view import FormulaView
    v = FormulaView(PID, "X")
    v._monomios = [dict(simbolo=s, descripcion=x, indice_inei=i, coeficiente=k,
                        componentes=[]) for s, x, i, k in MONOMIOS]
    v.resize(1300, 900)
    v.show()
    v._render_tabla()
    _app.processEvents()
    from PySide6.QtCore import Qt
    assert v.tbl.contextMenuPolicy() == Qt.CustomContextMenu
    menu = v._crear_menu_monomio(2)
    assert [a.text() for a in menu.actions()] == ['Editar símbolo']
    menu.actions()[0].trigger()
    assert (v.tbl.currentRow(), v.tbl.currentColumn()) == (2, 1)
    editores = [e for e in v.tbl.findChildren(QLineEdit) if e.isVisible()]
    assert editores and editores[0].text() == 'A'
    v.tbl.item(2, 1).setText('AC')
    assert v._monomios[2]['simbolo'] == 'AC'
    v.hide()


def test_los_montos_del_donut_van_en_una_linea():
    from views.proyecto_view import _DonutChart
    datos = [("Mano de Obra", 544272.24, "#F39C12"), ("Materiales", 920353.48, "#27AE60"),
             ("Equipo", 96091.58, "#607D8B"), ("Sub-contratos", 8012.5, "#7A36B1")]
    ch = _DonutChart(datos, moneda="Soles")

    def en_dos(W, pt):
        f = QFont()
        f.setPointSizeF(pt)
        return any(dos for *_r, dos in ch._filas_leyenda(W, QFontMetrics(f), pt))

    # El ancho justo en que el cuerpo normal ya no alcanza.
    W = next(w for w in range(600, 100, -1) if en_dos(w, 8.0))
    f = ch._fuente_leyenda(W)
    assert f.pointSizeF() < 8 and not en_dos(W, f.pointSizeF())
    assert ch._fuente_leyenda(600).pointSizeF() == 8
    # Con una sola línea por entrada, el alto que pide es el de una línea.
    assert ch._alto_necesario(W) == ch._alto_necesario(600)
