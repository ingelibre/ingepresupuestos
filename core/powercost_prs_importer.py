# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari / Sumari SAC
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Licensed under the GNU GPL v3.0 or later. See the LICENSE file.
"""Importador de proyectos desde un archivo .prs (PowerCost).

PowerCost almacena sus proyectos en un MS Access database (Jet 4.0).
- Linux: usamos ``mdbtools`` (paquete del sistema).
- Windows: usamos ``pyodbc`` con el driver ODBC de Microsoft Access
  (viene con Office o se instala gratis: "Microsoft Access Database
  Engine Redistributable").

Estructura PowerCost relevante:

  Pptos               (1 fila)            ← proyecto principal
  SubPptos            (N filas)           ← sub-presupuestos
  EstSubPpto          (árbol jerárquico)  ← partidas y títulos del proyecto
                                            usa IdPartidaPadre para anidar
  Titulos             (catálogo)          ← nombres de los títulos
  Analisis            (catálogo)          ← ACUs: NomAnalisis, Unidad, Rend
  EstAnalisis         (composiciones)     ← insumos del ACU con Tipo, Cuad,
                                            Cantidad
  Insumos             (catálogo)          ← recursos del proyecto, con
                                            NomInsumo, Unidad, IdIU (INEI),
                                            IdTipoIns
  PreciosIns          (precios)           ← precio por insumo en el proyecto
  EstMetradoNorm4     (metrados)          ← planilla de metrados detallados
                                            enlazada via IdMetrado4
"""
import csv
import io
import os
import shutil
import subprocess
import sys
from typing import Optional

_IS_WINDOWS = sys.platform == 'win32'


class AccessPasswordError(Exception):
    """El archivo .mdb/.prs está protegido con contraseña."""
    pass


# ── Helpers ─────────────────────────────────────────────────────────────────

# Jet 4.0 XOR key — la "contraseña" de base de datos Access 2000/XP/2003
# está en el header del archivo en offset 0x42, XOR'd con esta clave.
# mdbtools en Linux la ignora (lee datos crudos); ODBC la exige.
_JET4_PWD_KEY = bytes([
    0x86, 0xfb, 0xec, 0x37, 0x5d, 0x44, 0x9c, 0xfa,
    0xc6, 0x5e, 0x28, 0xe6, 0x13, 0xb6, 0x8a, 0x60,
    0x54, 0x94,
])


def _extract_jet_password(filepath: str) -> str:
    """Extrae la contraseña de un .mdb Jet 4.0 desde el header del archivo."""
    try:
        with open(filepath, 'rb') as f:
            header = f.read(0x80)
        if len(header) < 0x6A:
            return ''
        enc = header[0x42:0x42 + 40]
        key = _JET4_PWD_KEY
        dec = bytes(b ^ key[i % len(key)] for i, b in enumerate(enc))
        return dec.decode('utf-16-le').split('\x00')[0]
    except Exception:
        return ''


def _get_access_odbc_driver() -> str | None:
    """Busca un driver ODBC de Microsoft Access instalado en Windows."""
    try:
        import pyodbc
        drivers = pyodbc.drivers()
        for name in drivers:
            if 'Microsoft Access Driver' in name:
                return name
    except ImportError:
        pass
    return None


def _verificar_backend() -> None:
    """Lanza RuntimeError si no hay backend disponible para leer .mdb."""
    if _IS_WINDOWS:
        driver = _get_access_odbc_driver()
        if not driver:
            raise RuntimeError(
                "No se encontro el driver ODBC de Microsoft Access.\n\n"
                "Si tienes Office instalado, ya deberia estar disponible.\n"
                "Si no, instala gratis el 'Microsoft Access Database Engine':\n"
                "  https://www.microsoft.com/en-us/download/details.aspx?id=54920\n\n"
                "(es necesario para leer archivos .prs de PowerCost)"
            )
    else:
        if not _mdb_disponible():
            raise RuntimeError(
                "mdbtools no esta instalado. Instalalo con:\n"
                "  sudo apt install -y mdbtools\n"
                "(es necesario para leer archivos .prs de PowerCost)"
            )


def _en_flatpak_host(cmd: list[str]) -> list[str]:
    """Enruta un comando de mdbtools. Prefiere el binario LOCAL: el embebido en
    la edición Flathub (``/app/bin/mdb-export``) o el del sistema en instalación
    nativa. Solo si NO hay mdb-export local y corremos en un Flatpak con acceso
    al host (edición sideload, con ``--talk-name=org.freedesktop.Flatpak``) lo
    enruta con ``flatpak-spawn --host`` (allí mdbtools vive en el host).

    Distinguir por la presencia del binario local es clave: en Flathub
    ``flatpak-spawn --host`` está BLOQUEADO, así que enrutar al host rompería la
    importación .prs pese al mdbtools embebido.

    Se fija ``--directory`` al home del usuario porque flatpak-spawn hereda el
    cwd del proceso (bajo Flatpak = ``/app/…``, inexistente en el host)."""
    import os
    from core.config import es_flatpak
    if shutil.which('mdb-export'):
        return cmd                       # binario local (embebido o nativo)
    if es_flatpak():
        # flatpak-spawn exige --directory=DIR (con «=», no separado).
        host_dir = os.environ.get('HOME') or '/'
        return ['flatpak-spawn', '--host', f'--directory={host_dir}'] + cmd
    return cmd


