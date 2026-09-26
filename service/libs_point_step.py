"""
libs_point_step.py — LibsPointStep para el demo iberoLIBS 2026

Reemplaza LaserStep + SpectrometerStep en el pipeline del ScanRunner.
Usa el orden probado el 11/06/2026 con FIRE+ADQUIRIR:
    set_trigger_mode(3) → thread(spec.acquire) → fire_burst() → join()
    → set_trigger_mode(0)  ← reset garantizado en finally

Incluye:
  - Dark subtraction correcta (dark tomado previamente sin laser)
  - Visualización en tiempo real via SpectrumViewer (opcional)
  - Reset de trigger mode en finally (evita que el spec quede atrapado)
  - Guardado de CSV en session_dir/spectra/

Integración en build_pipeline():
    # ANTES (roto):
    LaserStep(), SpectrometerStep()

    # DESPUÉS:
    LibsPointStep()

Integración en scan_start() / ScanContext:
    ctx.spectrum_viewer = SpectrumViewer(root)   # puede ser None
    ctx.spectrometer_params["active_dark"] = dark_dict  # tomado antes del scan
"""

import os
import csv
import threading
import time
from typing import Optional

# Importar desde la arquitectura existente
# (ajustar ruta según estructura real del proyecto)
try:
    from service.scan_service import Step, StepResult, ScanContext, _parse_integration_ms
except ImportError:
    # Fallback para tests standalone
    class Step:
        name = ""
        critical = False
        def run(self, ctx): ...

    class StepResult:
        def __init__(self, step_name=""):
            self.step_name = step_name
            self.ok = True
            self.error = None
            self.data = {}
            self.duration_s = 0.0
            self.critical = False

    def _parse_integration_ms(params, default_ms=5.0):
        """Fallback: parsea integración sin importar scan_service."""
        int_us = params.get("integration_us")
        int_ms = params.get("integration_ms")
        if int_us is not None:
            if int_ms is not None:
                print("[WARN] Ambos integration_us e integration_ms presentes; usando integration_us")
            return float(int_us) / 1000.0
        elif int_ms is not None:
            return float(int_ms)
        else:
            return default_ms


# ─────────────────────────────────────────────────────────────────────────────

