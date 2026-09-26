#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
medir_ciclo_ocean.py  —  Herramienta de medición descartable
==============================================================
Mide el ciclo real de adquisición del Ocean HR2000+ en modo 0 (free-running).

Uso:
  python medir_ciclo_ocean.py --int-us 5000 --repeats 100 --out mediciones.csv

Objetivos:
  1. Medir elapsed_ms real en modo free-running para diferentes integraciones
  2. Detectar jitter en el timing
  3. Estimar dead time entre lecturas
  4. Validar que el timing es compatible con burst del láser a 100 Hz

Output:
  - Terminal: resumen estadístico (min, max, promedio, stdev)
  - CSV: todos los valores individuales (si --out se especifica)

NOTA: Este script es para medir en laboratorio. Descartar después de cada sesión.
"""

from __future__ import print_function

import argparse
import csv
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ─── Parche libusb (Windows) ──────────────────────────────────────────────────

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
except Exception:
    pass

try:
    import seabreeze
    seabreeze.use("pyseabreeze")
    from seabreeze.spectrometers import list_devices, Spectrometer
except ImportError:
    print("ERROR: seabreeze no instalado — pip install seabreeze")
    sys.exit(1)


def hline(c="-", n=70):
    print(c * n)


def connect_modules():
    """Detecta y abre módulos HR2000+ en free-running (modo 0)."""
    devices = list_devices()
    if not devices:
        print("ERROR: ningún HR2000+ detectado.")
        print("  Verificar: rack encendido, Zadig WinUSB, OceanView cerrado.")
        sys.exit(1)

    modules = []
    for i, dev in enumerate(sorted(devices, key=lambda d: d.serial_number)):
        letter = "ABC"[i] if i < 3 else str(i)
        try:
            spec = Spectrometer(dev)
            spec.integration_time_micros(10000)
            spec.trigger_mode(0)  # Free-running
            wls = list(spec.wavelengths())
            modules.append({
                "letter": letter,
                "serial": dev.serial_number,
                "spec": spec,
                "wls": wls,
            })
            print("  Canal %s: %s  [%.1f – %.1f nm]" % (
                letter, dev.serial_number, wls[0], wls[-1]))
        except Exception as e:
            print("  Canal %s: %s  ERROR: %s" % (letter, dev.serial_number, e))

    return modules


def close_modules(modules):
    for m in modules:
        try:
            m["spec"].trigger_mode(0)
            m["spec"].close()
        except Exception:
            pass


def measure_cycle(modules, int_us, repeats):
    """
    Realiza `repeats` ciclos de adquisición y mide elapsed_ms en cada uno.
    Usa el método que microLIBS usa: basado en time.perf_counter().

    Retorna dict con:
      - "samples": lista de tuples (channel, elapsed_ms, n_points)
      - "repeats": número de ciclos completados
      - "int_us": integración configurada
    """
    # Configurar integración en todos los módulos
    for m in modules:
        m["spec"].integration_time_micros(int_us)
    time.sleep(0.15)  # settle

    all_samples = []

    for rep in range(repeats):
        sys.stdout.write("\r  Ciclo %d/%d... " % (rep + 1, repeats))
        sys.stdout.flush()

        for m in modules:
            try:
                t0 = time.perf_counter()
                raw = list(m["spec"].intensities())  # ← Lectura
                elapsed = (time.perf_counter() - t0) * 1000.0

                all_samples.append({
                    "channel": m["letter"],
                    "serial": m["serial"],
                    "repeats": rep + 1,
                    "elapsed_ms": elapsed,
                    "n_points": len(raw),
                })
            except Exception as e:
                print("\n  ERROR en canal %s ciclo %d: %s" % (
                    m["letter"], rep + 1, e))

    print("\rCiclos completados.           ")
    return all_samples


def analyze_samples(samples, int_us):
    """Analiza las muestras y retorna estadísticas."""
    if not samples:
        return None

    elapsed_list = [s["elapsed_ms"] for s in samples]
    elapsed_list.sort()

    n = len(elapsed_list)
    mean = sum(elapsed_list) / n
    variance = sum((x - mean) ** 2 for x in elapsed_list) / n
    stdev = variance ** 0.5
    median = elapsed_list[n // 2] if n % 2 == 1 else (
        elapsed_list[n // 2 - 1] + elapsed_list[n // 2]) / 2.0

    dead_time_est = mean - (int_us / 1000.0)

    return {
        "n_samples": n,
        "min_ms": elapsed_list[0],
        "max_ms": elapsed_list[-1],
        "mean_ms": mean,
        "median_ms": median,
        "stdev_ms": stdev,
        "int_configured_ms": int_us / 1000.0,
        "dead_time_est_ms": dead_time_est,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Mide el ciclo de adquisición del Ocean HR2000+ en modo 0"
    )
    parser.add_argument("--int-us", type=int, default=5000,
                        help="Integración en µs (default: 5000 = 5 ms)")
    parser.add_argument("--repeats", type=int, default=100,
                        help="Número de ciclos a medir (default: 100)")
    parser.add_argument("--out", type=str, default=None,
                        help="Archivo CSV de salida con todas las muestras")
    args = parser.parse_args()

    hline("=")
    print("Medidor de ciclo Ocean HR2000+ — modo 0 (free-running)")
    hline("=")
    print()
    print("Parámetros:")
    print("  Integración: %d µs (%.1f ms)" % (args.int_us, args.int_us / 1000.0))
    print("  Ciclos a medir: %d" % args.repeats)
    if args.out:
        print("  Salida CSV: %s" % args.out)
    print()

    print("Detectando módulos...")
    modules = connect_modules()
    if not modules:
        print("ERROR: no se detectaron módulos.")
        sys.exit(1)
    print()

    print("Midiendo ciclos...")
    samples = measure_cycle(modules, args.int_us, args.repeats)
    close_modules(modules)
    print()

    if not samples:
        print("ERROR: ninguna muestra válida.")
        sys.exit(1)

    # Análisis estadístico
    stats = analyze_samples(samples, args.int_us)

    hline("=")
    print("RESULTADOS")
    hline("=")
    print()
    print("Integración configurada: %.1f ms" % stats["int_configured_ms"])
    print("Muestras: %d" % stats["n_samples"])
    print()
    print("elapsed_ms (tiempo total de lectura):")
    print("  mín:  %.2f ms" % stats["min_ms"])
    print("  máx:  %.2f ms" % stats["max_ms"])
    print("  prom: %.2f ms" % stats["mean_ms"])
    print("  median: %.2f ms" % stats["median_ms"])
    print("  stdev: %.2f ms" % stats["stdev_ms"])
    print()
    print("Dead time estimado (promedio - integración):")
    print("  %.2f ms" % stats["dead_time_est_ms"])
    print()

    # Análisis de timing del láser
    print("Análisis para burst a 100 Hz (pulso cada 10 ms):")
    pulso_interval = 10.0
    readings_per_second = 1000.0 / stats["mean_ms"]
    print("  Lecturas/segundo posibles: %.1f" % readings_per_second)
    print("  Ciclo Ocean: %.1f ms (integración %.1f + dead time %.1f)" % (
        stats["int_configured_ms"] + stats["dead_time_est_ms"],
        stats["int_configured_ms"],
        stats["dead_time_est_ms"]
    ))
    print("  Riesgo de aliasing: %s" % (
        "ALTO (ciclos múltiplos de 10 ms)" if abs((stats["mean_ms"] % pulso_interval)) < 1 else "BAJO"
    ))
    print()

    # Guardar CSV si se pide
    if args.out:
        try:
            # Agrupar por canal
            by_channel = {}
            for s in samples:
                ch = s["channel"]
                if ch not in by_channel:
                    by_channel[ch] = []
                by_channel[ch].append(s)

            with open(args.out, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "channel", "serial", "repeat", "elapsed_ms", "n_points",
                    "int_us", "timestamp"
                ])
                ts = datetime.now().isoformat()
                for s in samples:
                    writer.writerow([
                        s["channel"],
                        s["serial"],
                        s["repeats"],
                        round(s["elapsed_ms"], 3),
                        s["n_points"],
                        args.int_us,
                        ts,
                    ])
            print("CSV guardado: %s" % args.out)
            print()
        except Exception as e:
            print("ERROR guardando CSV: %s" % e)

    print("Medición completada.")
    print()
    print("Recomendaciones:")
    if stats["stdev_ms"] > stats["mean_ms"] * 0.1:
        print("  - Hay jitter significativo (%.1f%% del promedio)." % (
            100 * stats["stdev_ms"] / stats["mean_ms"]))
        print("    Verificar latencia de USB y carga del sistema.")
    else:
        print("  - Timing muy estable (jitter < 10%).")

    if stats["dead_time_est_ms"] < 1.0:
        print("  - Dead time bajo (< 1 ms) — timing ajustado.")
    elif stats["dead_time_est_ms"] > 5.0:
        print("  - Dead time alto (> 5 ms) — revisar overhead de seabreeze.")

    print()


if __name__ == "__main__":
    main()
