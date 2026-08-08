#!/usr/bin/env python3
# Copyright (C) 2026 Marco Sumari / Sumari SAC. Todos los derechos reservados.
# Herramienta interna — NO distribuir con la aplicación.
"""Generador de claves de licencia de IngePresupuestos.

Firma un payload JSON con la clave privada RSA-2048 (RSA-PSS + SHA-256) y
emite la clave user-facing que el comprador pega en «Activar licencia…».

La clave privada vive FUERA del repositorio y nunca se commitea:

    ~/.ingepresupuestos-licencias/license_private.pem

Su pública correspondiente es ``resources/license_public.pem``, que sí se
bundlea en el binario y es la que verifica ``core.licencia.activar_clave``.

Uso típico — el comprador manda su ID de máquina por WhatsApp (lo ve en
«Acerca de → Activar licencia…»):

    # Licencia anual (vence en 365 días)
    python3 scripts/gen_license.py --tipo anual \\
        --nombre "Juan Pérez" --email juan@correo.com \\
        --machine-id a1b2-c3d4-e5f6-a7b8

    # Licencia perpetua (no vence)
    python3 scripts/gen_license.py --tipo perpetua \\
        --nombre "Constructora XYZ SAC" --email admin@xyz.pe \\
        --machine-id a1b2-c3d4-e5f6-a7b8

    # Sin binding de máquina (sirve en cualquier PC — usar con criterio)
    python3 scripts/gen_license.py --tipo anual --nombre "..." \\
        --email "..." --sin-binding

Cada emisión se registra en ``~/.ingepresupuestos-licencias/emitidas.csv``
para llevar el control de a quién se le vendió qué.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Permite ejecutar el script desde la raíz del proyecto sin instalar nada.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.licencia import LICENSE_FORMAT_VERSION, empaquetar_clave  # noqa: E402

KEY_DIR = Path.home() / ".ingepresupuestos-licencias"
PRIVATE_KEY_PATH = KEY_DIR / "license_private.pem"
REGISTRO_CSV = KEY_DIR / "emitidas.csv"

DIAS_ANUAL = 365


def _normalizar_machine_id(raw: str) -> str:
    """Acepta el ID con o sin guiones (la app lo muestra como a1b2-c3d4-…)."""
    mid = raw.replace("-", "").replace(" ", "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{16}", mid):
        raise SystemExit(
            f"ID de máquina inválido: {raw!r}\n"
            "Debe ser 16 caracteres hexadecimales, con o sin guiones.\n"
            "El comprador lo ve en «Acerca de → Activar licencia…»."
        )
    return mid


def _firmar(payload: dict) -> bytes:
    """Firma el payload con RSA-PSS + SHA-256, idéntico a lo que verifica
    ``core.licencia._verificar_firma``."""
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    if not PRIVATE_KEY_PATH.exists():
        raise SystemExit(
            f"No se encontró la clave privada en {PRIVATE_KEY_PATH}\n\n"
            "Sin ella no se pueden emitir licencias. Restaurala del backup.\n"
            "Si la perdiste definitivamente hay que generar un par nuevo y\n"
            "publicar una versión con la pública nueva — las claves ya\n"
            "emitidas dejarían de validar."
        )

    with PRIVATE_KEY_PATH.open("rb") as f:
        privkey = serialization.load_pem_private_key(f.read(), password=None)

    # MISMA serialización que `empaquetar_clave` — cualquier diferencia de
    # separadores u orden de llaves invalida la firma.
    payload_bytes = json.dumps(
        payload, separators=(",", ":"), sort_keys=True, ensure_ascii=False
    ).encode("utf-8")

    return privkey.sign(
        payload_bytes,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH,
        ),
        hashes.SHA256(),
    )


def _registrar(payload: dict, clave: str, monto: str) -> None:
    """Anota la emisión en el CSV de control. Best-effort."""
    nuevo = not REGISTRO_CSV.exists()
    try:
        KEY_DIR.mkdir(parents=True, exist_ok=True)
        with REGISTRO_CSV.open("a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if nuevo:
                w.writerow(["emitida", "tipo", "nombre", "email",
                            "machine_id", "expira", "monto", "clave"])
            w.writerow([
                payload["emitida"], payload["tipo"], payload["nombre"],
                payload["email"], payload.get("machine_id", ""),
                payload.get("expira", ""), monto, clave,
            ])
    except OSError as e:
        print(f"  aviso: no se pudo escribir el registro ({e})", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(
        description="Emite una clave de licencia firmada de IngePresupuestos.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Uso típico")[-1],
    )
    p.add_argument("--tipo", required=True, choices=["anual", "perpetua"])
    p.add_argument("--nombre", required=True, help="Nombre del titular o razón social")
    p.add_argument("--email", required=True, help="Email del comprador")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--machine-id", help="ID de máquina del comprador (con o sin guiones)")
    g.add_argument("--sin-binding", action="store_true",
                   help="Emite una clave sin atar a una máquina")
    p.add_argument("--dias", type=int, default=DIAS_ANUAL,
                   help=f"Vigencia en días para licencias anuales (por defecto {DIAS_ANUAL})")
    p.add_argument("--monto", default="",
                   help="Monto cobrado, solo para el registro interno (ej. 'S/ 149 Yape')")
    args = p.parse_args()

    hoy = datetime.now().date()
    payload = {
        "v": LICENSE_FORMAT_VERSION,
        "tipo": args.tipo,
        "nombre": args.nombre.strip(),
        "email": args.email.strip(),
        "machine_id": "" if args.sin_binding else _normalizar_machine_id(args.machine_id),
        "emitida": hoy.isoformat(),
        "expira": "" if args.tipo == "perpetua" else (hoy + timedelta(days=args.dias)).isoformat(),
    }

    clave = empaquetar_clave(payload, _firmar(payload))
    _registrar(payload, clave, args.monto)

    print()
    print("─" * 72)
    print(f"  Licencia {payload['tipo'].upper()} para {payload['nombre']}")
    print(f"  Email:    {payload['email']}")
    print(f"  Máquina:  {payload['machine_id'] or '(sin binding — sirve en cualquier PC)'}")
    print(f"  Emitida:  {payload['emitida']}")
    print(f"  Vence:    {payload['expira'] or 'nunca'}")
    print("─" * 72)
    print()
    print("Clave para enviarle al comprador (una sola línea, se pega completa):")
    print()
    print(clave)
    print()
    print(f"Registrada en {REGISTRO_CSV}")
    print()


if __name__ == "__main__":
    main()