class LibsPointStep(Step):
    """
    Adquisición LIBS para un punto del scan: disparo sincronizado + espectro.

    Orden garantizado (crítico para trigger TTL modo 3):
      1. set_trigger_mode(3)  en todos los canales del espectrometro
      2. Thread spec.acquire()  ← bloqueado esperando flanco TTL
      3. laser.fire_burst()     ← genera flanco TTL
      4. thread.join(timeout)
      5. set_trigger_mode(0)    ← SIEMPRE, en finally

    Si ctx.spectrum_viewer existe, muestra raw y neto en tiempo real.
    Si ctx.spectrometer_params["active_dark"] existe, calcula neto = raw - dark.
    """

    name     = "libs_point"
    critical = False      # un fallo de espectro no detiene el scan

    # ── Parámetros con defaults ───────────────────────────────────────────────
    DEFAULT_INTEGRATION_MS = 5.0  # Cambió de 2.1 µs (mínimo HR2000+) a 5.0 ms (razonable para LIBS)
    DEFAULT_N_PULSOS       = 1
    TIMEOUT_EXTRA_S        = 15.0   # margen sobre integration_ms para el join

    # ── run() ─────────────────────────────────────────────────────────────────

    def run(self, ctx: "ScanContext") -> "StepResult":
        t0     = time.time()
        result = StepResult(step_name=self.name)

        spec  = getattr(ctx, "spectrometer", None)
        laser = getattr(ctx, "laser", None)

        # ── Validaciones ──────────────────────────────────────────────────────
        if laser is None or not getattr(laser, "is_connected", False):
            result.ok    = False
            result.error = "Láser no configurado o no conectado."
            result.critical = False
            result.duration_s = time.time() - t0
            return result

        if spec is None or not getattr(spec, "is_connected", False):
            # Sin espectrometro: solo disparar (útil para test de laser)
            _log(ctx, "WARN LibsPointStep: sin espectrometro — solo disparo.")
            fire_r = laser.fire_burst(
                int((ctx.laser_params or {}).get("n_pulsos", self.DEFAULT_N_PULSOS))
            )
            result.ok   = fire_r.get("ok", False)
            result.data = {"fire": fire_r, "spectrometer": "absent"}
            result.duration_s = time.time() - t0
            return result

        # ── Parámetros ────────────────────────────────────────────────────────
        sp     = ctx.spectrometer_params or {}
        lp     = ctx.laser_params        or {}
        int_ms = _parse_integration_ms(sp, self.DEFAULT_INTEGRATION_MS)
        n_puls = int(lp.get("n_pulsos", self.DEFAULT_N_PULSOS))
        dark   = sp.get("active_dark")        # dict | None
        viewer = getattr(ctx, "spectrum_viewer", None)

        timeout_s = int_ms / 1000.0 + self.TIMEOUT_EXTRA_S

        # ── Directorio de salida ──────────────────────────────────────────────
        spectra_dir = os.path.join(getattr(ctx, "session_dir", "."), "spectra")
        os.makedirs(spectra_dir, exist_ok=True)
        spec._output_dir = spectra_dir

        # ── Secuencia sincronizada ────────────────────────────────────────────
        acq = {"data": None, "error": None}

        try:
            # 1. Modo trigger externo (TTL, flanco descendente)
            spec.set_trigger_mode(3)
            _log(ctx, f"LibsPointStep: trigger_mode=3 | int={int_ms}ms | n={n_puls}")

            # 2. Iniciar thread de adquisición PRIMERO — queda bloqueado esperando TTL
            def _acquire():
                try:
                    acq["data"] = spec.acquire(
                        integration_ms=int_ms,
                        averages=1,
                    )
                except Exception as e:
                    acq["error"] = repr(e)

            acq_thread = threading.Thread(target=_acquire, daemon=True)
            acq_thread.start()
            time.sleep(2.314)   # head-start: asegura que el espectrómetro ya está leyendo antes de disparar

            # 3. Disparar laser — genera el flanco TTL que desbloquea el thread
            fire_result = laser.fire_burst(n_puls)
            fire_ok     = bool(fire_result.get("ok", False))
            _log(ctx, f"LibsPointStep: fire_burst ok={fire_ok}")

            # 4. Esperar a que el thread de adquisición termine
            acq_thread.join(timeout=timeout_s)

        finally:
            # 5. SIEMPRE resetear a free-running — sin esto el spec queda atrapado
            try:
                spec.set_trigger_mode(0)
                _log(ctx, "LibsPointStep: trigger_mode=0 (reset)")
            except Exception as e:
                _log(ctx, f"WARN LibsPointStep: no se pudo resetear trigger_mode: {e}")

        # ── Procesar resultado ────────────────────────────────────────────────
        raw = acq["data"]

        if acq_thread.is_alive():
            result.ok    = False
            result.error = f"Timeout ({timeout_s:.0f}s): trigger TTL no llegó."
            _log(ctx, "LibsPointStep: " + result.error)
            result.data  = {"fire": fire_result, "raw": None, "neto": None}
            result.duration_s = time.time() - t0
            return result

        if acq["error"]:
            result.ok    = False
            result.error = f"Error en acquire(): {acq['error']}"
            _log(ctx, "LibsPointStep: " + result.error)
            result.data  = {"fire": fire_result, "raw": None, "neto": None}
            result.duration_s = time.time() - t0
            return result

        if raw is None or not raw.get("ok"):
            result.ok    = False
            result.error = "acquire() devolvió None o ok=False."
            _log(ctx, "LibsPointStep: " + result.error)
            result.data  = {"fire": fire_result, "raw": raw, "neto": None}
            result.duration_s = time.time() - t0
            return result

        # ── Mostrar raw en viewer ─────────────────────────────────────────────
        if viewer is not None:
            viewer.update(raw, "raw")

        # ── Dark subtraction ──────────────────────────────────────────────────
        neto = None
        if dark is not None:
            try:
                neto = _subtract_dark(raw, dark)
                if viewer is not None:
                    viewer.update(neto, "neto")
                _log(ctx, "LibsPointStep: dark subtraction OK")
            except Exception as e:
                _log(ctx, f"WARN LibsPointStep: dark subtraction falló: {e}")

        # ── CSV ya está guardado por spec.acquire() ───────────────────────────
        csv_raw  = raw.get("csv_path", "")
        csv_neto = None

        # ── Opcionalmente: guardar CSV del neto si hay dark subtraction ────────
        if neto:
            ts      = time.strftime("%Y%m%d_%H%M%S")
            pt_tag  = getattr(getattr(ctx, "pr", None), "point_id", "pt")
            csv_neto = os.path.join(spectra_dir, f"espectro_neto_{pt_tag}_{ts}.csv")
            _save_spectrum_csv(neto, csv_neto)

        # ── Resumen para el JSON del punto ────────────────────────────────────
        ch_summary = _build_channel_summary(raw)

        result.ok   = True
        result.data = {
            "fire":         fire_result,
            "n_pulsos":     n_puls,
            "integration_ms": int_ms,
            "trigger_mode": 3,
            "channels_raw": ch_summary,
            "csv_raw":      csv_raw,
            "csv_neto":     csv_neto,
            "dark_applied": dark is not None,
            # Campos del loop+keep-best (para verificación en laboratorio)
            "n_frames_read":    raw.get("n_frames_read", 1),
            "best_frame_index": raw.get("best_frame_index"),
            "best_peak_value":  raw.get("best_peak_value", 0.0),
            "saturated":        raw.get("saturated", False),
        }
        result.duration_s = time.time() - t0
        _log(ctx, f"LibsPointStep: OK — {len(ch_summary)} canal(es) en {result.duration_s:.2f}s")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _subtract_dark(raw: dict, dark: dict) -> dict:
    """
    Devuelve neto = raw - dark canal por canal.
    Solo resta los canales que existen en ambos y tienen la misma longitud.
    """
    raw_ch  = raw.get("channels",  {})
    dark_ch = dark.get("channels", {})
    neto_ch = {}

    for ch, raw_data in raw_ch.items():
        dark_data = dark_ch.get(ch)
        if dark_data is None:
            neto_ch[ch] = raw_data   # sin dark para este canal → pasar tal cual
            continue

        r_ints = raw_data.get("intensities",  [])
        d_ints = dark_data.get("intensities", [])

        if len(r_ints) != len(d_ints):
            neto_ch[ch] = raw_data   # longitudes distintas → no restar
            continue

        neto_ints = [r - d for r, d in zip(r_ints, d_ints)]
        neto_ch[ch] = {
            **raw_data,
            "intensities": neto_ints,
        }

    return {
        **raw,
        "channels": neto_ch,
        "dark_subtracted": True,
    }


