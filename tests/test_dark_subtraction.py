# -*- coding: utf-8 -*-
"""
tests/test_dark_subtraction.py
================================
Test redondo de resta de fondo (dark subtraction).

Verifica:
1. SimSpectrometer: modo 0 → baseline plana (sin picos), modo 3 → picos.
2. subtract_dark aritmética exacta canal por canal (clip_negative=False).
3. Integración completa: dark + señal → neto correcto en formato HAL.

No usa hardware ni UI. No modifica ningún golden.
"""

import pytest
import math


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mean(lst):
    return sum(lst) / len(lst) if lst else 0.0

def _max(lst):
    return max(lst) if lst else 0.0


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def sim_spec():
    from hal.drivers.sim_spectrometer import SimSpectrometer
    s = SimSpectrometer(rng_seed=42)
    s.connect({"n_channels": 3, "trigger_mode": 3})
    yield s
    s.disconnect()


# ── Tests ──────────────────────────────────────────────────────────────────────

def test_mode0_is_flat_baseline(sim_spec):
    """Modo free-running (0) → baseline plana, sin picos gaussianos."""
    sim_spec.set_trigger_mode(0)
    data = sim_spec.acquire(integration_ms=5.0)

    assert data["ok"], "acquire() en modo 0 debe retornar ok=True"
    channels = data["channels"]
    assert len(channels) == 3, "Deben existir 3 canales (A, B, C)"

    for ch_name, ch in channels.items():
        ints = ch["intensities"]
        assert len(ints) == 2048, "Canal %s: esperaba 2048 puntos" % ch_name
        mean_val = _mean(ints)
        max_val  = _max(ints)
        # Baseline plana: media ~200, max/mean ≈ 1.1 (solo ruido gaussiano ±25 cuentas)
        assert 100 < mean_val < 400, \
            "Canal %s: media del dark fuera de rango baseline (%.1f)" % (ch_name, mean_val)
        assert max_val < mean_val * 1.5, \
            "Canal %s: dark tiene pico sospechoso (max=%.1f, mean=%.1f)" % (
                ch_name, max_val, mean_val)


def test_mode3_has_peaks(sim_spec):
    """Modo HW-edge (3) → espectro con picos gaussianos >> baseline."""
    sim_spec.set_trigger_mode(3)
    data = sim_spec.acquire(integration_ms=5.0)

    assert data["ok"]
    for ch_name, ch in data["channels"].items():
        ints = ch["intensities"]
        mean_val = _mean(ints)
        max_val  = _max(ints)
        # Señal de plasma: pico al menos 2.5× la media (dark tiene ratio ≈ 1.1)
        assert max_val > mean_val * 2.5, \
            "Canal %s: señal sin pico detectable (max=%.1f, mean=%.1f)" % (
                ch_name, max_val, mean_val)


def test_subtract_dark_exact_arithmetic():
    """subtract_dark(clip_negative=False): neto == raw − dark, incluyendo negativos."""
    from spec_pipeline import subtract_dark

    raw_ch = {
        "channel":     "A",
        "serial":      "SIM_A0001",
        "wavelengths": [300.0, 301.0, 302.0],
        "intensities": [500.0, 300.0, 100.0],
    }
    dark_ch = {
        "channel":     "A",
        "serial":      "SIM_A0001",
        "wavelengths": [300.0, 301.0, 302.0],
        "intensities": [200.0, 350.0, 150.0],   # dark > raw en el tercer punto
    }

    net = subtract_dark(raw_ch, dark_ch, clip_negative=False)

    assert net["intensities"] == [300.0, -50.0, -50.0], \
        "Aritmética incorrecta: %s" % net["intensities"]
    assert net["dark_subtracted"] is True
    assert net["wavelengths"] == raw_ch["wavelengths"]   # longitudes de onda intactas


def test_subtract_dark_clip_negative_legacy():
    """subtract_dark(clip_negative=True): floor en 0 para compatibilidad con spec_probe."""
    from spec_pipeline import subtract_dark

    raw_ch  = {"channel": "B", "serial": "X", "wavelengths": [500.0],
               "intensities": [100.0]}
    dark_ch = {"channel": "B", "serial": "X", "wavelengths": [500.0],
               "intensities": [200.0]}   # dark > raw → negativo clippeado

    net = subtract_dark(raw_ch, dark_ch, clip_negative=True)
    assert net["intensities"] == [0.0], \
        "clip_negative=True debe retornar 0.0, no negativo"