def _mdb_disponible() -> bool:
    """True si mdb-export está disponible: primero el local (embebido en la
    edición Flathub o del sistema); si no, el del host (Flatpak sideload)."""
    if shutil.which('mdb-export'):
        return True
    from core.config import es_flatpak
    if es_flatpak():
        try:
            r = subprocess.run(
                _en_flatpak_host(['which', 'mdb-export']),
                capture_output=True, text=True, timeout=10,
            )
            return r.returncode == 0 and bool(r.stdout.strip())
        except Exception:
            return False
    return False


def _query_mdbtools(filepath: str, table: str) -> list[dict]:
    """Lee una tabla del .mdb via mdb-export (Linux)."""
    proc = subprocess.run(
        _en_flatpak_host(['mdb-export', '-D', '%Y-%m-%d %H:%M:%S', filepath, table]),
        capture_output=True, text=True, check=False
    )
    if proc.returncode != 0:
        return []
    return list(csv.DictReader(io.StringIO(proc.stdout)))


def _patch_access_parser():
    """Corrige dos bugs en access_parser 0.0.6:
    1. Null bitmap: se calcula con column_count (columnas lógicas) pero
       field_count incluye columnas de sistema → desalinea el metadata.
    2. Variable offsets: usa índice secuencial (enumerate) pero debe usar
       variable_column_number para indexar la tabla de offsets."""
    import struct
    import access_parser.access_parser as _ap
    from access_parser.access_parser import AccessTable
    if getattr(AccessTable, '_patched', False):
        return

    _orig_row = AccessTable._parse_row

    def _parse_row_fixed(self, record):
        if self.version > 3 and len(record) >= 2:
            field_count = struct.unpack_from('h', record)[0]
            real_len = (field_count + 7) // 8
            hdr_len = (self.table_header.column_count + 7) // 8
            if real_len > hdr_len:
                self.table_header.column_count = field_count
        return _orig_row(self, record)

    def _parse_dynamic_fixed(self, original_record, metadata,
                             col_map, null_table):
        offsets = list(metadata.variable_length_field_offsets)
        var_len_count = metadata.var_len_count
        for column_index in col_map:
            column = col_map[column_index]
            col_name = column.col_name_str
            has_value = True
            if column.column_id < len(null_table):
                has_value = null_table[column.column_id]
            if not has_value:
                self.parsed_table[col_name].append(None)
                continue
            vn = column.variable_column_number
            if vn >= len(offsets):
                self.parsed_table[col_name].append(None)
                continue
            start = offsets[vn]
            end = offsets[vn + 1] if vn + 1 < len(offsets) else var_len_count
            if start == end:
                self.parsed_table[col_name].append('')
                continue
            data = original_record[start:end]
            if column.type == _ap.TYPE_MEMO:
                try:
                    val = self._parse_memo(data)
                except Exception:
                    val = data
            else:
                val = _ap.parse_type(column.type, data, len(data),
                                     version=self.version)
            self.parsed_table[col_name].append(val)

    AccessTable._parse_row = _parse_row_fixed
    AccessTable._parse_dynamic_length_data = _parse_dynamic_fixed
    AccessTable._patched = True


def _query_access_parser(filepath: str, table: str,
                         _db_cache: dict = {}) -> list[dict]:
    """Lee una tabla del .mdb via access_parser (fallback sin ODBC/password)."""
    _patch_access_parser()
    from access_parser import AccessParser
    cache_key = os.path.normcase(os.path.abspath(filepath))
    if cache_key not in _db_cache:
        _db_cache[cache_key] = AccessParser(filepath)
    db = _db_cache[cache_key]
    try:
        tbl = db.parse_table(table)
    except Exception:
        return []
    cols = list(tbl.keys())
    if not cols:
        return []
    n_rows = len(tbl[cols[0]])
    return [{col: (tbl[col][i] if tbl[col][i] is not None else '')
             for col in cols}
            for i in range(n_rows)]


def _query_odbc(filepath: str, table: str, password: str = '',
                _conn_cache: dict = {}) -> list[dict]:
    """Lee una tabla del .mdb via pyodbc (Windows).
    Si ODBC falla por contraseña, usa access_parser como fallback."""
    import pyodbc
    cache_key = (os.path.normcase(os.path.abspath(filepath)), password)
    if cache_key not in _conn_cache:
        driver = _get_access_odbc_driver()
        conn_str = (
            f"DRIVER={{{driver}}};"
            f"DBQ={filepath};"
            "ReadOnly=1;"
        )
        if password:
            conn_str += f"PWD={password};"
        try:
            _conn_cache[cache_key] = pyodbc.connect(conn_str)
        except pyodbc.Error as exc:
            if '-1905' in str(exc):
                return _query_access_parser(filepath, table)
            raise
    conn = _conn_cache[cache_key]
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM [{table}]")
        cols = [desc[0] for desc in cursor.description]
        rows = []
        for row in cursor.fetchall():
            rows.append({col: (val if val is not None else '')
                         for col, val in zip(cols, row)})
        return rows
    except pyodbc.ProgrammingError:
        return []


def _query(filepath: str, table: str) -> list[dict]:
    """Lee toda una tabla del .prs como lista de dicts."""
    if _IS_WINDOWS:
        return _query_odbc(filepath, table)
    return _query_mdbtools(filepath, table)