def _build_channel_summary(spectrum: dict) -> dict:
    """Resumen compacto por canal para guardar en el JSON del punto."""
    summary = {}
    for ch, data in spectrum.get("channels", {}).items():
        ints = data.get("intensities", [])
        if not ints:
            summary[ch] = {"ok": False, "reason": "empty"}
            continue
        summary[ch] = {
            "range_nm":      data.get("range_nm"),
            "max_intensity": round(max(ints), 1),
            "mean_intensity": round(sum(ints) / len(ints), 1),
            "n_points":      len(ints),
        }
    return summary


def _save_spectrum_csv(spectrum: dict, path: str) -> None:
    """Guarda todas las intensidades de todos los canales en un CSV multi-columna."""
    channels = spectrum.get("channels", {})
    if not channels:
        return

    # Todas las longitudes de onda del primer canal con datos
    wl_ref    = None
    wl_ref_ch = None
    for ch, data in channels.items():
        wls = data.get("wavelengths", [])
        if wls:
            wl_ref    = wls
            wl_ref_ch = ch
            break

    if wl_ref is None:
        return

    with open(path, "w", newline="") as f:
        writer = csv.writer(f)

        # Encabezado
        header = [f"wavelength_nm_ch{wl_ref_ch}"]
        for ch in channels:
            header.append(f"intensity_counts_ch{ch}")
        writer.writerow(header)

        # Datos (fila por pixel)
        n = len(wl_ref)
        ch_ints = {ch: data.get("intensities", []) for ch, data in channels.items()}
        for i in range(n):
            row = [round(wl_ref[i], 4)]
            for ch in channels:
                ints = ch_ints.get(ch, [])
                row.append(round(ints[i], 2) if i < len(ints) else "")
            writer.writerow(row)


def _log(ctx, msg: str) -> None:
    """Intenta loggear via ctx.log_fn o print."""
    try:
        log_fn = getattr(ctx, "log_fn", None)
        if callable(log_fn):
            log_fn(msg)
        else:
            print(msg)
    except Exception:
        print(msg)
