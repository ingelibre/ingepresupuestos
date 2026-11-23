# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari
# This file is part of IngePresupuestos — https://ingepresupuestos.com
# Software libre bajo la GNU GPL v3 o posterior. Ver el archivo LICENSE.
"""Modelos BIM dentro del presupuesto: elementos de un IFC o de un «takeoff»
de IngeTrazo, sus vínculos con las partidas y la actualización por diferencia.

Reglas:
* Las cantidades van SIEMPRE en SI. Una cantidad que el modelo no trae está
  ausente: nunca 0, nunca 1 inventado. (Contar una puerta como 1 und sí es
  un dato.)
* Se elige la cantidad por nombre según la clase (Qto_* de IFC): neta antes
  que bruta. Si solo hay bruta en un elemento con vanos, se avisa.
* Cada vínculo es UNA fila de `metrados_detalle`. Las filas escritas a mano
  no se tocan; una fila de vínculo que el usuario editó pasa a ser suya y la
  actualización la respeta.
* Borrar la fila en la planilla deshace el vínculo (ON DELETE CASCADE).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field

from core import ifc_lector as step
from utils.i18n import N_, tr

# ── Vocabulario IFC ──────────────────────────────────────────────────────────

# Subtipos concretos de IfcElement en IFC2x3, IFC4 e IFC4x3 ADD2 (sin vanos ni
# elementos virtuales), generados con los esquemas oficiales.
_CLASES = """
    Actuator AirTerminal AirTerminalBox AirToAirHeatRecovery Alarm AudioVisualAppliance Beam
    BeamStandardCase Bearing Boiler Borehole BuildingElementPart BuildingElementProxy
    BuiltElement Burner CableCarrierFitting CableCarrierSegment CableFitting CableSegment
    CaissonFoundation Chiller Chimney CivilElement Coil Column ColumnStandardCase
    CommunicationsAppliance Compressor Condenser Controller ConveyorSegment CooledBeam
    CoolingTower Course Covering CurtainWall Damper DeepFoundation DiscreteAccessory
    DistributionBoard DistributionChamberElement DistributionControlElement
    DistributionElement DistributionFlowElement Door DoorStandardCase DuctFitting
    DuctSegment DuctSilencer EarthworksElement EarthworksFill ElectricAppliance
    ElectricDistributionBoard ElectricDistributionPoint ElectricFlowStorageDevice
    ElectricFlowTreatmentDevice ElectricGenerator ElectricMotor ElectricTimeControl
    ElectricalElement ElementAssembly EnergyConversionDevice Engine EquipmentElement
    EvaporativeCooler Evaporator Fan Fastener Filter FireSuppressionTerminal FlowController
    FlowFitting FlowInstrument FlowMeter FlowMovingDevice FlowSegment FlowStorageDevice
    FlowTerminal FlowTreatmentDevice Footing FurnishingElement Furniture GeographicElement
    Geomodel Geoslice GeotechnicalStratum HeatExchanger Humidifier ImpactProtectionDevice
    Interceptor JunctionBox Kerb Lamp LightFixture LiquidTerminal MechanicalFastener
    MedicalDevice Member MemberStandardCase MobileTelecommunicationsAppliance MooringDevice
    MotorConnection NavigationElement Outlet Pavement Pile PipeFitting PipeSegment Plate
    PlateStandardCase ProtectiveDevice ProtectiveDeviceTrippingUnit Pump Rail Railing Ramp
    RampFlight ReinforcedSoil ReinforcingBar ReinforcingMesh Roof SanitaryTerminal Sensor
    ShadingDevice Sign Signal Slab SlabElementedCase SlabStandardCase SolarDevice
    SpaceHeater StackTerminal Stair StairFlight SwitchingDevice SystemFurnitureElement Tank
    Tendon TendonAnchor TendonConduit TrackElement Transformer TransportElement TubeBundle
    UnitaryControlElement UnitaryEquipment Valve Vehicle VibrationDamper VibrationIsolator
    Wall WallElementedCase WallStandardCase WasteTerminal Window WindowStandardCase
