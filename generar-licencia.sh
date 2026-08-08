#!/usr/bin/env bash
# Generador de claves de licencia — atajo sobre scripts/gen_license.py.
# HERRAMIENTA INTERNA de Marco: necesita la clave privada RSA de
# ~/.ingepresupuestos-licencias/ (nunca viaja en el repo ni en el binario).
#
# Uso rápido:
#   ./generar-licencia.sh --tipo anual    --nombre "Juan Pérez" \
#       --email juan@correo.com --machine-id a1b2-c3d4-e5f6-a7b8 \
#       --monto "S/ 80 Yape"
#
#   ./generar-licencia.sh --tipo perpetua --nombre "Constructora XYZ SAC" \
#       --email admin@xyz.pe --machine-id a1b2-c3d4-e5f6-a7b8 \
#       --monto "S/ 300 transferencia"
#
# El comprador ve su machine-id en: Acerca de → Activar licencia…
# Cada clave emitida queda registrada en:
#   ~/.ingepresupuestos-licencias/emitidas.csv
#
# Sin argumentos muestra la ayuda completa.
cd "$(dirname "$0")"
if [ $# -eq 0 ]; then
    exec venv/bin/python3 scripts/gen_license.py --help
fi
exec venv/bin/python3 scripts/gen_license.py "$@"
