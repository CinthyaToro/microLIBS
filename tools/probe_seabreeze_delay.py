# -*- coding: utf-8 -*-
"""
probe_seabreeze_delay.py
========================
Diagnostico: el backend cseabreeze de python-seabreeze, expone un control de
TRIGGER DELAY (gate delay) para el HR2000+, o hay que ir a OmniDriver?

Es READ-ONLY. La Etapa 1 NO toca microLIBS, ni el hardware, ni los drivers.

----------------------------------------------------------------------------
ETAPA 1  (segura, correr en la OFICINA, sin espectrometro conectado)
----------------------------------------------------------------------------
  python probe_seabreeze_delay.py

  Inspecciona la API de los backends 'cseabreeze' y 'pyseabreeze' y lista todos
  los metodos de sus clases Feature, marcando con  >>> los que matchean
  delay / trigger / strobe / lamp. Responde la condicion NECESARIA: existe el
  control en la libreria? Si ningun backend lo expone, cseabreeze queda
  descartado y el camino es OmniDriver.

----------------------------------------------------------------------------
ETAPA 2  (en el LABO, con el HR2000+ enchufado, SOLO si la Etapa 1 encontro algo)
----------------------------------------------------------------------------
  python probe_seabreeze_delay.py --device

  Enumera las features del equipo real bajo cseabreeze.

  >>> ADVERTENCIA WINDOWS <<<
  cseabreeze y pyseabreeze usan DRIVERS USB DISTINTOS. microLIBS hoy anda con
  pyseabreeze (driver libusb/WinUSB). Si cseabreeze no ve el equipo, es porque
  el HR2000+ esta bindeado al driver de pyseabreeze, NO porque el equipo falle.
  NO corras 'seabreeze_os_setup' a la ligera para forzar el rebind: te puede
  romper el path pyseabreeze que ya funciona para el congreso. El rebind a
  cseabreeze es una decision de v2, con plan de vuelta atras, NO algo para
  hacer en plena sesion de labo.
"""

import sys
import inspect
import importlib

KEYWORDS = ("delay", "trigger", "strobe", "lamp")


def banner(t):
    print("\n" + "=" * 64)
    print(t)
    print("=" * 64)


def public_methods(cls):
    out = []
    for m, _ in inspect.getmembers(cls, callable):
        if not m.startswith("_"):
            out.append(m)
    return sorted(set(out))


def dump_backend_api(backend_name):
    """Lista las clases Feature de un backend y sus metodos, marcando keywords."""
    banner("ETAPA 1 - API del backend: %s" % backend_name)
    try:
        mod = importlib.import_module("seabreeze.%s" % backend_name)
    except Exception as e:
        print("  NO disponible: %s" % e)
        print("  (si falta cseabreeze:  pip install seabreeze )")
        print("  (si falta pyseabreeze: pip install seabreeze[pyseabreeze] )")
        return None

    hit_global = False
    for name, obj in inspect.getmembers(mod, inspect.isclass):
        # solo clases que parezcan Feature o Spectrometer del backend
        if not any(tag in name for tag in ("Feature", "Spectrometer", "Device")):
            continue
        methods = public_methods(obj)
        if not methods:
            continue
        print("\n  [%s]" % name)
        for m in methods:
            mark = ">>>" if any(k in m.lower() for k in KEYWORDS) else "   "
            if mark == ">>>":
                hit_global = True
            print("    %s %s" % (mark, m))

    print("\n  --> %s expone metodos de delay/trigger/strobe?  %s" % (
        backend_name, "SI (ver lineas >>>)" if hit_global else "NO"))
    return hit_global


def probe_real_device():
    """ETAPA 2: enumera features del HR2000+ real bajo cseabreeze."""
    banner("ETAPA 2 - Equipo real bajo cseabreeze")
    try:
        from seabreeze.cseabreeze import SeaBreezeAPI
    except Exception as e:
        print("  No pude importar SeaBreezeAPI de cseabreeze: %s" % e)
        return

    try:
        api = SeaBreezeAPI()
        devices = api.list_devices()
    except Exception as e:
        print("  Error listando dispositivos: %s" % e)
        return

    if not devices:
        print("  No se encontro ningun dispositivo bajo cseabreeze.")
        print("  OJO (Windows): el HR2000+ probablemente esta bindeado al driver")
        print("  de pyseabreeze (libusb/WinUSB). Eso NO significa que el equipo")
        print("  falle. Lee la advertencia del encabezado antes de rebindear nada.")
        return

    for dev in devices:
        print("\n  Dispositivo: %s" % dev)
        try:
            dev.open()
        except Exception as e:
            print("    No pude abrirlo: %s" % e)
            continue
        try:
            print("    model  : %s" % getattr(dev, "model", "?"))
            print("    serial : %s" % getattr(dev, "serial_number", "?"))
            feats = getattr(dev, "features", {}) or {}
            print("    features disponibles:")
            for fname, flist in feats.items():
                mark = ">>>" if any(k in fname.lower() for k in KEYWORDS) else "   "
                print("      %s %s  (n=%d)" % (mark, fname, len(flist)))
        except Exception as e:
            print("    Error leyendo features: %s" % e)
        finally:
            try:
                dev.close()
            except Exception:
                pass


def main():
    try:
        import seabreeze
        print("seabreeze version: %s" % getattr(seabreeze, "__version__", "?"))
    except Exception as e:
        print("No pude importar seabreeze: %s" % e)
        print("Instalalo con:  pip install seabreeze")
        return

    c_hit = dump_backend_api("cseabreeze")
    p_hit = dump_backend_api("pyseabreeze")

    if "--device" in sys.argv:
        probe_real_device()

    banner("CONCLUSION")
    if c_hit:
        print("  cseabreeze SI muestra metodos relacionados (revisa los >>> arriba).")
        print("  Camino barato posible: confirmar en el labo con --device que el")
        print("  metodo de delay aplique al HR2000+. Si aplica, ganaste sin OmniDriver.")
    else:
        print("  cseabreeze NO expone control de delay en su API.")
        print("  Camino seguro: OmniDriver (setExternalTriggerDelay), detras del HAL,")
        print("  como driver de espectrometro de v2.")
    print("  pyseabreeze (lo que usa microLIBS hoy): %s" % (
        "tiene algo" if p_hit else "no expone delay, como esperabamos."))


if __name__ == "__main__":
    main()
