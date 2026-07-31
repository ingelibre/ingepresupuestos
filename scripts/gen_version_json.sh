#!/usr/bin/env bash
# Genera el `version.json` que lee el auto-updater de la app.
#
#   scripts/gen_version_json.sh 2.8.6 [notas]      → escribe ./version.json
#
# NO sube nada: la subida a R2 necesita credenciales y vive en los workflows
# (build-linux.yml y update-version-json.yml), que ambos llaman a este script
# para no tener dos copias de la lógica divergiendo.
#
# El changelog sale, por orden: el argumento `notas` → el mensaje del tag
# anotado → un texto genérico. Ese campo es lo que el usuario ve en el aviso
# de actualización, así que NUNCA debe acabar siendo el mensaje del commit.
set -euo pipefail

V="${1:?falta la versión (ej. 2.8.6)}"
NOTAS="${2:-}"
BASE="${BASE_URL:-https://downloads.ingepresupuestos.com}"
OUT="${OUT_FILE:-version.json}"

# ── Los 4 binarios deben existir ya en R2 o publicaríamos enlaces rotos ──────
FILES="v${V}/ingepresupuestos-setup-v${V}.exe
v${V}/ingepresupuestos-windows.zip
v${V}/IngePresupuestos-${V}-x86_64.AppImage
v${V}/ingepresupuestos-linux.tar.gz"
faltan=""
for f in $FILES; do
    curl -fsI "${BASE}/${f}" >/dev/null 2>&1 || faltan="${faltan} ${f}"
done
if [ -n "$faltan" ]; then
    echo "ERROR: faltan binarios en R2:${faltan}" >&2
    exit 2
fi

# ── Preservar el bloque `ingeconverter` del version.json vivo ───────────────
if ! curl -fsSL "${BASE}/version.json" -o _cur.json; then
    echo "ERROR: no pude leer el version.json actual (perdería ingeconverter)" >&2
    exit 3
fi

# ── Changelog ───────────────────────────────────────────────────────────────
if [ -z "$NOTAS" ]; then
    # `actions/checkout` clona en superficial y NO trae el objeto del tag
    # anotado; sin este fetch, `%(contents)` cae al mensaje del commit y el
    # aviso de actualización mostraba «chore: bump version to X.Y.Z» (v2.8.6).
    git fetch --force origin "refs/tags/v${V}:refs/tags/v${V}" 2>/dev/null || true
    NOTAS=$(git for-each-ref "refs/tags/v${V}" --format='%(contents)' 2>/dev/null | head -c 3000)
    # Un tag ligero devuelve el mensaje del commit; y "Release vX.Y.Z" era el
    # texto que ponía release.sh antes de aceptar notas. Ninguno sirve.
    case "$NOTAS" in chore:*|"Release v${V}") NOTAS="" ;; esac
fi
[ -z "$NOTAS" ] && NOTAS="Versión ${V} — software libre y gratuito. Novedades en ingepresupuestos.com"

ICONV=$(jq -c 'if .ingeconverter then .ingeconverter else null end' _cur.json)
jq -n --arg v "$V" --arg date "$(date +%F)" --arg cl "$NOTAS" --argjson ic "$ICONV" \
  '{version:$v, release_date:$date, changelog:$cl, minimum_version:null,
    downloads:{
      windows_installer:("https://downloads.ingepresupuestos.com/v"+$v+"/ingepresupuestos-setup-v"+$v+".exe"),
      windows_portable:("https://downloads.ingepresupuestos.com/v"+$v+"/ingepresupuestos-windows.zip"),
      linux_appimage:("https://downloads.ingepresupuestos.com/v"+$v+"/IngePresupuestos-"+$v+"-x86_64.AppImage"),
      linux_portable:("https://downloads.ingepresupuestos.com/v"+$v+"/ingepresupuestos-linux.tar.gz")
    },
    download_url:"https://ingepresupuestos.com/#descargar"}
   + (if $ic==null then {} else {ingeconverter:$ic} end)' > "$OUT"
rm -f _cur.json
echo "── ${OUT} generado ──"
cat "$OUT"