def test_full_dark_subtraction_per_channel(sim_spec):
    """
    Test redondo: dark + señal → neto exacto canal por canal.

    Verifica:
      · Para cada canal: neto[i] == señal[i] − dark[i]  (aritmética exacta)
      · neto tiene media ~0 (los picos sobresalen del fondo)
      · La media del neto es mayor que la media del dark
        (hay señal real sobre el fondo)
    """
    from spec_pipeline import subtract_dark

    # Capturar dark en modo 0
    sim_spec.set_trigger_mode(0)
    dark_data = sim_spec.acquire(integration_ms=5.0)
    dark_channels = dark_data["channels"]

    # Capturar señal en modo 3
    sim_spec.set_trigger_mode(3)
    signal_data = sim_spec.acquire(integration_ms=5.0)
    signal_channels = signal_data["channels"]

    assert set(dark_channels) == set(signal_channels), \
        "Dark y señal deben tener los mismos canales"

    for ch_name in sorted(dark_channels):
        raw_ch  = signal_channels[ch_name]
        dark_ch = dark_channels[ch_name]

        net_ch = subtract_dark(raw_ch, dark_ch, clip_negative=False)
        net_ints    = net_ch["intensities"]
        raw_ints    = raw_ch["intensities"]
        dark_ints   = dark_ch["intensities"]

        # Aritmética exacta punto a punto
        expected = [r - d for r, d in zip(raw_ints, dark_ints)]
        for i, (got, exp) in enumerate(zip(net_ints, expected)):
            assert math.isclose(got, exp, rel_tol=1e-9), \
                "Canal %s, punto %d: neto=%.6f, esperado=%.6f" % (
                    ch_name, i, got, exp)

        # El neto debe tener picos (señal real sobre fondo ya restado)
        max_net  = _max(net_ints)
        mean_net = _mean(net_ints)
        assert max_net > mean_net * 2.5, \
            "Canal %s: neto sin pico visible (max=%.1f, mean=%.1f)" % (
                ch_name, max_net, mean_net)


def test_sign_pico_raw_mayor_dark_es_positivo():
    """
    El orden de la resta DEBE ser raw − dark (señal − fondo).
    Con raw > dark en la zona del pico, el neto debe ser positivo.

    Si alguien invierte el signo a dark − raw, el pico aparece como
    valle negativo (el bug reportado: picos como valles de −10000 cuentas).
    """
    from spec_pipeline import subtract_dark

    N = 20
    baseline = 300.0
    peak_amp = 10000.0
    peak_idx = 10

    dark_ch = {
        "channel":     "A",
        "serial":      "SIM_A",
        "wavelengths": list(range(N)),
        "intensities": [baseline] * N,          # dark: plano, sin picos
    }
    raw_ch = {
        "channel":     "A",
        "serial":      "SIM_A",
        "wavelengths": list(range(N)),
        "intensities": [
            baseline + (peak_amp if i == peak_idx else 0.0)
            for i in range(N)
        ],                                       # raw: baseline + pico LIBS
    }

    net = subtract_dark(raw_ch, dark_ch, clip_negative=False)
    net_ints = net["intensities"]

    # El pico debe ser POSITIVO (raw − dark = peak_amp, no dark − raw = −peak_amp)
    assert net_ints[peak_idx] > 0, (
        "Signo incorrecto en la sustraccion: neto en el pico = %.1f "
        "(debe ser +%.0f; se esta calculando dark-raw en lugar de raw-dark)"
        % (net_ints[peak_idx], peak_amp)
    )
    # Amplitud correcta: raw_peak − dark_baseline = peak_amp
    assert abs(net_ints[peak_idx] - peak_amp) < 1e-6, (
        "Amplitud del pico neto incorrecta: %.1f, esperado %.1f"
        % (net_ints[peak_idx], peak_amp)
    )
    # El resto del neto debe ser ~0 (baseline − baseline)
    for i, v in enumerate(net_ints):
        if i != peak_idx:
            assert abs(v) < 1e-6, (
                "Punto %d: neto=%.6f, esperado 0.0 (baseline se cancela)" % (i, v)
            )