""".split()
CLASES = {('IFC' + c.upper()): 'Ifc' + c for c in _CLASES}
CLASES['IFCSPACE'] = 'IfcSpace'

_A_LADO = ('NetSideArea', 'GrossSideArea', 'Area')
_A = ('NetArea', 'GrossArea', 'ProjectedArea', 'Area')
_V = ('NetVolume', 'GrossVolume', 'Volume')
_L = ('Length',)
_P = ('NetWeight', 'GrossWeight', 'Weight')
# Nombres aceptados para cada unidad cuando no manda la clase.
_POR_UNIDAD = {
    'm2': ('NetSideArea', 'NetArea', 'NetFloorArea', 'GrossSideArea', 'GrossArea',
           'ProjectedArea', 'GrossFloorArea', 'Area', 'NetSurfaceArea',
           'GrossSurfaceArea', 'OuterSurfaceArea'),
    'm3': _V, 'm': _L, 'kg': _P, 'und': ('Count',),
}


def _pref():
    d = {}
    for nombres, regla in (
        ('Wall WallStandardCase WallElementedCase CurtainWall', ('m2', _A_LADO)),
        ('Slab SlabStandardCase SlabElementedCase Roof Covering Plate PlateStandardCase '
         'Ramp RampFlight Stair Pavement ShadingDevice SolarDevice', ('m2', _A)),
        ('Space', ('m2', ('NetFloorArea', 'GrossFloorArea'))),
        ('Beam BeamStandardCase Column ColumnStandardCase Footing StairFlight '
         'DeepFoundation CaissonFoundation EarthworksFill ReinforcedSoil', ('m3', _V)),
        ('Pile Member MemberStandardCase Railing Chimney Kerb Rail FlowSegment PipeSegment '
         'DuctSegment CableSegment CableCarrierSegment ConveyorSegment', ('m', _L)),
        ('ReinforcingBar ReinforcingMesh Tendon', ('kg', _P)),
    ):
        for n in nombres.split():
            d['Ifc' + n] = regla
    # No se sabe en qué unidad se presupuestan: sin cantidad no se cuentan.
    sin_regla = set(('BuildingElementProxy BuiltElement BuildingElementPart CivilElement '
                     'GeographicElement Geomodel Geoslice GeotechnicalStratum Borehole '
                     'ElementAssembly EarthworksElement Course TrackElement '
                     'DiscreteAccessory Fastener MechanicalFastener TendonAnchor '
                     'TendonConduit').split())
    for c in _CLASES:
        if c not in sin_regla:
            d.setdefault('Ifc' + c, ('und', ()))
    return d


PREFERENCIA = _pref()

# clase → (código de grupo, título del grupo, nombre de la partida)
_GRUPOS = {
    'IfcFooting': ('01', N_('CIMENTACIONES'), N_('ZAPATA')),
    'IfcPile': ('01', N_('CIMENTACIONES'), N_('PILOTE')),
    'IfcWall': ('02', N_('MUROS Y TABIQUES'), N_('MURO')),
    'IfcCurtainWall': ('02', N_('MUROS Y TABIQUES'), N_('MURO CORTINA')),
    'IfcSlab': ('03', N_('LOSAS'), N_('LOSA')),
    'IfcBeam': ('04', N_('VIGAS'), N_('VIGA')),
    'IfcColumn': ('05', N_('COLUMNAS'), N_('COLUMNA')),
    'IfcRoof': ('06', N_('TECHOS Y COBERTURAS'), N_('TECHO')),
    'IfcStair': ('07', N_('ESCALERAS Y RAMPAS'), N_('ESCALERA')),
    'IfcStairFlight': ('07', N_('ESCALERAS Y RAMPAS'), N_('TRAMO DE ESCALERA')),
    'IfcRamp': ('07', N_('ESCALERAS Y RAMPAS'), N_('RAMPA')),
    'IfcRampFlight': ('07', N_('ESCALERAS Y RAMPAS'), N_('TRAMO DE RAMPA')),
    'IfcRailing': ('07', N_('ESCALERAS Y RAMPAS'), N_('BARANDA')),
    'IfcDoor': ('08', N_('PUERTAS'), N_('PUERTA')),
    'IfcWindow': ('09', N_('VENTANAS'), N_('VENTANA')),
    'IfcPlate': ('10', N_('ELEMENTOS ESTRUCTURALES'), N_('PLACA')),
    'IfcMember': ('10', N_('ELEMENTOS ESTRUCTURALES'), N_('ELEMENTO')),
    'IfcReinforcingBar': ('10', N_('ELEMENTOS ESTRUCTURALES'), N_('ACERO DE REFUERZO')),
    'IfcReinforcingMesh': ('10', N_('ELEMENTOS ESTRUCTURALES'), N_('MALLA DE REFUERZO')),
    'IfcCovering': ('11', N_('REVESTIMIENTOS'), N_('REVESTIMIENTO')),
    'IfcFurnishingElement': ('12', N_('MOBILIARIO'), N_('MOBILIARIO')),
    'IfcFurniture': ('12', N_('MOBILIARIO'), N_('MOBILIARIO')),
    'IfcSanitaryTerminal': ('13', N_('APARATOS SANITARIOS'), N_('APARATO SANITARIO')),
    'IfcPipeSegment': ('14', N_('INSTALACIONES'), N_('TUBERÍA')),
    'IfcDuctSegment': ('14', N_('INSTALACIONES'), N_('DUCTO')),
    'IfcFlowSegment': ('14', N_('INSTALACIONES'), N_('TUBERÍA')),
    'IfcFlowFitting': ('14', N_('INSTALACIONES'), N_('ACCESORIO')),
    'IfcPipeFitting': ('14', N_('INSTALACIONES'), N_('ACCESORIO')),
    'IfcLightFixture': ('15', N_('INSTALACIONES ELÉCTRICAS'), N_('LUMINARIA')),
    'IfcOutlet': ('15', N_('INSTALACIONES ELÉCTRICAS'), N_('SALIDA ELÉCTRICA')),
}
_OTROS = ('99', N_('OTROS ELEMENTOS'), None)

SIN_CANTIDAD = 'sin_cantidad'
BRUTA = 'bruta'


# ── Modelo en memoria ────────────────────────────────────────────────────────

@dataclass
class ElementoBim:
    global_id: str
    clase: str
    nombre: str = ''
    tipo: str = ''
    piso: str = ''
    capa: str = ''
    material: str = ''
    cantidades: dict = field(default_factory=dict)   # nombre → (valor, unidad SI)
    metrado: tuple | None = None                     # (valor, unidad SI)
    medida: str = ''           # nombre de la cantidad que dio el metrado
    avisos: list = field(default_factory=list)       # SIN_CANTIDAD, BRUTA
    parte_de: str = ''         # global_id del conjunto que ya se mide entero
    conjunto: bool = False     # se mide por sus partes

    @property
    def se_presupuesta(self) -> bool:
        return not (self.conjunto or self.parte_de or self.clase == 'IfcSpace')


@dataclass
class ModeloBim:
    nombre: str = ''
    origen: str = ''
    huella: str = ''
    elementos: list = field(default_factory=list)
    avisos: list = field(default_factory=list)
    info: dict = field(default_factory=dict)


def _a_json(e: ElementoBim) -> str:
    return json.dumps(asdict(e), ensure_ascii=False)


def _de_json(s: str) -> ElementoBim:
    d = json.loads(s)
    d['cantidades'] = {k: tuple(v) for k, v in (d.get('cantidades') or {}).items()}
    d['metrado'] = tuple(d['metrado']) if d.get('metrado') else None
    conocidos = ElementoBim.__dataclass_fields__
    return ElementoBim(**{k: v for k, v in d.items() if k in conocidos})


def elegir_metrado(clase: str, cantidades: dict):
    """``(valor, unidad), nombre`` con la regla de la clase, o ``(None, '')``.

    Primero la unidad de presupuesto de la clase; si el modelo no la trae, el
    área o el volumen que sí traiga (con SU unidad). Una longitud no
    sustituye a un volumen: esa columna queda sin cantidad."""
    unidad, nombres = PREFERENCIA.get(clase, (None, ()))
    if unidad == 'und':
        return (1.0, 'und'), 'und'
    for n in nombres:
        c = cantidades.get(n)
        if c and c[1] == unidad:
            return (c[0], unidad), n
    if unidad == 'kg' and cantidades:
        return None, ''
    if clase == 'IfcSpace':
        return None, ''
    for u in ('m2', 'm3') if unidad == 'm2' else ('m3', 'm2'):
        for n in _POR_UNIDAD[u][:8]:
            c = cantidades.get(n)
            if c and c[1] == u:
                return (c[0], u), n
    return None, ''


def _medir(e: ElementoBim, con_vanos: bool = False) -> None:
    e.metrado, e.medida = elegir_metrado(e.clase, e.cantidades)
    if e.metrado is None:
        e.avisos.append(SIN_CANTIDAD)
    elif con_vanos and e.medida.startswith('Gross'):
        e.avisos.append(BRUTA)


# ── IFC ──────────────────────────────────────────────────────────────────────

_QTY = {'IFCQUANTITYLENGTH': ('LENGTHUNIT', 'm'), 'IFCQUANTITYAREA': ('AREAUNIT', 'm2'),
        'IFCQUANTITYVOLUME': ('VOLUMEUNIT', 'm3'), 'IFCQUANTITYWEIGHT': ('MASSUNIT', 'kg'),
        'IFCQUANTITYCOUNT': (None, 'und')}
_OTRAS = {
    'IFCPROJECT', 'IFCSITE', 'IFCBUILDING', 'IFCBUILDINGSTOREY', 'IFCUNITASSIGNMENT',
    'IFCSIUNIT', 'IFCCONVERSIONBASEDUNIT', 'IFCMEASUREWITHUNIT',
    'IFCRELCONTAINEDINSPATIALSTRUCTURE', 'IFCRELAGGREGATES', 'IFCRELNESTS',
    'IFCRELDEFINESBYPROPERTIES', 'IFCRELDEFINESBYTYPE', 'IFCRELASSOCIATESMATERIAL',
    'IFCRELVOIDSELEMENT', 'IFCPRESENTATIONLAYERASSIGNMENT', 'IFCPRESENTATIONLAYERWITHSTYLE',
    'IFCPRODUCTDEFINITIONSHAPE', 'IFCSHAPEREPRESENTATION', 'IFCELEMENTQUANTITY',
    'IFCPHYSICALCOMPLEXQUANTITY', 'IFCFACILITYPART', 'IFCBRIDGEPART', 'IFCROADPART',
    'IFCRAILWAYPART', 'IFCMARINEPART', 'IFCFACILITY', 'IFCBRIDGE', 'IFCROAD', 'IFCRAILWAY',
    'IFCMARINEFACILITY', 'IFCSPATIALZONE',
    'IFCMATERIAL', 'IFCMATERIALLIST', 'IFCMATERIALLAYER', 'IFCMATERIALLAYERSET',
    'IFCMATERIALLAYERSETUSAGE', 'IFCMATERIALPROFILE', 'IFCMATERIALPROFILESET',
    'IFCMATERIALPROFILESETUSAGE', 'IFCMATERIALPROFILESETUSAGETAPERING',
    'IFCMATERIALCONSTITUENT', 'IFCMATERIALCONSTITUENTSET',
}
_CONTENEDORES = {'IFCBUILDINGSTOREY', 'IFCFACILITYPART', 'IFCBRIDGEPART', 'IFCROADPART',
                 'IFCRAILWAYPART', 'IFCMARINEPART'}


def _txt(a, i) -> str:
    return step.texto(a[i]) if len(a) > i else ''


def leer_ifc(path) -> ModeloBim:
    """Lee un .ifc (IFC2x3 / IFC4 / IFC4x3) con las cantidades en SI."""
    with open(path, 'rb') as f:
        datos = f.read()
    if datos[:2] == b'PK':
        raise ValueError(tr("El archivo está comprimido (.ifczip): descomprímelo y elige el .ifc."))
    if b'ISO-10303-21' not in datos[:4096]:
        raise ValueError(tr("El archivo no es un IFC (STEP): le falta la cabecera ISO-10303-21."))
    ents: dict[int, tuple[str, bytes]] = {}
    for eid, t, raw in step.sentencias(datos):
        if (t in CLASES or t in _OTRAS or t in _QTY or t.endswith('TYPE')
                or t in ('IFCDOORSTYLE', 'IFCWINDOWSTYLE')):
            ents[eid] = (t, raw)
    por_tipo: dict[str, list[int]] = {}
    for eid, (t, _r) in ents.items():
        por_tipo.setdefault(t, []).append(eid)
    args: dict[int, list] = {}

    def A(eid):
        if eid not in args:
            args[eid] = step.argumentos(ents[eid][1])
        return args[eid]

    def de(*tipos):
        return [e for t in tipos for e in por_tipo.get(t, ())]

    m = ModeloBim(origen='ifc', huella=hashlib.sha256(datos).hexdigest())
    esq = re.search(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']*)'", datos[:8192])
    m.info = {'esquema': esq.group(1).decode('ascii', 'replace') if esq else '',
              'cliente': '', 'ubicacion': ''}
    asignacion = None
    for e in de('IFCPROJECT'):
        a = A(e)
        m.nombre = m.nombre or _txt(a, 2) or _txt(a, 5)
        if len(a) > 8 and asignacion is None:
            asignacion = step.ref(a[8])
    for e in de('IFCSITE'):
        m.info['ubicacion'] = m.info['ubicacion'] or _txt(A(e), 2)
    m.nombre = m.nombre or os.path.splitext(os.path.basename(str(path)))[0].replace('_', ' ')
    if asignacion is None:
        asignacion = next(iter(por_tipo.get('IFCUNITASSIGNMENT', ())), None)
    unidades = step.factores_proyecto(ents, asignacion)

    # ── Relaciones ───────────────────────────────────────────────────────
    contenido, padre, hijos = {}, {}, {}
    for e in de('IFCRELCONTAINEDINSPATIALSTRUCTURE'):
        a = A(e)
        if len(a) > 5:
            for x in step.refs(a[4]):
                contenido[x] = step.ref(a[5])
    for e in de('IFCRELAGGREGATES', 'IFCRELNESTS'):
        a = A(e)
        if len(a) > 5:
            p = step.ref(a[4])
            for x in step.refs(a[5]):
                padre[x] = p
                if ents[e][0] == 'IFCRELAGGREGATES':
                    hijos.setdefault(p, []).append(x)
    con_vanos = {step.ref(A(e)[4]) for e in de('IFCRELVOIDSELEMENT') if len(A(e)) > 4}
    tipo_de = {}
    for e in de('IFCRELDEFINESBYTYPE'):
        a = A(e)
        if len(a) > 5:
            for x in step.refs(a[4]):
                tipo_de[x] = step.ref(a[5])
    qsets = set(de('IFCELEMENTQUANTITY'))
    qs_de: dict[int, list[int]] = {}
    for e in de('IFCRELDEFINESBYPROPERTIES'):
        # Se miran antes los #id: la mayoría de estas relaciones son de
        # propiedades, no de cantidades, y no hace falta analizarlas.
        r = step.refs_crudas(ents[e][1])
        if not qsets.intersection(r):
            continue
        a = A(e)
        if len(a) > 5:
            q = [x for x in step.refs(a[5]) if x in qsets]
            for x in step.refs(a[4]):
                qs_de.setdefault(x, []).extend(q)

    # ── Cantidades ───────────────────────────────────────────────────────
    sin_unidad = set()
    cache_q: dict[int, dict] = {}

    def _cantidad(q, out):
        if q not in ents:
            return
        t, _ = ents[q]
        a = A(q)
        if t == 'IFCPHYSICALCOMPLEXQUANTITY':
            return      # capas de un material: no son cantidades del elemento
        clase_u, si = _QTY.get(t, (None, None))
        if si is None or len(a) < 4:
            return
        v = step.numero(a[3])
        if v is None or v <= 0:
            return
        if clase_u:
            propia = step.ref(a[2])
            f = step.factor_unidad(propia, ents) if propia else unidades.get(clase_u)
            if f is None:
                sin_unidad.add(clase_u)
                f = 1.0
            v *= f
        out.setdefault(_txt(a, 0), (v, si))

    def _qset(q):
        if q not in cache_q:
            a, d = A(q), {}
            for x in (step.refs(a[5]) if len(a) > 5 else ()):
                _cantidad(x, d)
            cache_q[q] = d
        return cache_q[q]

    def _orden(q):           # los conjuntos estándar mandan sobre los demás
        n = _txt(A(q), 2)
        return 0 if n.startswith('Qto_') else 1 if n == 'BaseQuantities' else 2

    def _juntar(lista):
        d = {}
        for q in sorted(dict.fromkeys(lista), key=_orden):
            for k, v in _qset(q).items():
                d.setdefault(k, v)
        return d

    cant_tipo: dict[int, dict] = {}

    def _del_tipo(t):
        if t not in cant_tipo:
            a = A(t)
            cant_tipo[t] = _juntar([x for x in (step.refs(a[5]) if len(a) > 5 else ())
                                    if x in qsets] + qs_de.get(t, []))
        return cant_tipo[t]

    # ── Materiales y capas ───────────────────────────────────────────────
    def _material(x, prof=0):
        if x not in ents or prof > 6:
            return []
        t, _ = ents[x]
        a = A(x)
        if t == 'IFCMATERIAL':
            return [_txt(a, 0)]
        out = []
        for y in (z for arg in a for z in step.refs(arg)):
            out += _material(y, prof + 1)
        return out

    mat_de, cache_m = {}, {}
    for e in de('IFCRELASSOCIATESMATERIAL'):
        a = A(e)
        if len(a) > 5:
            r = step.ref(a[5])
            if r not in cache_m:
                cache_m[r] = ' + '.join(dict.fromkeys(n for n in _material(r) if n))
            for x in step.refs(a[4]):
                mat_de[x] = cache_m[r]
    capa_rep: dict[int, str] = {}
    for e in de('IFCPRESENTATIONLAYERASSIGNMENT', 'IFCPRESENTATIONLAYERWITHSTYLE'):
        a = A(e)
        if len(a) > 2:
            for x in step.refs(a[2]):
                capa_rep.setdefault(x, _txt(a, 0))

    def _capa(shape):
        if not capa_rep or shape not in ents:
            return ''
        for r in step.refs_crudas(ents[shape][1]):
            if r in capa_rep:
                return capa_rep[r]
            if r in ents and ents[r][0] == 'IFCSHAPEREPRESENTATION':
                a = A(r)
                for x in (step.refs(a[3]) if len(a) > 3 else ()):
                    if x in capa_rep:
                        return capa_rep[x]
        return ''

    cache_piso: dict[int, str] = {}

    def _piso(x):
        visto, y = set(), x
        while y is not None and y not in visto:
            visto.add(y)
            if y in ents and ents[y][0] in _CONTENEDORES:
                if y not in cache_piso:
                    a = A(y)
                    cache_piso[y] = _txt(a, 2) or _txt(a, 7)
                return cache_piso[y]
            y = contenido.get(y, padre.get(y))
        return ''

    # ── Elementos ────────────────────────────────────────────────────────
    ids = [(e, t) for e, (t, _r) in ents.items() if t in CLASES]
    gid_de, dup, sin_gid = {}, 0, 0
    vistos = set()
    por_ent: dict[int, ElementoBim] = {}
    for eid, t in ids:
        a = A(eid)
        gid = _txt(a, 0)
        if not gid:
            sin_gid += 1
            continue
        if gid in vistos:
            dup += 1
            continue
        vistos.add(gid)
        gid_de[eid] = gid
        tt = tipo_de.get(eid)
        tt = tt if tt in ents else None
        cant = _juntar(qs_de.get(eid, ()))
        if tt is not None:
            for k, v in _del_tipo(tt).items():
                cant.setdefault(k, v)
        e = ElementoBim(
            gid, CLASES[t], _txt(a, 2),
            (_txt(A(tt), 2) if tt is not None else '') or _txt(a, 4),
            _piso(eid), _capa(step.ref(a[6]) if len(a) > 6 else None),
            mat_de.get(eid) or mat_de.get(tt, ''), cant)
        _medir(e, eid in con_vanos)
        por_ent[eid] = e
        m.elementos.append(e)

    # ── Conjuntos: se mide el conjunto o sus partes, nunca los dos ───────
    for p, hs in hijos.items():
        ep = por_ent.get(p)
        partes = [por_ent[h] for h in hs if h in por_ent]
        if ep is None or not partes:
            continue
        medido = ep.metrado is not None and ep.clase != 'IfcElementAssembly'
        if medido:
            for x in partes:
                x.parte_de = ep.global_id
                if SIN_CANTIDAD in x.avisos:
                    x.avisos.remove(SIN_CANTIDAD)
        else:
            ep.conjunto = True
            ep.metrado, ep.medida, ep.avisos = None, '', []
    # Partes de partes (muro → capas → piezas)
    for h, p in padre.items():
        if h in por_ent and p in por_ent and por_ent[p].parte_de:
            por_ent[h].parte_de = por_ent[p].parte_de

    # ── Avisos ───────────────────────────────────────────────────────────
    if sin_unidad:
        m.avisos.append(tr("El archivo no declara la unidad de: {que}. Se leyó en metros "
                           "(m, m2, m3, kg).").format(que=', '.join(sorted(sin_unidad))))
    if dup:
        m.avisos.append(tr("{n} elemento(s) con GlobalId repetido: se leyó solo el primero.").format(n=dup))
    if sin_gid:
        m.avisos.append(tr("{n} elemento(s) sin GlobalId: no se leyeron.").format(n=sin_gid))
    _avisos_comunes(m)
    return m


def _avisos_comunes(m: ModeloBim) -> None:
    n = sum(1 for e in m.elementos if SIN_CANTIDAD in e.avisos and e.se_presupuesta)
    if n:
        m.avisos.append(tr("{n} elemento(s) sin cantidad en el modelo: no se les asigna metrado.").format(n=n))
    n = sum(1 for e in m.elementos if BRUTA in e.avisos and e.se_presupuesta)
    if n:
        m.avisos.append(tr("{n} elemento(s) con vanos solo traen la cantidad BRUTA: no descuenta los vanos.").format(n=n))
    n = sum(1 for e in m.elementos if e.conjunto)
    if n:
        m.avisos.append(tr("{n} conjunto(s) se miden por sus partes.").format(n=n))
    n = sum(1 for e in m.elementos if e.parte_de)
    if n:
        m.avisos.append(tr("{n} pieza(s) no se miden aparte: su conjunto ya trae la cantidad.").format(n=n))


# ── Takeoff de IngeTrazo ─────────────────────────────────────────────────────

_UNIDADES_SI = ('m', 'm2', 'm3', 'kg', 'und')


def _par(x):
    """{'value','unit'} → (valor, unidad) o None si no es una cantidad válida."""
    if not isinstance(x, dict):
        return None
    v, u = x.get('value'), x.get('unit')
    if isinstance(v, bool) or not isinstance(v, (int, float)) or u not in _UNIDADES_SI:
        return None
    return (float(v), u) if 0 < v < float('inf') else None


def leer_takeoff(datos: dict) -> ModeloBim:
    """JSON «inge-takeoff» v1 (ver CONTRATO) → ModeloBim."""
    if not isinstance(datos, dict) or datos.get('schema') != 'inge-takeoff':
        raise ValueError(tr("No es un metrado de IngeTrazo (inge-takeoff)."))
    if datos.get('version') != 1:
        raise ValueError(tr("Versión de metrado no admitida: {v}. Actualiza IngePresupuestos.")
                         .format(v=datos.get('version')))
    src = datos.get('source') or {}
    doc = str(src.get('document') or '')
    m = ModeloBim(nombre=os.path.splitext(os.path.basename(doc))[0] or str(src.get('app') or ''),
                  origen=str(src.get('app') or 'IngeTrazo'),
                  info={'documento': doc, 'namespace': str(src.get('namespace') or ''),
                        'cliente': '', 'ubicacion': ''})
    vistos, dup, sin_gid = set(), 0, 0
    for d in datos.get('elements') or []:
        gid = str(d.get('global_id') or '').strip()
        if not gid:
            sin_gid += 1
            continue
        if gid in vistos:
            dup += 1
            continue
        vistos.add(gid)
        cant = {str(k): p for k, v in (d.get('quantities') or {}).items()
                if (p := _par(v)) is not None}
        e = ElementoBim(gid, str(d.get('ifc_class') or ''), str(d.get('name') or ''),
                        str(d.get('type') or ''), str(d.get('storey') or ''),
                        str(d.get('layer') or ''), str(d.get('material') or ''), cant)
        # IngeTrazo ya aplicó su regla de clase: su metrado manda; null = no
        # se puede medir.
        e.metrado = _par(d.get('metrado'))
        if e.metrado is None:
            e.avisos.append(SIN_CANTIDAD)
        m.elementos.append(e)
    m.huella = hashlib.sha256(json.dumps(
        sorted(([e.global_id, e.clase, e.nombre, e.tipo, e.piso, e.capa, e.material,
                 sorted(e.cantidades.items()), e.metrado] for e in m.elementos)),
        ensure_ascii=False).encode()).hexdigest()
    if dup:
        m.avisos.append(tr("{n} elemento(s) con GlobalId repetido: se leyó solo el primero.").format(n=dup))
    if sin_gid:
        m.avisos.append(tr("{n} elemento(s) sin GlobalId: no se leyeron.").format(n=sin_gid))
    _avisos_comunes(m)
    return m


# ── Propuesta de partidas ────────────────────────────────────────────────────

def _base(clase: str) -> str:
    """IfcWallStandardCase → IfcWall (para agrupar y nombrar)."""
    return re.sub(r'(StandardCase|ElementedCase)$', '', clase)


def nombre_clase(clase: str) -> str:
    g = _GRUPOS.get(_base(clase))
    return tr(g[2]) if g else (clase[3:] if clase.startswith('Ifc') else clase).upper()


def proponer_partidas(modelo) -> list[dict]:
    """Agrupa por clase + tipo + unidad. Cada partida propuesta::

        {'grupo','grupo_nombre','item','descripcion','unidad','metrado',
         'clase','tipo','global_ids': [...], 'sin_cantidad': [...]}

    Nunca mezcla unidades. `global_ids` son los que tienen cantidad;
    `sin_cantidad` los del mismo tipo que el modelo no mide (no suman)."""
    elementos_ = modelo.elementos if isinstance(modelo, ModeloBim) else list(modelo)
    grupos: dict[tuple, dict] = {}
    sueltos: dict[tuple, list] = {}
    for e in elementos_:
        if not e.se_presupuesta:
            continue
        c = _base(e.clase)
        if e.metrado is None:
            sueltos.setdefault((c, e.tipo), []).append(e)
            continue
        g = grupos.setdefault((c, e.tipo, e.metrado[1]), {'els': [], 'sin': []})
        g['els'].append(e)
    for (c, t), els in sueltos.items():
        u = PREFERENCIA.get(c, ('', ()))[0] or ''
        destino = next((g for k, g in grupos.items() if k[:2] == (c, t) and (not u or k[2] == u)), None)
        if destino is None:
            destino = grupos.setdefault((c, t, u), {'els': [], 'sin': []})
        destino['sin'] += els
    orden = sorted(grupos.items(), key=lambda kv: (
        _GRUPOS.get(kv[0][0], _OTROS)[0], kv[0][0], kv[0][1], kv[0][2]))
    out, cont = [], {}
    for (c, t, u), g in orden:
        cod, titulo, _n = _GRUPOS.get(c, _OTROS)
        cont[cod] = cont.get(cod, 0) + 1
        todos = g['els'] + g['sin']
        nombres = {e.nombre for e in todos if e.nombre}
        detalle = t or (nombres.pop() if len(nombres) == 1 else '')
        desc = nombre_clase(c) + (f" — {detalle}" if detalle else '')
        out.append({
            'grupo': cod, 'grupo_nombre': tr(titulo), 'item': f"{cod}.{cont[cod]:02d}",
            'descripcion': desc, 'unidad': u,
            'metrado': round(sum(e.metrado[0] for e in g['els']), 6),
            'clase': c, 'tipo': t,
            'global_ids': [e.global_id for e in g['els']],
            'sin_cantidad': [e.global_id for e in g['sin']]})
    return out


def con_titulos(propuestas: list[dict]) -> list[dict]:
    """Propuestas → lista para `guardar_importacion`, con un título por grupo."""
    out, vistos = [], set()
    for p in propuestas:
        if p['grupo'] not in vistos:
            vistos.add(p['grupo'])
            out.append({'item': p['grupo'], 'descripcion': p['grupo_nombre'], 'unidad': '',
                        'metrado': 0, 'precio_unitario': 0, 'nivel': 1, 'es_titulo': 1})
        out.append({'item': p['item'], 'descripcion': p['descripcion'], 'unidad': p['unidad'],
                    'metrado': p['metrado'], 'precio_unitario': 0, 'nivel': 2, 'es_titulo': 0})
    return out


# ── Base de datos: modelos y vínculos ────────────────────────────────────────

TABLAS_SQL = '''
    -- BIM: un modelo importado en un proyecto, la foto de sus elementos y sus
    -- vínculos. Cada vínculo es UNA fila de metrados_detalle: borrar la fila
    -- deshace el vínculo. `valor`/`unidad` = lo último que el modelo escribió
    -- en esa fila; si la fila ya no dice eso, la editó el usuario.
    CREATE TABLE IF NOT EXISTS bim_modelos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proyecto_id INTEGER NOT NULL REFERENCES proyectos(id) ON DELETE CASCADE,
        nombre TEXT DEFAULT '',
        origen TEXT DEFAULT '',
        ruta TEXT DEFAULT '',
        huella TEXT DEFAULT '',
        importado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS bim_elementos (
        modelo_id INTEGER NOT NULL REFERENCES bim_modelos(id) ON DELETE CASCADE,
        global_id TEXT NOT NULL,
        datos TEXT NOT NULL,
        PRIMARY KEY (modelo_id, global_id)
    );
    CREATE TABLE IF NOT EXISTS bim_vinculos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        partida_id INTEGER NOT NULL REFERENCES partidas(id) ON DELETE CASCADE,
        modelo_id INTEGER NOT NULL REFERENCES bim_modelos(id) ON DELETE CASCADE,
        global_id TEXT NOT NULL,
        medida TEXT DEFAULT 'metrado',
        factor REAL DEFAULT 1,
        metrado_detalle_id INTEGER REFERENCES metrados_detalle(id) ON DELETE CASCADE,
        valor REAL,
        unidad TEXT DEFAULT '',
        UNIQUE (partida_id, modelo_id, global_id)
    );
    CREATE INDEX IF NOT EXISTS idx_bim_vinc_partida ON bim_vinculos(partida_id);
    CREATE INDEX IF NOT EXISTS idx_bim_vinc_elem    ON bim_vinculos(modelo_id, global_id);
    CREATE INDEX IF NOT EXISTS idx_bim_vinc_fila    ON bim_vinculos(metrado_detalle_id);
'''


class MetradoManual(ValueError):
    """La partida tiene un metrado escrito a mano que se perdería."""


def _db():
    from core.database import get_db
    return get_db()


class _tx:
    """Conexión con todo-o-nada; si se le pasa una abierta, no la cierra."""

    def __init__(self, conn=None):
        self._propia = conn is None
        self.conn = conn or _db()

    def __enter__(self):
        return self.conn

    def __exit__(self, tipo, *_):
        if self._propia:
            self.conn.rollback() if tipo else self.conn.commit()
            self.conn.close()
        return False


def _guardar_elementos(conn, modelo_id, elementos_) -> None:
    conn.executemany("INSERT INTO bim_elementos (modelo_id, global_id, datos) VALUES (?,?,?)",
                     ((modelo_id, e.global_id, _a_json(e)) for e in elementos_))


def registrar_modelo(pid: int, modelo: ModeloBim, ruta: str = '', conn=None) -> int:
    """Guarda el modelo en el proyecto. El mismo archivo (misma huella) no se
    duplica: devuelve el que ya estaba."""
    with _tx(conn) as c:
        if modelo.huella:
            r = c.execute("SELECT id FROM bim_modelos WHERE proyecto_id=? AND huella=?",
                          (pid, modelo.huella)).fetchone()
            if r:
                if ruta:
                    c.execute("UPDATE bim_modelos SET ruta=? WHERE id=?", (str(ruta), r['id']))
                return r['id']
        mid = c.execute(
            "INSERT INTO bim_modelos (proyecto_id, nombre, origen, ruta, huella) VALUES (?,?,?,?,?)",
            (pid, modelo.nombre, modelo.origen, str(ruta or ''), modelo.huella)).lastrowid
        _guardar_elementos(c, mid, modelo.elementos)
        return mid


def eliminar_modelo(modelo_id: int, conn=None) -> None:
    """Quita el modelo y sus vínculos. Los metrados que escribió se quedan,
    como filas normales de la planilla."""
    with _tx(conn) as c:
        c.execute("DELETE FROM bim_modelos WHERE id=?", (modelo_id,))


def modelos(pid: int, conn=None) -> list[dict]:
    with _tx(conn) as c:
        return [dict(r) for r in c.execute(
            "SELECT m.*, (SELECT COUNT(*) FROM bim_elementos e WHERE e.modelo_id=m.id) AS n_elementos, "
            "(SELECT COUNT(*) FROM bim_vinculos v WHERE v.modelo_id=m.id) AS n_vinculos "
            "FROM bim_modelos m WHERE proyecto_id=? ORDER BY id", (pid,))]


def elementos(modelo_id: int, conn=None) -> list[ElementoBim]:
    with _tx(conn) as c:
        return [_de_json(r[0]) for r in c.execute(
            "SELECT datos FROM bim_elementos WHERE modelo_id=? ORDER BY rowid", (modelo_id,))]


def vinculos_partida(partida_id: int, conn=None) -> list[dict]:
    """Vínculos de una partida con su elemento (None si ya no está en el
    modelo) y `editada` (la fila de metrado fue retocada a mano)."""
    with _tx(conn) as c:
        out = []
        for r in c.execute(
                "SELECT v.*, e.datos, md.n_estructuras, md.n_elementos, md.area, md.largo, "
                "md.ancho, md.alto, md.parcial FROM bim_vinculos v "
                "LEFT JOIN bim_elementos e ON e.modelo_id=v.modelo_id AND e.global_id=v.global_id "
                "LEFT JOIN metrados_detalle md ON md.id=v.metrado_detalle_id "
                "WHERE v.partida_id=? ORDER BY md.orden, v.id", (partida_id,)).fetchall():
            d = {k: r[k] for k in ('id', 'partida_id', 'modelo_id', 'global_id', 'medida', 'factor',
                                   'metrado_detalle_id', 'valor', 'unidad', 'parcial')}
            d['elemento'] = _de_json(r['datos']) if r['datos'] else None
            d['editada'] = _editada(r)
            out.append(d)
        return out


def partidas_de(modelo_id: int, global_id: str, conn=None) -> list[int]:
    with _tx(conn) as c:
        return [r[0] for r in c.execute(
            "SELECT DISTINCT partida_id FROM bim_vinculos WHERE modelo_id=? AND global_id=?",
            (modelo_id, global_id))]


# ── Vincular ─────────────────────────────────────────────────────────────────

_ALIAS_UNIDAD = {'m²': 'm2', 'mt2': 'm2', 'm³': 'm3', 'mt3': 'm3', 'ml': 'm', 'mt': 'm',
                 'mts': 'm', 'kgs': 'kg', 'u': 'und', 'un': 'und', 'ud': 'und', 'uds': 'und',
                 'unid': 'und', 'uni': 'und', 'unidad': 'und', 'pza': 'und', 'pz': 'und',
                 'pieza': 'und', 'pto': 'und', 'jgo': 'und'}


def unidad_si(unidad) -> str:
    """«M²» → m2, «ml» → m, «pza» → und; '' si no es una unidad medible."""
    u = (unidad or '').strip().lower().rstrip('.')
    u = _ALIAS_UNIDAD.get(u, u)
    return u if u in _UNIDADES_SI else ''


def medir(e: ElementoBim, medida: str | None, unidad: str = ''):
    """``(valor, unidad, medida)`` de un elemento, o None si no la trae."""
    if medida == 'metrado' or (not medida and e.metrado and e.metrado[1] == unidad):
        return (*e.metrado, 'metrado') if e.metrado else None
    if medida == 'und' or (not medida and unidad == 'und'):
        return 1.0, 'und', 'und'
    if medida:
        c = e.cantidades.get(medida)
        return (c[0], c[1], medida) if c else None
    for n in _POR_UNIDAD.get(unidad, ()):
        c = e.cantidades.get(n)
        if c and c[1] == unidad:
            return c[0], c[1], n
    return None


def _fila(valor: float, unidad: str, factor: float) -> dict:
    """Dimensiones de la fila de planilla. El factor va en n_estructuras; m en
    largo, m2 en área; m3, kg y und (no tienen columna) en n_elementos."""
    from core.database import _rn, get_decimales_metrado
    col = {'m': 'largo', 'm2': 'area'}.get(unidad, 'n_elementos')
    v = round(valor, 6)
    f = None if factor == 1 else float(factor)
    return {'n_estructuras': f, 'n_elementos': None, 'area': None, 'largo': None,
            'ancho': None, 'alto': None, col: v,
            'parcial': _rn(v * (1.0 if f is None else f), get_decimales_metrado())}


def _editada(r) -> bool:
    """¿La fila dejó de decir lo que escribió el modelo? La hoja de metrados
    reescribe las dimensiones a 2 decimales: eso no cuenta como edición."""
    if r['valor'] is None or r['parcial'] is None:
        return False
    p, hay = 1.0, False
    for k in ('n_estructuras', 'n_elementos', 'area', 'largo', 'ancho', 'alto'):
        if r[k] is not None:
            p, hay = p * r[k], True
    f = r['factor'] if r['factor'] is not None else 1.0
    esperado = r['valor'] * f
    tol = 0.0051 * max(1.0, abs(f), abs(r['valor']) if f != 1 else 0) + 1e-9 * abs(esperado)
    return not hay or abs(p - esperado) > tol


def _descripcion(e: ElementoBim) -> str:
    t = e.nombre or e.tipo or nombre_clase(e.clase)
    return f"{t} · {e.piso}" if e.piso else t


def _recalcular(conn, partida_id: int) -> float:
    from core.database import _rn, get_decimales_metrado
    t = conn.execute("SELECT COALESCE(SUM(parcial),0) FROM metrados_detalle WHERE partida_id=?",
                     (partida_id,)).fetchone()[0]
    t = _rn(t, get_decimales_metrado())
    conn.execute("UPDATE partidas SET metrado=? WHERE id=?", (t, partida_id))
    return t


_INS_FILA = ("INSERT INTO metrados_detalle (partida_id, orden, descripcion, n_estructuras, "
             "n_elementos, area, largo, ancho, alto, parcial) VALUES (?,?,?,?,?,?,?,?,?,?)")


def _insertar(conn, partida_id, modelo_id, e, valor, unidad, medida, factor, orden):
    f = _fila(valor, unidad, factor)
    fid = conn.execute(_INS_FILA, (
        partida_id, orden, _descripcion(e), f['n_estructuras'], f['n_elementos'], f['area'],
        f['largo'], f['ancho'], f['alto'], f['parcial'])).lastrowid
    conn.execute(
        "INSERT INTO bim_vinculos (partida_id, modelo_id, global_id, medida, factor, "
        "metrado_detalle_id, valor, unidad) VALUES (?,?,?,?,?,?,?,?)",
        (partida_id, modelo_id, e.global_id, medida, float(factor), fid, round(valor, 6), unidad))


def _sig_orden(conn, partida_id) -> int:
    return (conn.execute("SELECT COALESCE(MAX(orden),0) FROM metrados_detalle WHERE partida_id=?",
                         (partida_id,)).fetchone()[0] or 0) + 1


def vincular(partida_id: int, modelo_id: int, global_ids, medida: str | None = None,
             factor: float = 1.0, *, reemplazar_manual: bool = False, conn=None) -> dict:
    """Cuelga elementos de una partida: una fila de planilla por elemento.

    `medida`: nombre de la cantidad («NetSideArea», «Length»…), «metrado»,
    «und» o None = la que corresponde a la unidad de la partida. Con factor 1
    la unidad debe coincidir con la de la partida.

    Devuelve ``{'vinculados': n, 'omitidos': [(global_id, motivo)],
    'metrado': total}``. Si la partida tiene un metrado escrito a mano (sin
    planilla) lanza `MetradoManual`, salvo `reemplazar_manual=True`."""
    factor = float(factor)
    if not (factor == factor and abs(factor) != float('inf')) or factor == 0:
        raise ValueError(tr("El factor debe ser un número distinto de cero."))
    with _tx(conn) as c:
        p = c.execute("SELECT * FROM partidas WHERE id=?", (partida_id,)).fetchone()
        m = c.execute("SELECT proyecto_id FROM bim_modelos WHERE id=?", (modelo_id,)).fetchone()
        if not p or p['es_titulo']:
            raise ValueError(tr("Elige una partida (no un título)."))
        if not m or m['proyecto_id'] != p['proyecto_id']:
            raise ValueError(tr("El modelo no es de este proyecto."))
        if c.execute("SELECT 1 FROM acero_detalle WHERE partida_id=? LIMIT 1", (partida_id,)).fetchone():
            raise MetradoManual(tr("La partida tiene una planilla de acero: no se mezcla con el modelo."))
        filas = c.execute("SELECT COUNT(*) FROM metrados_detalle WHERE partida_id=?",
                          (partida_id,)).fetchone()[0]
        if not filas and (p['metrado'] or 0) and not reemplazar_manual:
            raise MetradoManual(tr("La partida «{p}» tiene un metrado escrito a mano ({m}).").format(
                p=p['descripcion'], m=p['metrado']))
        up = unidad_si(p['unidad'])
        ya = {r[0] for r in c.execute(
            "SELECT global_id FROM bim_vinculos WHERE partida_id=? AND modelo_id=?",
            (partida_id, modelo_id))}
        gids = list(dict.fromkeys(global_ids))
        els = {}
        for i in range(0, len(gids), 500):
            lote = gids[i:i + 500]
            for r in c.execute(f"SELECT global_id, datos FROM bim_elementos WHERE modelo_id=? AND "
                               f"global_id IN ({','.join('?' * len(lote))})", (modelo_id, *lote)):
                els[r[0]] = _de_json(r[1])
        orden, n, omit = _sig_orden(c, partida_id), 0, []
        for g in gids:
            e = els.get(g)
            if e is None:
                omit.append((g, tr("no está en el modelo")))
                continue
            if g in ya:
                omit.append((g, tr("ya estaba vinculado a esta partida")))
                continue
            if not medida and not up:
                omit.append((g, tr("elige la medida: la unidad de la partida no es m, m2, m3, kg ni und")))
                continue
            x = medir(e, medida, up)
            if x is None:
                omit.append((g, tr("el modelo no trae esa cantidad")))
                continue
            if up and x[1] != up and factor == 1:
                omit.append((g, tr("la cantidad está en {a} y la partida en {b}").format(a=x[1], b=up)))
                continue
            _insertar(c, partida_id, modelo_id, e, *x, factor, orden)
            orden, n = orden + 1, n + 1
        total = _recalcular(c, partida_id) if n else (p['metrado'] or 0)
        return {'vinculados': n, 'omitidos': omit, 'metrado': total}


def desvincular(partida_id: int, modelo_id: int, global_ids=None, conn=None) -> int:
    """Deshace vínculos (todos los de ese modelo si `global_ids` es None) y
    borra sus filas de planilla. Una fila editada a mano se conserva."""
    with _tx(conn) as c:
        gids = None if global_ids is None else set(global_ids)
        n = 0
        for v in vinculos_partida(partida_id, c):
            if v['modelo_id'] != modelo_id or (gids is not None and v['global_id'] not in gids):
                continue
            c.execute("DELETE FROM bim_vinculos WHERE id=?", (v['id'],))
            if not v['editada']:
                c.execute("DELETE FROM metrados_detalle WHERE id=?", (v['metrado_detalle_id'],))
            n += 1
        if n:
            _recalcular(c, partida_id)
        return n


# ── Actualizar ───────────────────────────────────────────────────────────────

def _cambio(a: ElementoBim, b: ElementoBim) -> list[str]:
    """Qué cambió de verdad: clase o cantidades. Nombre, tipo, piso, capa y
    material dependen de por dónde llegó el modelo (IFC o takeoff)."""
    out = [] if a.clase == b.clase else ['clase']
    ca, cb = dict(a.cantidades), dict(b.cantidades)
    ca['metrado'], cb['metrado'] = a.metrado, b.metrado
    for k in sorted(set(ca) | set(cb)):
        x, y = ca.get(k), cb.get(k)
        if (x is None) != (y is None) or (x and (
                x[1] != y[1] or abs(x[0] - y[0]) > 1e-6 * max(1.0, abs(x[0])))):
            out.append(k)
    return out


def _plan(conn, modelo_id: int, nuevos: dict) -> dict:
    """Lo que pasaría con cada vínculo: {partida_id: {'act': [(v, valor)],
    'borrar': [v], 'editadas': [v], 'sin_medida': [v]}}."""
    plan: dict[int, dict] = {}
    for (pid_,) in conn.execute("SELECT DISTINCT partida_id FROM bim_vinculos WHERE modelo_id=?",
                                (modelo_id,)).fetchall():
        d = {'act': [], 'borrar': [], 'editadas': [], 'sin_medida': []}
        for v in vinculos_partida(pid_, conn):
            if v['modelo_id'] != modelo_id:
                continue
            e = nuevos.get(v['global_id'])
            x = medir(e, v['medida']) if e is not None else None
            if e is not None and (x is None or x[1] != v['unidad']):
                d['sin_medida'].append(v)
            elif e is None or abs(x[0] - v['valor']) > 1e-6 * max(1.0, abs(v['valor'])):
                if v['editada']:
                    d['editadas'].append(v)
                elif e is None:
                    d['borrar'].append(v)
                else:
                    d['act'].append((v, x[0]))
        if any(d.values()):
            plan[pid_] = d
    return plan


def _despues(conn, partida_id, d) -> float:
    from core.database import _rn, get_decimales_metrado
    filas = {r['id']: r['parcial'] or 0 for r in conn.execute(
        "SELECT id, parcial FROM metrados_detalle WHERE partida_id=?", (partida_id,))}
    for v in d['borrar']:
        filas.pop(v['metrado_detalle_id'], None)
    for v, val in d['act']:
        filas[v['metrado_detalle_id']] = _fila(val, v['unidad'], v['factor'])['parcial']
    return _rn(sum(filas.values()), get_decimales_metrado())


def diferencias(modelo_id: int, modelo_nuevo: ModeloBim, conn=None) -> dict:
    """Compara el modelo guardado con otra versión. No escribe nada.

    ``nuevos`` / ``borrados``: list[ElementoBim]; ``cambiados``: list de
    ``{'global_id','antes','despues','campos'}``; ``iguales``: list de
    global_id; ``partidas``: ``{'partida_id','item','descripcion','unidad',
    'antes','despues','actualizar','borrar','editadas','sin_medida'}`` (los
    cuatro últimos son cuentas de filas); ``sugerencias``: {global_id nuevo:
    partida_id} cuando todos sus iguales (clase y tipo) están en esa partida."""
    with _tx(conn) as c:
        viejos = {e.global_id: e for e in elementos(modelo_id, c)}
        nuevos = {e.global_id: e for e in modelo_nuevo.elementos}
        out = {'nuevos': [e for g, e in nuevos.items() if g not in viejos],
               'borrados': [e for g, e in viejos.items() if g not in nuevos],
               'cambiados': [], 'iguales': [], 'partidas': [], 'sugerencias': {}}
        for g, a in viejos.items():
            if g in nuevos:
                campos = _cambio(a, nuevos[g])
                if campos:
                    out['cambiados'].append({'global_id': g, 'antes': a, 'despues': nuevos[g],
                                             'campos': campos})
                else:
                    out['iguales'].append(g)
        for pid_, d in _plan(c, modelo_id, nuevos).items():
            p = c.execute("SELECT item, descripcion, unidad, metrado FROM partidas WHERE id=?",
                          (pid_,)).fetchone()
            out['partidas'].append({
                'partida_id': pid_, 'item': p['item'], 'descripcion': p['descripcion'],
                'unidad': p['unidad'], 'antes': p['metrado'] or 0.0,
                'despues': _despues(c, pid_, d), 'actualizar': len(d['act']),
                'borrar': len(d['borrar']), 'editadas': len(d['editadas']),
                'sin_medida': len(d['sin_medida'])})
        out['partidas'].sort(key=lambda x: x['item'] or '')
        # ¿A qué partida van sus iguales? Solo si es una y la misma para todos.
        # Sin tipo, el nombre distingue («Columna C-1» de «Columna C-2»).
        clave = lambda e: (_base(e.clase), e.tipo or e.nombre)
        destino: dict = {}
        for r in c.execute("SELECT global_id, partida_id FROM bim_vinculos WHERE modelo_id=?",
                           (modelo_id,)):
            e = viejos.get(r[0])
            if e is not None:
                destino.setdefault(clave(e), set()).add(r[1])
        for e in out['nuevos']:
            d = destino.get(clave(e))
            if d and len(d) == 1:
                out['sugerencias'][e.global_id] = next(iter(d))
        return out


def aplicar(modelo_id: int, modelo_nuevo: ModeloBim, partidas=None, *, nuevos=None,
            ruta: str | None = None, conn=None) -> dict:
    """Pone el modelo al día en UNA transacción.

    `partidas`: ids de las partidas que se actualizan (None = todas). Las
    demás conservan sus filas y vuelven a salir en la próxima diferencia.
    `nuevos`: {global_id: partida_id} de elementos nuevos que se vinculan, con
    la medida y el factor de sus hermanos en esa partida.

    Las filas escritas o editadas a mano no se tocan. Devuelve
    ``{'actualizadas','borradas','vinculados','editadas','omitidos'}``."""
    elegidas = None if partidas is None else set(partidas)
    res = {'actualizadas': 0, 'borradas': 0, 'vinculados': 0, 'editadas': 0, 'omitidos': []}
    with _tx(conn) as c:
        mapa = {e.global_id: e for e in modelo_nuevo.elementos}
        for pid_, d in _plan(c, modelo_id, mapa).items():
            if elegidas is not None and pid_ not in elegidas:
                continue
            res['editadas'] += len(d['editadas'])
            for v, val in d['act']:
                f = _fila(val, v['unidad'], v['factor'])
                c.execute("UPDATE metrados_detalle SET n_estructuras=:n_estructuras, "
                          "n_elementos=:n_elementos, area=:area, largo=:largo, ancho=:ancho, "
                          "alto=:alto, parcial=:parcial WHERE id=:id",
                          {**f, 'id': v['metrado_detalle_id']})
                c.execute("UPDATE bim_vinculos SET valor=? WHERE id=?", (round(val, 6), v['id']))
                res['actualizadas'] += 1
            for v in d['borrar']:
                c.execute("DELETE FROM bim_vinculos WHERE id=?", (v['id'],))
                c.execute("DELETE FROM metrados_detalle WHERE id=?", (v['metrado_detalle_id'],))
                res['borradas'] += 1
            if d['act'] or d['borrar']:
                _recalcular(c, pid_)
        # Foto nueva. Lo que una vía no trae (piso, tipo…) no borra lo sabido.
        viejos = {e.global_id: e for e in elementos(modelo_id, c)}
        for g, e in mapa.items():
            a = viejos.get(g)
            if a is not None:
                for k in ('nombre', 'tipo', 'piso', 'capa', 'material'):
                    if not getattr(e, k):
                        setattr(e, k, getattr(a, k))
        c.execute("DELETE FROM bim_elementos WHERE modelo_id=?", (modelo_id,))
        _guardar_elementos(c, modelo_id, mapa.values())
        c.execute("UPDATE bim_modelos SET huella=?, importado_en=CURRENT_TIMESTAMP, "
                  "ruta=COALESCE(?, ruta), origen=? WHERE id=?",
                  (modelo_nuevo.huella, ruta, modelo_nuevo.origen, modelo_id))
        por_partida: dict[int, list] = {}
        for g, pid_ in (nuevos or {}).items():
            por_partida.setdefault(pid_, []).append(g)
        for pid_, gids in por_partida.items():
            h = c.execute("SELECT medida, factor FROM bim_vinculos WHERE partida_id=? AND modelo_id=? "
                          "ORDER BY id LIMIT 1", (pid_, modelo_id)).fetchone()
            r = vincular(pid_, modelo_id, gids, h['medida'] if h else None,
                         h['factor'] if h else 1.0, conn=c)
            res['vinculados'] += r['vinculados']
            res['omitidos'] += r['omitidos']
    return res


# ── Crear partidas desde el modelo ───────────────────────────────────────────

def _id_por_item(conn, pid) -> dict:
    return {r['item']: r['id'] for r in conn.execute(
        "SELECT id, item FROM partidas WHERE proyecto_id=?", (pid,))}


def crear_proyecto(modelo: ModeloBim, ruta: str = '', propuestas=None) -> int:
    """Proyecto nuevo con las partidas propuestas, ya vinculadas."""
    from core.importer import guardar_importacion
    props = proponer_partidas(modelo) if propuestas is None else propuestas
    pid = guardar_importacion({'nombre': modelo.nombre, **{k: modelo.info.get(k, '') for k in
                                                           ('cliente', 'ubicacion')}},
                              [{**p, 'metrado': 0} for p in con_titulos(props)])
    with _tx() as c:
        mid = registrar_modelo(pid, modelo, ruta, c)
        ids = _id_por_item(c, pid)
        for p in props:
            if p['global_ids']:
                vincular(ids[p['item']], mid, p['global_ids'], 'metrado', conn=c)
    return pid


def anadir_partidas(pid: int, modelo: ModeloBim, ruta: str = '', propuestas=None,
                    titulo: str | None = None, sub_id: int | None = None) -> tuple[int, list[int]]:
    """Agrega al final del sub-presupuesto un título con las partidas
    propuestas, vinculadas. No toca las que ya había. ``(modelo_id, ids)``."""
    props = proponer_partidas(modelo) if propuestas is None else propuestas
    with _tx() as c:
        mid = registrar_modelo(pid, modelo, ruta, c)
        mx = 0
        for (it,) in c.execute("SELECT item FROM partidas WHERE proyecto_id=? AND "
                               "sub_presupuesto_id IS ?", (pid, sub_id)):
            cab = str(it or '').split('.')[0]
            mx = max(mx, int(cab)) if cab.isdigit() else mx
        raiz = f"{mx + 1:02d}"
        ins = ("INSERT INTO partidas (proyecto_id, sub_presupuesto_id, item, descripcion, unidad, "
               "metrado, precio_unitario, nivel, es_titulo) VALUES (?,?,?,?,?,0,0,?,?)")
        c.execute(ins, (pid, sub_id, raiz, titulo or modelo.nombre, '', 1, 1))
        grupos, cont, ids = {}, {}, []
        for p in props:
            if p['grupo'] not in grupos:
                grupos[p['grupo']] = f"{raiz}.{len(grupos) + 1:02d}"
                c.execute(ins, (pid, sub_id, grupos[p['grupo']], p['grupo_nombre'], '', 2, 1))
            cont[p['grupo']] = cont.get(p['grupo'], 0) + 1
            part = c.execute(ins, (pid, sub_id, f"{grupos[p['grupo']]}.{cont[p['grupo']]:02d}",
                                   p['descripcion'], p['unidad'], 3, 0)).lastrowid
            ids.append(part)
            if p['global_ids']:
                vincular(part, mid, p['global_ids'], 'metrado', conn=c)
    return mid, ids


def sugerir_biblioteca(descripcion: str, unidad: str, limite: int = 5, conn=None) -> list[dict]:
    """Partidas de la biblioteca (y propias con ACU) de la MISMA unidad más
    parecidas: ``[{'descripcion','unidad','origen','ref_id','puntaje'}]``."""
    from rapidfuzz import fuzz, process
    from core.ai_specs import _normalizar_desc
    from core.database import pool_partidas_rag
    with _tx(conn) as c:
        u = unidad_si(unidad) or (unidad or '').strip().lower()
        pool = [x for x in pool_partidas_rag(c)
                if (unidad_si(x['unidad']) or (x['unidad'] or '').strip().lower()) == u]
    q = _normalizar_desc(descripcion.replace('—', ' '))
    r = process.extract(q, [x['_norm'] for x in pool], scorer=fuzz.token_set_ratio, limit=limite,
                        score_cutoff=55)
    return [{**{k: pool[i][k] for k in ('descripcion', 'unidad', 'origen', 'ref_id')},
             'puntaje': round(s, 1)} for _t, s, i in r]


def poner_acu(partida_id: int, origen: str, ref_id: int, *, solo_estructura=False,
              conn=None) -> bool:
    """Copia a una partida SIN ACU la composición de la biblioteca."""
    from core.database import _recalcular_pu, acu_de_pool, copiar_items_acu
    with _tx(conn) as c:
        p = c.execute("SELECT proyecto_id FROM partidas WHERE id=?", (partida_id,)).fetchone()
        if not p or c.execute("SELECT 1 FROM acu_items WHERE partida_id=? LIMIT 1",
                              (partida_id,)).fetchone():
            return False
        acu = acu_de_pool(c, origen, ref_id)
        if not acu or not acu['items']:
            return False
        c.execute("UPDATE partidas SET rendimiento=? WHERE id=?", (acu['rendimiento'], partida_id))
        copiar_items_acu(c, partida_id, acu['items'], proyecto_id=p['proyecto_id'],
                         solo_estructura=solo_estructura)
        _recalcular_pu(c, partida_id)
        return True


# ── Copias: duplicar proyecto, exportar/importar .db, copiar/pegar ───────────

def _hay(conn, esquema: str) -> bool:
    return conn.execute(f"SELECT 1 FROM {esquema}.sqlite_master WHERE type='table' "
                        "AND name='bim_vinculos'").fetchone() is not None


def copiar_proyecto(conn, pid_origen: int, pid_destino: int, partidas_: dict, filas: dict,
                    esquema: str = 'main') -> None:
    """Copia modelos, elementos y vínculos de un proyecto a otro de la BD
    (`esquema='src'` si viene de otra adjunta). `partidas_` y `filas` mapean
    ids viejos → nuevos de partidas y de metrados_detalle."""
    if not _hay(conn, esquema):
        return
    for m in conn.execute(f"SELECT id, nombre, origen, ruta, huella, importado_en "
                          f"FROM {esquema}.bim_modelos WHERE proyecto_id=?", (pid_origen,)).fetchall():
        nuevo = conn.execute(
            "INSERT INTO main.bim_modelos (proyecto_id, nombre, origen, ruta, huella, importado_en) "
            "VALUES (?,?,?,?,?,?)", (pid_destino, *tuple(m)[1:])).lastrowid
        conn.execute(f"INSERT INTO main.bim_elementos (modelo_id, global_id, datos) "
                     f"SELECT ?, global_id, datos FROM {esquema}.bim_elementos "
                     "WHERE modelo_id=? ORDER BY rowid", (nuevo, m[0]))
        for v in conn.execute(
                f"SELECT partida_id, metrado_detalle_id, global_id, medida, factor, valor, unidad "
                f"FROM {esquema}.bim_vinculos WHERE modelo_id=?", (m[0],)).fetchall():
            if v[0] in partidas_ and v[1] in filas:
                conn.execute(
                    "INSERT OR IGNORE INTO main.bim_vinculos (partida_id, modelo_id, "
                    "metrado_detalle_id, global_id, medida, factor, valor, unidad) "
                    "VALUES (?,?,?,?,?,?,?,?)", (partidas_[v[0]], nuevo, filas[v[1]], *tuple(v)[2:]))


def serializar_vinculos(conn, partida_id: int) -> list[dict]:
    """Vínculos de una partida para el portapapeles."""
    return [dict(r) for r in conn.execute(
        "SELECT v.metrado_detalle_id, v.modelo_id, v.global_id, v.medida, v.factor, v.valor, "
        "v.unidad, m.huella, m.proyecto_id FROM bim_vinculos v JOIN bim_modelos m ON m.id=v.modelo_id "
        "WHERE v.partida_id=?", (partida_id,))]


def pegar_vinculos(conn, pid_destino: int, partida_id: int, vinculos: list, filas: dict,
                   modelos_: dict) -> None:
    """Rehace en la partida pegada los vínculos copiados. Si el destino es
    otro proyecto, lleva también el modelo (una vez: `modelos_` es caché)."""
    for v in vinculos:
        mid = v['modelo_id']
        if mid not in modelos_:
            modelos_[mid] = None
            orig = conn.execute("SELECT * FROM bim_modelos WHERE id=?", (mid,)).fetchone()
            if orig and orig['proyecto_id'] == pid_destino:
                modelos_[mid] = mid
            elif orig:
                r = conn.execute("SELECT id FROM bim_modelos WHERE proyecto_id=? AND huella=? "
                                 "AND huella<>''", (pid_destino, orig['huella'])).fetchone()
                if r:
                    modelos_[mid] = r['id']
                else:
                    nuevo = conn.execute(
                        "INSERT INTO bim_modelos (proyecto_id, nombre, origen, ruta, huella, "
                        "importado_en) VALUES (?,?,?,?,?,?)",
                        (pid_destino, orig['nombre'], orig['origen'], orig['ruta'], orig['huella'],
                         orig['importado_en'])).lastrowid
                    conn.execute("INSERT INTO bim_elementos (modelo_id, global_id, datos) SELECT ?, "
                                 "global_id, datos FROM bim_elementos WHERE modelo_id=? ORDER BY rowid",
                                 (nuevo, mid))
                    modelos_[mid] = nuevo
        if modelos_[mid] and v['metrado_detalle_id'] in filas:
            conn.execute("INSERT OR IGNORE INTO bim_vinculos (partida_id, modelo_id, global_id, "
                         "medida, factor, metrado_detalle_id, valor, unidad) VALUES (?,?,?,?,?,?,?,?)",
                         (partida_id, modelos_[mid], v['global_id'], v['medida'], v['factor'],
                          filas[v['metrado_detalle_id']], v['valor'], v['unidad']))
