#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
¿Algún backend de python-seabreeze implementa de verdad `acquisition_delay`?

Todo el repo usa `pyseabreeze` (Python puro, sin DLL del fabricante), en los
6 scripts y en el HAL. El otro backend, `cseabreeze` —la librería C++ de Ocean
compilada—, nunca se probó.

La feature `acquisition_delay` está DECLARADA para varios modelos en pyseabreeze
pero NO implementada para el HR2000+: levanta NotImplementedError. Si cseabreeze
la tuviera implementada, se podría fijar el gate delay desde Python y no haría
falta ingeniería inversa de ningún registro FPGA.

Este script contesta esa pregunta. Es SOLO LECTURA salvo que se pase --set.

Uso:
    python tools/probe_backends_delay.py              # prueba los dos backends
    python tools/probe_backends_delay.py --backend cseabreeze
    python tools/probe_backends_delay.py --set 1000   # además intenta escribir

⚠ Cerrá ocean_control.py, OceanView y cualquier otro programa que tenga los
  módulos tomados: un módulo abierto por otro proceso acá aparece como ausente.

⚠ IMPORTANTE sobre los drivers en Windows — los dos backends NO usan el mismo:

      pyseabreeze  →  WinUSB   (el que asigna Zadig; es lo que tiene la Dell)
      cseabreeze   →  driver nativo de Ocean (el que instala OmniDriver)

  Por eso es ESPERABLE que cseabreeze detecte 0 módulos en una máquina
  configurada para pyseabreeze. Eso NO significa que cseabreeze no sirva:
  significa que para probarlo hay que correrlo donde esté el driver nativo,
  o rebindear. El script lo aclara en la salida cuando pasa.