def _str(v) -> str:
    if v is None:
        return ''
    return str(v).strip()


def _num(v, default: float = 0.0) -> float:
    if v is None or v == '':
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _int(v, default: int = 0) -> int:
    if v is None or v == '':
        return default
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _leer_pie(q, id_ppto: int, cd: float) -> tuple[list, list]:
    """Lee el pie de presupuesto de PowerCost y lo traduce al modelo de la app.

    PowerCost guarda el pie en dos tablas:
      - ``PiePpto``   — una fila por renglón, con ``Expresion`` (la fórmula:
        ``U= CD*4/100``, ``IGV = ST*18/100``, ``GG= <<Detalle>>``…),
        ``Orden`` de impresión y ``TipoPie`` (5/6 = separador visual).
      - ``EstGGs``    — el desagregado de los renglones «<<Detalle>>»,
        agrupado por ``IdPos``, con NoPersonas/NoUnidades/Participacion.
    ``ValoresPieP`` (los montos ya calculados) suele venir VACÍA: PowerCost
    recalcula del árbol al abrir, así que hay que resolver las fórmulas.

    Devuelve ``(rubros, detalle)`` listos para `guardar_importacion`:
      rubros  → [(codigo, nombre, pct, activo, orden, tipo, mostrar_pct)]
      detalle → [{'rubro','tipo','descripcion','unidad','n_personas',
                  'tiempo','pct_participacion','precio','cantidad','orden'}]
    Con `[], []` si el archivo no trae pie (el llamador cae al default).
    """
    filas = [r for r in q('PiePpto') if _int(r.get('IdPpto')) == id_ppto]
    if not filas:
        return [], []
    filas.sort(key=lambda r: _int(r.get('Orden')))

    # ── Desagregado por IdPos (los renglones «<<Detalle>>») ────────────────
    ins_by_id = {_int(r['IdInsumo']): r for r in q('Insumos')}
    tit_by_id = {_int(r['IdTitulo']): _str(r['NomTitulo']) for r in q('Titulos')}
    precio_de = {_int(r['IdInsumo']): _num(r['Precio'])
                 for r in q('PreciosIns') if _int(r.get('IdPpto')) == id_ppto}
    gg_por_pos: dict[int, list[dict]] = {}
    for r in q('EstGGs'):
        if _int(r.get('IdPpto')) != id_ppto:
            continue
        gg_por_pos.setdefault(_int(r['IdPos']), []).append(r)
    for lst in gg_por_pos.values():
        lst.sort(key=lambda r: _int(r.get('Orden')))

    def _detalle_de(idpos: int, codigo: str) -> tuple[list, float]:
        """Convierte las filas de EstGGs de un rubro y devuelve (filas, total)."""
        out, total = [], 0.0
        for i, r in enumerate(gg_por_pos.get(idpos, [])):
            if _int(r.get('TipoDetalle')) == 1:      # fila de TÍTULO
                out.append({
                    'rubro': codigo, 'tipo': 'titulo',
                    'descripcion': tit_by_id.get(_int(r['IdTitulo']), '') or '',
                    'unidad': '', 'n_personas': 0, 'tiempo': 0,
                    'pct_participacion': 100, 'precio': 0, 'cantidad': 0,
                    'orden': i,
                })
                continue
            ins = ins_by_id.get(_int(r['IdInsumo']))
            if not ins:
                continue
            # `Cantidad` ya viene resuelta por PowerCost (NoPersonas ×
            # NoUnidades × Participacion cuando aplica); si viniera en 0 se
            # reconstruye. `Participacion` es fracción (1 = 100%).
            part = _num(r.get('Participacion'), 1.0)
            cant = _num(r.get('Cantidad'))
            if not cant:
                cant = (_num(r.get('NoPersonas')) * _num(r.get('NoUnidades'))
                        * (part or 1.0))
            precio = precio_de.get(_int(r['IdInsumo']), 0.0)
            total += cant * precio
            out.append({
                'rubro': codigo, 'tipo': 'item',
                'descripcion': _str(ins.get('NomInsumo')),
                'unidad': _str(ins.get('Unidad')),
                'n_personas': _num(r.get('NoPersonas')),
                'tiempo': _num(r.get('NoUnidades')),
                # La app multiplica por pct/100, y PowerCost ya metió la
                # participación dentro de `Cantidad` → aquí va 100 para no
                # aplicarla dos veces.
                'pct_participacion': 100.0,
                'precio': precio, 'cantidad': cant, 'orden': i,
            })
        return out, total

    # ── Traducir cada renglón ──────────────────────────────────────────────
    # Códigos de la app (mismos que `rubros_default` en core/importer.py).
    _POR_NOMBRE = [
        ('SUPERVIS',  'SUP',  'rubro'),
        # Los nombres varían por obra: «EXPEDIENTE TECNICO», «GASTOS DE
        # EXP. TEC.»… El tipo lo decide la estructura (ver abajo); estos
        # patrones solo eligen un CÓDIGO legible.
        ('EXPEDIENTE','ET',   'rubro'),
        ('EXP. TEC',  'ET',   'rubro'),
        ('EXP TEC',   'ET',   'rubro'),
        ('EXPED',     'ET',   'rubro'),
        ('LIQUIDAC',  'LQ',   'rubro'),
        ('GASTOS GENERALES', 'GG', 'rubro'),
        ('UTILIDAD',  'UTIL', 'pct_cd'),
        ('IGV',       'IGV',  'pct_sub'),
        # Acumulados conocidos: código corto y legible en vez del que
        # saldría de destripar el nombre («VALORREFER», «COSTOTOTAL»).
        ('SUB TOTAL', 'SUB',  'subtotal'),
        ('VALOR REFERENCIAL', 'VR', 'subtotal'),
        ('COSTO TOTAL', 'CT', 'subtotal'),
        ('PRESUPUESTO TOTAL', 'CT', 'subtotal'),
    ]
    import re as _re
    rubros, detalle, orden = [], [], 0
    usados: set = set()
    for f in filas:
        tipo_pie = _int(f.get('TipoPie'))
        nombre = _str(f.get('Descripcion'))
        expr = _str(f.get('Expresion'))
        if tipo_pie in (5, 6) or not nombre:
            continue                      # separador visual, sin contenido
        up = nombre.upper()
        if up.startswith('COSTO DIRECTO'):
            continue                      # el CD es la base, no un rubro
        if _int(f.get('EsTotal')) == 1:
            # El renglón del gran total (PowerCost lo marca con EsTotal=1) NO
            # se importa: la app ya cierra el pie con su propia línea de total.
            # Si se importara saldría el mismo monto dos veces seguidas.
            continue
        idpos = _int(f.get('IdPos'))

        codigo = tipo = None
        for clave, cod, tp in _POR_NOMBRE:
            if clave in up:
                codigo, tipo = cod, tp
                break

        # El NOMBRE no basta para decidir el tipo: cada obra bautiza sus
        # rubros a su manera («GASTOS DE EXP. TEC.» no contiene
        # «EXPEDIENTE»). Manda la ESTRUCTURA del archivo:
        #   · tiene desagregado en EstGGs          → 'rubro'
        #   · la fórmula lleva  <<Detalle>>        → 'rubro' (aunque venga vacío)
        #   · la fórmula lleva  ST*n/100           → 'pct_sub'
        #   · la fórmula lleva  CD*n/100           → 'pct_cd'
        #   · resto (suma de términos ya calculados) → 'subtotal'
        _expr_sin_esp = expr.replace(' ', '').upper()
        if gg_por_pos.get(idpos) or '<<DETALLE>>' in expr.upper():
            tipo = 'rubro'
        elif tipo is None:
            if _re.search(r'\bST\s*\*', _expr_sin_esp):
                tipo = 'pct_sub'
            elif _re.search(r'\bCD\s*\*', _expr_sin_esp):
                tipo = 'pct_cd'
            else:
                tipo = 'subtotal'
        if codigo is None:
            codigo = _re.sub(r'[^A-Z0-9]', '', up)[:10] or f'POS{idpos}'
        while codigo in usados:            # nombres repetidos → código único
            codigo += 'X'
        usados.add(codigo)

        # Porcentaje: de `txPor` («4 %», «18 %») o de la propia fórmula
        # (`CD*4/100`). Si el rubro trae desagregado, manda el desagregado.
        pct = 0.0
        m = _re.search(r'([\d.,]+)\s*%', _str(f.get('txPor')))
        if m:
            pct = _num(m.group(1).replace(',', '.'))
        if not pct:
            m = _re.search(r'\*\s*([\d.,]+)\s*/\s*100', expr)
            if m:
                pct = _num(m.group(1).replace(',', '.'))

        filas_det, total_det = ([], 0.0)
        if tipo == 'rubro':
            filas_det, total_det = _detalle_de(idpos, codigo)
            if filas_det:
                detalle.extend(filas_det)
                if cd:
                    pct = total_det / cd * 100
            else:
                # Renglón sin desagregado: monto fijo en la fórmula
                # (`GL=  6000`) → se guarda como fila 'manual' del rubro.
                m = _re.search(r'=\s*([\d.,]+)\s*$', expr.replace(' ', ''))
                if m:
                    val = _num(m.group(1).replace(',', '.'))
                    if val:
                        detalle.append({
                            'rubro': codigo, 'tipo': 'manual',
                            'descripcion': nombre, 'unidad': '',
                            'n_personas': 0, 'tiempo': 0,
                            'pct_participacion': 100, 'precio': val,
                            'cantidad': 1, 'orden': 0,
                        })
                        if cd:
                            pct = val / cd * 100

        # PowerCost escribe todo en MAYÚSCULAS; se pasa a Capitalizado para
        # que case con el resto de la app, pero respetando siglas (IGV, CD…).
        _SIGLAS = {'IGV', 'CD', 'CT', 'ST', 'GG', 'IVA'}
        _bonito = ' '.join(w if w in _SIGLAS else w.capitalize()
                           for w in nombre.split()) if nombre.isupper() else nombre
        rubros.append((codigo, _bonito, round(pct, 6), 1, orden, tipo, 1))
        orden += 1
    return rubros, detalle


