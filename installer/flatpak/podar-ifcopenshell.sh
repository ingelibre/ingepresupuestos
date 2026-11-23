#!/bin/sh
# Deja de IfcOpenShell solo lo que usa el visor BIM (lo mismo que el .spec):
# 203 MB → unos 80. Uso: podar-ifcopenshell.sh <carpeta con el paquete ifcopenshell>
set -eu
cd "$1/ifcopenshell"
rm -rf api express util/schema libwgpu_native.so libOpenCOLLADA* libMathMLSolver* \
  libGeneratedSaxParser* libbuffer.so libftoa.so libUTF.so libTKDE* libTKRWMesh* \
  libTKCAF* libTKCDF* libTKHLR* libTKLCAF* libTKService* libTKV3d* libTKVCAF* \
  libTKXCAF* libTKXSBase* libgmp* libmpfr* libmanifold* libpcre* libxml2* \
  ifcopenshell_geometry_kernel_cgal* ifcopenshell_geometry_kernel_manifold* \
  ifcopenshell_geometry_svg* ifcopenshell_geometry_tree* ifcopenshell_geometry_writer* \
  ifcopenshell_document_json* ifcopenshell_document_xml*
for x in dae glb igs obj stp ttl; do rm -f ifcopenshell_geometry_$x.so; done