"""

import argparse
import subprocess
import sys

BACKENDS = ("pyseabreeze", "cseabreeze")


# ─────────────────────────────────────────────────────────────────────────────
# Sondeo de UN backend (este proceso queda atado a él: seabreeze.use() no se
# puede deshacer una vez importado seabreeze.spectrometers)
# ─────────────────────────────────────────────────────────────────────────────
def probe(backend, set_us=None):
    print("=" * 74)
    print("BACKEND: %s" % backend)
    print("=" * 74)

    if backend == "pyseabreeze":
        # Windows: pyusb no encuentra libusb solo; libusb_package lo provee.
        # Mismo parche que usa ocean_control.py.
        try:
            import libusb_package
            import usb.core as _usb_core
            _lb = libusb_package.get_libusb1_backend()
            if _lb is not None:
                _orig = _usb_core.find

                def _patched(*a, **kw):
                    kw.setdefault("backend", _lb)
                    return _orig(*a, **kw)

                _usb_core.find = _patched
        except Exception as e:
            print("  aviso: no se pudo preparar libusb (%s)" % e)

    try:
        import seabreeze
        seabreeze.use(backend)
        from seabreeze.spectrometers import Spectrometer, list_devices
    except Exception as e:
        print("  ✗ backend NO disponible: %s" % e)
        if backend == "cseabreeze":
            print("    Instalar con:  pip install seabreeze[cseabreeze]")
        return 2

    print("  ✓ backend cargado")

    try:
        devices = list(list_devices())
    except Exception as e:
        print("  ✗ list_devices() falló: %s" % e)
        return 2

    if not devices:
        print("  ✗ 0 módulos detectados.")
        if backend == "cseabreeze":
            print()
            print("    Esperable si esta PC tiene los módulos en WinUSB (Zadig).")
            print("    cseabreeze necesita el driver NATIVO de Ocean (OmniDriver).")
            print("    No concluye nada sobre la feature: hay que correrlo donde")
            print("    esté el driver nativo, o rebindear el driver.")
        else:
            print("    Verificar: rack encendido, driver WinUSB, y que no esté")
            print("    abierto ocean_control.py / OceanView / otra instancia.")
        return 3

    print("  %d módulo(s) detectado(s)" % len(devices))
    print()

    veredicto = False
    for dev in sorted(devices, key=lambda d: str(d.serial_number)):
        try:
            spec = Spectrometer(dev)
        except Exception as e:
            print("  ── %s: no se pudo abrir: %s" % (dev, e))
            continue

        try:
            serial = spec.serial_number
        except Exception:
            serial = str(dev)
        print("  ── %s ──" % serial)

        # Features realmente soportadas (las vacías son ruido: pyseabreeze
        # declara como clave TODAS las que conoce, tenga o no el módulo).
        try:
            feats = sorted(n for n, insts in spec.features.items() if insts)
            print("     features: %s" % ", ".join(feats))
        except Exception as e:
            feats = []
            print("     features: no se pudieron listar (%s)" % e)

        f = None
        try:
            lst = spec.features.get("acquisition_delay", [])
            f = lst[0] if lst else None
        except Exception:
            pass

        if f is None:
            print("     acquisition_delay: la feature NO existe en este módulo")
        else:
            try:
                mn = int(f.get_minimum_delay_microseconds())
                mx = int(f.get_maximum_delay_microseconds())
                inc = int(f.get_delay_increment_microseconds())
                print("     acquisition_delay: ✓ OPERATIVA — %d a %d µs, paso %d"
                      % (mn, mx, inc))
                veredicto = True
                try:
                    print("     delay actual: %d µs"
                          % int(f.get_delay_microseconds()))
                except Exception as e:
                    print("     delay actual: no se pudo leer (%s)" % e)

                if set_us is not None:
                    _try_set(f, set_us, mn, mx, inc)

            except NotImplementedError:
                print("     acquisition_delay: declarada pero NO IMPLEMENTADA "
                      "para este modelo")
            except Exception as e:
                print("     acquisition_delay: falló al consultarla (%s)" % e)

        try:
            spec.close()
        except Exception:
            pass
        print()

    print("  VEREDICTO %s: %s" % (
        backend,
        "acquisition_delay USABLE" if veredicto else "acquisition_delay NO usable"))
    print()
    return 0 if veredicto else 1


def _try_set(feature, us, mn, mx, inc):
    """Escribe el delay y verifica por read-back. Solo con --set."""
    us = max(mn, min(mx, us))
    if inc > 1:
        us = (us // inc) * inc
    print("     --set: escribiendo %d µs…" % us)
    try:
        feature.set_delay_microseconds(us)
    except Exception as e:
        print("     --set: ✗ falló al escribir (%s)" % e)
        return
    try:
        back = int(feature.get_delay_microseconds())
    except Exception as e:
        print("     --set: escribió, pero no se pudo releer (%s)" % e)
        return
    marca = "✓ coincide" if back == us else "✗ NO coincide"
    print("     --set: read-back = %d µs  [%s]" % (back, marca))


# ─────────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--backend", choices=BACKENDS,
                    help="probar sólo este backend (default: los dos)")
    ap.add_argument("--set", type=int, metavar="US", dest="set_us",
                    help="además de leer, intentar fijar el delay en US µs")
    args = ap.parse_args()

    if args.backend:
        return probe(args.backend, args.set_us)

    # Sin --backend: un subproceso por backend. seabreeze.use() no se puede
    # cambiar dentro del mismo proceso una vez importado spectrometers.
    codes = {}
    for b in BACKENDS:
        cmd = [sys.executable, __file__, "--backend", b]
        if args.set_us is not None:
            cmd += ["--set", str(args.set_us)]
        codes[b] = subprocess.call(cmd)

    print("=" * 74)
    print("RESUMEN")
    print("=" * 74)
    leyenda = {0: "acquisition_delay USABLE",
               1: "feature no usable (declarada pero no implementada)",
               2: "backend no disponible / error al cargar",
               3: "0 módulos detectados (probable tema de driver)"}
    for b in BACKENDS:
        print("  %-12s  %s" % (b, leyenda.get(codes[b], "código %d" % codes[b])))
    print()
    if codes.get("cseabreeze") == 0:
        print("  → cseabreeze SIRVE: se puede fijar el delay desde Python y no")
        print("    hace falta ingeniería inversa del banco de registros.")
    elif codes.get("cseabreeze") == 3:
        print("  → cseabreeze no vio los módulos. Correrlo en la PC con el")
        print("    driver nativo de Ocean antes de descartarlo.")
    return 0 if 0 in codes.values() else 1


if __name__ == "__main__":
    sys.exit(main())