def _codigo_recurso(id_iu: int, id_tipo: int, id_insumo: int) -> str:
    """Construye un código de 7 dígitos: 2 INEI + 5 correlativo.

    El INEI viene de IdIU (1..80). Si el insumo es overhead/herramientas
    (%MO/%MAT/%EQ) el INEI se mantiene en 37 (Herramientas Manuales).
    """
    inei = max(0, id_iu) % 100
    corr = id_insumo % 100000
    return f"{inei:02d}{corr:05d}"


# ── Parser principal ───────────────────────────────────────────────────────

def import_powercost_prs(filepath: str,
                          id_ppto: Optional[int] = None,
                          id_subppto: Optional[int] = None):
    """Lee un .prs de PowerCost y devuelve (info, partidas, acus, recursos,
    metrados) compatible con ``core.importer.guardar_importacion()``.

    Argumentos:
      filepath: ruta al .prs
      id_ppto: opcional, ID del proyecto a importar. Si no se pasa y la
        base tiene varios proyectos, se importa el primero. Para archivos
        con cientos de proyectos, usar `listar_proyectos_powercost()` y
        pedirle al usuario que elija.
      id_subppto: opcional, ID de UN sub-presupuesto concreto. Si no se
        pasa se importan TODOS los del proyecto (IdSubPpto>0; la fila
        IdSubPpto=0 es el total y no se usa): el primero queda como
        Principal del proyecto y los demás viajan en cada partida vía
        ``sub_ref`` para que ``guardar_importacion()`` los cree dentro
        del mismo proyecto, replicando la estructura de PowerCost.

    Con varios sub-presupuestos los ítems se repiten entre subs (cada uno
    numera desde 01), así que ``acus_data``/``metrados_data`` se indexan
    por la clave única ``item_origen`` (``"<IdSubPpto>|<item>"``) que
    también lleva cada partida.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"No existe: {filepath}")
    _verificar_backend()

    # ── 1. Lectura de tablas ────────────────────────────────────────────
    q = lambda tbl: _query(filepath, tbl)

    pptos = q('Pptos')
    if not pptos:
        raise ValueError("El archivo no contiene presupuestos (tabla Pptos vacía).")
    if id_ppto is not None:
        proy = next((p for p in pptos if _int(p['IdPpto']) == id_ppto), None)
        if not proy:
            raise ValueError(
                f"No se encontró el proyecto IdPpto={id_ppto} en la base."
            )
    else:
        proy = pptos[0]
    id_ppto_real = _int(proy['IdPpto'])

    subpptos = q('SubPptos')
    subs_del_proy = [s for s in subpptos
                     if _int(s['IdPpto']) == id_ppto_real
                     and _int(s['IdSubPpto']) > 0]
    subs_del_proy.sort(key=lambda s: (_int(s.get('Orden')),
                                      _int(s['IdSubPpto'])))
    if id_subppto is not None:
        subs_sel = [s for s in subs_del_proy
                    if _int(s['IdSubPpto']) == id_subppto]
        if not subs_sel:
            raise ValueError(
                f"El proyecto IdPpto={id_ppto_real} no tiene el "
                f"sub-presupuesto IdSubPpto={id_subppto}."
            )
    else:
        subs_sel = subs_del_proy
        if not subs_sel:
            raise ValueError(
                f"El proyecto IdPpto={id_ppto_real} no tiene sub-presupuesto activo."
            )
    id_ppto = id_ppto_real

    # Nombre de cada sub-presupuesto, con desambiguación: dos subs con el
    # mismo nombre colapsarían en una sola pestaña al guardar (sub_ref es
    # el nombre), así que al repetido se le añade « (2)», « (3)»…
    nombres_subs: list[str] = []
    for s in subs_sel:
        n = _str(s.get('NomSubPpto')) or f"Sub-presupuesto {_int(s['IdSubPpto'])}"
        base, k = n, 2
        while n in nombres_subs:
            n = f"{base} ({k})"
            k += 1
        nombres_subs.append(n)

    titulos    = q('Titulos')
    analisis   = q('Analisis')
    est_anal   = q('EstAnalisis')
    insumos    = q('Insumos')
    precios    = q('PreciosIns')
    est_sub    = q('EstSubPpto')
    metr_norm  = q('EstMetradoNorm4')

    # Mapeos
    tit_by_id = {_int(r['IdTitulo']): _str(r['NomTitulo']) for r in titulos}
    anl_by_id = {_int(r['IdAnalisis']): r for r in analisis}
    ins_by_id = {_int(r['IdInsumo']): r for r in insumos}
    # Precios: (IdPpto, IdInsumo) → Precio
    precio_de = {
        (_int(r['IdPpto']), _int(r['IdInsumo'])): _num(r['Precio'])
        for r in precios if _int(r.get('Activo', 0) or 0) == 1
    }

    # Composiciones del ACU agrupadas por IdAnalisis
    comps_por_acu: dict[int, list[dict]] = {}
    for r in est_anal:
        aid = _int(r['IdAnalisis'])
        comps_por_acu.setdefault(aid, []).append(r)

    # Metrados detallados: agrupados por IdMetrado4
    met_por_id: dict[int, list[dict]] = {}
    for r in metr_norm:
        mid = _int(r['IdMetrado4'])
        met_por_id.setdefault(mid, []).append(r)
    for mid in met_por_id:
        met_por_id[mid].sort(key=lambda x: _int(x['Orden']))

    # ── 2. Construir info del proyecto ──────────────────────────────────
    info = {
        'nombre':          _str(proy.get('NomPpto')) or 'Proyecto importado',
        'cliente':         '',
        'ubicacion':       _str(proy.get('Localidad')),
        # El primer sub-presupuesto es el «Principal» del proyecto; los
        # demás los crea guardar_importacion() a partir de sub_ref.
        'sub_presupuesto': nombres_subs[0],
        'costo_al':        _str(proy.get('Fecha')),
    }

    # ── Pie de presupuesto REAL del archivo (PiePpto + EstGGs) ──────────
    # Antes se sembraba un pie genérico inactivo; ahora se replica el del
    # .prs con sus rubros, porcentajes y desagregado de costos indirectos.
    try:
        _cd_arch = _num(proy.get('CD'))
        _pie_rubros, _pie_detalle = _leer_pie(q, id_ppto, _cd_arch)
        if _pie_rubros:
            info['pie_rubros'] = _pie_rubros
            info['pie_detalle'] = _pie_detalle
        elif any(_int(r.get('IdPpto')) == id_ppto for r in q('PiePpto')):
            # El archivo SÍ trae pie, pero solo el renglón «COSTO DIRECTO»:
            # en PowerCost ese presupuesto no lleva costos indirectos. Hay que
            # decirlo explícitamente (0 %), porque si no la app aplicaría sus
            # porcentajes por defecto (10/5/18) y el total no cuadraría con el
            # archivo.
            info['gf_pct'] = 0.0
            info['utilidad_pct'] = 0.0
            info['igv_pct'] = 0.0
            info['pie_activo_default'] = False
    except Exception:
        # Un pie ilegible no debe tumbar la importación del presupuesto:
        # se cae al pie por defecto y el usuario lo ajusta a mano.
        pass

    # ── 3. Helpers compartidos entre sub-presupuestos ───────────────────

    # Descripciones de partidas (preferir IdAnalisis.NomAnalisis o IdTitulo)
    def descripcion(row: dict) -> str:
        t = _int(row['Tipo'])
        if t == 1:   # título
            return tit_by_id.get(_int(row['IdTitulo']), '') or '(sin nombre)'
        # partida con análisis
        aid = _int(row['IdAnalisis'])
        an = anl_by_id.get(aid)
        if an:
            return _str(an['NomAnalisis']) or '(sin análisis)'
        return '(partida sin análisis)'

    def unidad_part(row: dict) -> str:
        if _int(row['Tipo']) == 1:
            return ''
        an = anl_by_id.get(_int(row['IdAnalisis']))
        return _str(an['Unidad']) if an else ''

    # Tipos de costo en PowerCost: 1=MO, 2=MAT, 3=EQ + IdCategoria 2=SUB CONTRATO.
    # PowerCost no tiene tipo SC explícito, pero clasifica insumos en
    # Categoria SUB CONTRATO (cat_id=2) → los mapeamos a SC.
    def map_tipo(t: int) -> str:
        # IdTipoIns: 1=MO, 2=MAT, 3=EQ. NO usar IdCategoria: la categoría 2
        # incluye OPERARIO/OFICIAL/CEMENTO (verificado en bases reales) — no
        # significa subcontrato. Los SC reales entran como sub-análisis.
        return {1: 'MO', 2: 'MAT', 3: 'EQ'}.get(t, 'MAT')

    def _es_global_anl(an: dict) -> bool:
        """Análisis global (glb/est/serv): cantidades directas, sin cuadrilla."""
        u = _str(an.get('Unidad', '')).strip().rstrip('.').lower()
        return u in ('glb', 'gbl', 'est', 'serv')

    def _filas_acu(aid: int, _stack: frozenset = frozenset()) -> list[dict]:
        """Filas del ACU de `aid` con cantidad efectiva y precio resueltos.

        Una fila de EstAnalisis con IdSubAnalisis != 0 es una SUB-PARTIDA
        (análisis anidado): se importa como recurso SC cuyo precio es el
        costo unitario del sub-análisis, calculado recursivamente (la tabla
        PreciosSubAnl suele venir vacía). `_stack` evita ciclos."""
        an = anl_by_id.get(aid)
        if not an:
            return []
        rend_acu = _num(an['Rend'], 1.0) or 1.0
        jornada  = _num(an.get('NumHrs') if isinstance(an, dict) else None, 8.0)
        if not jornada:
            jornada = 8.0
        part_global = _es_global_anl(an)

        out = []
        for c in comps_por_acu.get(aid, []):
            said = _int(c.get('IdSubAnalisis') or 0)
            if said and said != aid and said not in _stack:
                sub = anl_by_id.get(said)
                if not sub:
                    continue
                out.append({
                    'tipo':        'SC',
                    'codigo':      f"99{said % 100000:05d}",
                    'descripcion': _str(sub.get('NomAnalisis')) or f'Sub-análisis {said}',
                    'unidad':      _str(sub.get('Unidad', '')) or 'und',
                    'cuadrilla':   0.0,
                    'cantidad':    _num(c['Cantidad']),
                    'precio':      _cu_analisis(said, _stack | {aid}),
                })
                continue

            id_ins = _int(c['IdInsumo'])
            ins = ins_by_id.get(id_ins)
            if not ins:
                continue
            # El tipo real (MO/MAT/EQ/SC) viene del INSUMO, no de la composición.
            # EstAnalisis.Tipo se refiere a algo distinto (sub-tipo interno).
            id_tipo_ins = _int(ins['IdTipoIns'])
            tipo = map_tipo(id_tipo_ins)
            id_iu = _int(ins['IdIU'])
            codigo = _codigo_recurso(id_iu, id_tipo_ins, id_ins)
            r_unidad = _str(ins.get('Unidad', '')) or 'und'
            r_desc = _str(ins.get('NomInsumo', '')) or f'Recurso {id_ins}'
            precio = precio_de.get((id_ppto, id_ins), 0.0)

            cuad = _num(c['Cuadrilla'])
            cant = _num(c['Cantidad'])
            # Para MO y EQ por hora (hh/hm), la cantidad SIEMPRE se deriva
            # de la cuadrilla mediante la fórmula canónica peruana:
            #     cant = cuadrilla / rendimiento * jornada
            # PowerCost almacena valores inconsistentes (a veces 0, a veces
            # truncados con jornada parcial). Sobreescribir asegura que el
            # ACU sea coherente con el editor de la app.
            unidad_lower = (r_unidad or '').strip().rstrip('.').lower()
            # MO/EQ por día (día/jor): el rendimiento ya es por día → la
            # fórmula NO lleva jornada (cant = cuadrilla / rend). La MO en
            # día NO debe caer en la fórmula horaria (inflaría ×jornada).
            es_por_dia = (
                tipo in ('MO', 'EQ')
                and unidad_lower in ('día', 'dia', 'días', 'dias', 'jor', 'jornada')
            )
            es_por_hora = not es_por_dia and (
                tipo == 'MO'
                or unidad_lower in ('hh', 'hm', 'h-h', 'h-m', 'jph', 'jh')
                or 'hora' in unidad_lower
            )
            if cuad and rend_acu > 0 and not part_global:
                if es_por_hora:
                    cant = (cuad / rend_acu) * jornada
                elif es_por_dia and tipo == 'MO':
                    # Solo MO-día se normaliza; EQ-día conserva la cantidad
                    # original de PowerCost (fidelidad de totales validada)…
                    cant = cuad / rend_acu
                elif es_por_dia and tipo == 'EQ' and not cant:
                    # …EXCEPTO equipo-día con cantidad 0: PowerCost la deriva
                    # de la cuadrilla (caso «ESTACION TOTAL» cuad=1, cant=0).
                    # Sin esto el equipo entra al ACU con parcial 0.
                    cant = cuad / rend_acu

            out.append({
                'tipo':        tipo,
                'codigo':      codigo,
                'descripcion': r_desc,
                'unidad':      r_unidad,
                'cuadrilla':   cuad,
                'cantidad':    cant,
                'precio':      precio,
            })
        return out

    _cu_memo: dict[int, float] = {}

    def _cu_analisis(aid: int, _stack: frozenset = frozenset()) -> float:
        """Costo unitario de un análisis (para sub-partidas anidadas), con las
        mismas reglas de suma que la app (parciales a 2 dec, %MO/%MAT sobre
        el subtotal del tipo)."""
        if aid in _cu_memo:
            return _cu_memo[aid]
        from core.database import _pu_desde_items
        cu = _pu_desde_items(_filas_acu(aid, _stack))
        _cu_memo[aid] = cu
        return cu

    # ── 4. Partidas, ACUs y metrados — POR SUB-PRESUPUESTO ──────────────
    partidas_data: list[dict] = []
    acus_data: dict = {}
    recursos_uniq: dict[str, dict] = {}
    metrados_data: dict[str, list[dict]] = {}

    # Numeración de títulos raíz CONTINUA entre sub-presupuestos, como en
    # PowerCost y sus reportes: si el sub 01 termina en el título 03, el
    # sub 02 empieza en 04 (verificado contra reportes reales: 01, 04, 08,
    # 11, 15, 21, 23…). Además deja el ítem único en todo el proyecto, que
    # es lo que asumen los reportes que ordenan por ítem sin agrupar por sub.
    raiz_sig = 1

    for _idx_sub, _sp in enumerate(subs_sel):
        sp_id = _int(_sp['IdSubPpto'])
        # El primer sub es el Principal del proyecto (sub_ref=None); los
        # demás llevan su nombre para que guardar_importacion() los cree
        # dentro del mismo proyecto.
        sub_ref = None if _idx_sub == 0 else nombres_subs[_idx_sub]

        # Filtrar las filas del sub-presupuesto en curso
        filas = [r for r in est_sub
                 if _int(r['IdPpto']) == id_ppto
                 and _int(r['IdSubPpto']) == sp_id]

        # Mapa: IdPartida → fila
        by_id = {_int(r['IdPartida']): r for r in filas}

        def nivel(idp: int) -> int:
            n, cur = 0, idp
            seen = set()
            while cur:
                cur_padre = _int(by_id.get(cur, {}).get('IdPartidaPadre', 0))
                if not cur_padre or cur_padre in seen:
                    break
                seen.add(cur_padre)
                cur = cur_padre
                n += 1
            return n

        def hijos(parent_id: int) -> list[int]:
            r = [pid for pid, row in by_id.items()
                 if _int(row['IdPartidaPadre']) == parent_id]
            r.sort(key=lambda x: (_int(by_id[x]['IdItem']),
                                   _str(by_id[x]['TxItem'])))
            return r

        # DFS desde las raíces (IdPartidaPadre=0)
        item_de: dict[int, str] = {}

        def emit(idp: int, prefijo: str, indice: int):
            # Numeración JERÁRQUICA por posición de hermano: 01, 01.01, 01.02,
            # 02, … NO usar TxItem/IdItem del .prs: en el .prs masivo TxItem
            # viene vacío y el fallback a IdItem (contador global) producía
            # numeración saltada (01, 04, 06, 13…). El orden de hermanos lo da
            # hijos() (por IdItem documental). Los niveles anidados reinician
            # por padre; solo los títulos RAÍZ continúan entre subs (raiz_sig).
            row = by_id[idp]
            item = (prefijo + '.' if prefijo else '') + f"{indice:02d}"
            item_de[idp] = item

            es_titulo = (_int(row['Tipo']) == 1)
            partidas_data.append({
                'item':            item,
                'item_origen':     f"{sp_id}|{item}",
                'sub_ref':         sub_ref,
                'descripcion':     descripcion(row),
                'unidad':          unidad_part(row),
                'metrado':         _num(row['Metrado']),
                'precio_unitario': _num(row['Precio']),
                'nivel':           min(nivel(idp) + 1, 4),
                'es_titulo':       1 if es_titulo else 0,
            })
            for i, child in enumerate(hijos(idp), 1):
                emit(child, item, i)

        n_raices = 0
        for i, r in enumerate(hijos(0), raiz_sig):
            emit(r, '', i)
            n_raices += 1
        raiz_sig += n_raices

        # ACUs (rendimiento + items) del sub en curso
        for idp, row in by_id.items():
            if _int(row['Tipo']) != 0:
                continue  # solo partidas, no títulos
            aid = _int(row['IdAnalisis'])
            if not aid:
                continue
            an = anl_by_id.get(aid)
            if not an:
                continue
            item = item_de.get(idp)
            if not item:
                continue

            items_acu = _filas_acu(aid)
            for it in items_acu:
                if it['codigo'] not in recursos_uniq:
                    recursos_uniq[it['codigo']] = {
                        'codigo':      it['codigo'],
                        'descripcion': it['descripcion'],
                        'tipo':        it['tipo'],
                        'unidad':      it['unidad'],
                        'precio':      it['precio'],
                    }

            if items_acu:
                acus_data[f"{sp_id}|{item}"] = {
                    'rendimiento': _num(an['Rend'], 1.0),
                    'items':       items_acu,
                }

        # Metrados detallados del sub en curso
        for idp, row in by_id.items():
            mid = _int(row.get('IdMetrado4', 0))
            if mid <= 0:
                continue
            item = item_de.get(idp)
            if not item:
                continue
            filas_m = met_por_id.get(mid, [])
            if not filas_m:
                continue
            det = []
            for f in filas_m:
                det.append({
                    'descripcion':   _str(f.get('Descripcion')),
                    'n_estructuras': _num(f.get('NEstr')),
                    'n_elementos':   _num(f.get('NElem')),
                    'area':          _num(f.get('Area')) or None,
                    'largo':         _num(f.get('Largo')),
                    'ancho':         _num(f.get('Ancho')),
                    'alto':          _num(f.get('Alto')),
                    'parcial':       _num(f.get('Parcial')),
                })
            if det:
                metrados_data[f"{sp_id}|{item}"] = det

    recursos_data = list(recursos_uniq.values())

    # ── 5. Conciliar PU con la suma del ACU ──────────────────────────────
    # PowerCost suma los parciales SIN redondear cada uno; la app los
    # redondea a 2 (criterio S10). Eso deja diferencias de ±1-2 céntimos.
    # Se adopta la suma de la app SOLO si el impacto monetario en el CD
    # (dif × metrado) es despreciable (≤ 1 sol): presupuesto autoconsistente
    # sin alterar el total. Con metrados grandes se conserva el PU del
    # archivo (fidelidad del total ante todo); la diferencia de céntimos
    # restante queda dentro de la tolerancia del detector PU≠ACU (0.02).
    from core.database import _pu_desde_items
    _EPS = 0.0005   # absorbe el ruido float de una dif de exactamente 0.02
    for p in partidas_data:
        if p.get('es_titulo'):
            continue
        acu = acus_data.get(p['item_origen'])
        if not acu:
            continue
        cu_app = _pu_desde_items(acu['items'])
        dif = abs(cu_app - (p.get('precio_unitario') or 0))
        impacto = dif * abs(p.get('metrado') or 0)
        if dif <= 0.02 + _EPS and impacto <= 1.0:
            p['precio_unitario'] = cu_app

    return info, partidas_data, acus_data, recursos_data, (metrados_data or None)


# ── API pública para listar proyectos ──────────────────────────────────────

def listar_proyectos_powercost(filepath: str) -> list[dict]:
    """Lista los proyectos disponibles en un .prs (para que el usuario
    elija cuando hay varios). Retorna lista ordenada por nombre con:
    id_ppto, nombre, fecha, cd, ct, localidad.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"No existe: {filepath}")
    _verificar_backend()
    pptos = _query(filepath, 'Pptos')
    out = []
    for p in pptos:
        nombre = _str(p.get('NomPpto'))
        if not nombre:
            continue
        out.append({
            'id_ppto':   _int(p['IdPpto']),
            'nombre':    nombre,
            'fecha':     _str(p.get('Fecha')),
            'cd':        _num(p.get('CD')),
            'ct':        _num(p.get('CT')),
            'localidad': _str(p.get('Localidad')),
        })
    out.sort(key=lambda x: x['nombre'])
    return out
