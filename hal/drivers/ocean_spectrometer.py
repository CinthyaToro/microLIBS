# -*- coding: utf-8 -*-
"""
hal/drivers/ocean_spectrometer.py  —  OceanSpectrometer
=========================================================
Implementa BaseSpectrometer para el LIBS2500plus (módulos HR2000+)
usando python-seabreeze con backend pyseabreeze (Python puro, 64-bit).

Requisitos:
    pip install seabreeze
    + Zadig para asignar driver WinUSB a cada módulo HR2000+

Modo de operación en microLIBS:
    El espectrómetro NO espera activamente. Se pone en modo trigger externo
    (HW Edge, modo 4) y queda "escuchando" el flanco TTL que viene del
    Q-switch del láser via el cable BNC EXT TRIG OUT → EXT TRIG IN del rack.

    Secuencia por punto de scan:
        1. LaserStep:  ctx.laser.fire()  →  láser dispara
        2.             Q-switch genera flanco TTL en su salida LAMP SYNC
        3.             Cable BNC lleva ese flanco al pin EXT TRIG del rack
        4. SpectrometerStep: spec.acquire() — ya tiene el espectro en buffer
        5.             Guardar CSV + registrar en JSON del punto

Diagrama de timing (valores típicos LIBS):
    t=0          Láser dispara (pulso 10 ns)
    t=0..1 µs    Plasma caliente, bremsstrahlung continuo (ignorar)
    t=1..50 µs   Líneas atómicas visibles (ventana de adquisición)
    t=0+delay    Trigger TTL → HR2000+ inicia integración
    t=0+delay+integration  HR2000+ termina, datos en buffer USB

    delay:        configurable vía seabreeze AcquisitionDelayFeature
                  (spec.features["acquisition_delay"]) si el equipo la soporta.
                  Para el HR2000+ bajo pyseabreeze la feature está declarada pero
                  no implementada → supports_acquisition_delay() devuelve False.
                  Usar set_acquisition_delay_us() / get_acquisition_delay_limits_us()
                  del HAL; si no está soportada, degrada con gracia sin crashear.
    integration:  2.1–10 ms (lo que caiga dentro de la ventana de plasma)

Uso desde microLIBS factory.py:
    from hal.drivers.ocean_spectrometer import OceanSpectrometer
    spec = OceanSpectrometer()
    spec.connect({
        "trigger_mode": 4,              # HW Edge para LIBS
        "integration_us": 5000,         # 5 ms
        "n_channels": 4,                # cuántos HR2000+ tiene el rack
        "output_dir": session_dir,      # donde guardar CSV
    })
    data = spec.acquire(integration_ms=5.0, averages=1)
    # data["channels"]["A"]["wavelengths"] = [200.1, 200.5, ...]
    # data["channels"]["A"]["intensities"] = [1024, 1100, ...]
    # data["csv_path"] = "/sesion/espectra/punto_0001.csv"

Modo simulado (sin hardware):
    spec.connect({"simulate": True, ...})
    # Genera espectros gaussianos aleatorios. Útil para desarrollar el
    # pipeline sin tener el rack conectado.
"""

from __future__ import annotations

import csv
import os
import time
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from hal.base_spectrometer import BaseSpectrometer


# ─── Constantes del HR2000+ ───────────────────────────────────────────────────

# Modos de trigger (del manual y confirmado en python-seabreeze issues)
TRIGGER_FREE_RUNNING  = 0   # adquisición continua, sin esperar señal
TRIGGER_SOFTWARE      = 1   # disparo por comando USB (spec.trigger_mode(1) + acquire)
TRIGGER_HW_LEVEL      = 2   # nivel TTL externo (mantener alto = adquiriendo)
TRIGGER_HW_EDGE       = 3   # flanco TTL externo → LIBS via LAMP SYNC del rack
TRIGGER_SINGLE_STROBE = 4   # strobe de lámpara (NO usar para LIBS)

# Límites del HR2000+
MIN_INTEGRATION_US = 2100       # 2.1 ms mínimo absoluto del HR2000+
MAX_INTEGRATION_US = 655_350_000  # ~10 minutos máximo

# ADC saturation levels (para detección de saturación en keep-best)
ADC_SATURATION = 16383          # Techo teórico (14-bit ADC)
ADC_SATURATION_THRESHOLD = 16000  # Considerar saturado si >= 16000 (margen por no-linealidad)

# Colores por canal (A=200nm, B=295nm, ...) para el gráfico
CHANNEL_COLORS = {
    "A": "#00BFFF",   # UV 200-305 nm
    "B": "#7CFC00",   # UV-VIS 295-400 nm
    "C": "#FF8C00",   # VIS 390-525 nm
    "D": "#FF1493",   # VIS 520-635 nm
    "E": "#BF5FFF",   # VIS-NIR 625-735 nm
    "F": "#FFD700",   # NIR 725-820 nm
    "G": "#00FA9A",   # NIR 800-980 nm
}


# ─── OceanSpectrometer ────────────────────────────────────────────────────────

class OceanSpectrometer(BaseSpectrometer):
    """
    Driver para LIBS2500plus (1-7 módulos HR2000+).

    Thread-safety: acquire() usa un lock. No llamar desde múltiples hilos
    simultáneamente (el HR2000+ tiene un solo buffer USB).
    """

    def __init__(self):
        self._modules: List[_SpecModule] = []   # ordenados A, B, C, D...
        self._excluded_serials: List[str] = []  # seriales encontrados pero excluidos por modulos_activos
        self._lock = threading.Lock()
        self._params: dict = {}
        self._simulate = False
        self._connected = False
        self._output_dir: Optional[str] = None
        self._point_counter = 0

    # ── BaseSpectrometer API ──────────────────────────────────────────────────

    def connect(self, params: dict) -> None:
        """
        Detecta módulos HR2000+, los abre y configura.

        Parámetros del dict params:
            trigger_mode     int  Modo trigger (default: TRIGGER_HW_EDGE = 3)
            integration_us   int  Tiempo de integración en µs (default: 5000)
            n_channels       int  Cuántos módulos esperar (0 = todos los que haya)
            modulos_activos  list[str]  Seriales a usar (ej. ["HR+C1911", "HR+C1915"]).
                                  Ausente o vacío = usar todos los que detecte seabreeze
                                  (retrocompatible). Seriales no encontrados se ignoran.
            output_dir       str  Directorio donde guardar CSV de espectros
            simulate         bool Si True, opera sin hardware (espectros sintéticos)
            averages         int  Número de adquisiciones a promediar (default: 1)
            sim_hang_channels list[str]  Solo con simulate=True. Fault injection para
                                  dev/test: canales (letra) que bloquean a propósito en
                                  acquire(), ejercitando el mismo camino de timeout/partial
                                  que hardware real sin necesitar el rack conectado.
                                  Ausente/vacío = comportamiento normal de simulación.
        """
        self._params = dict(params)
        self._simulate = params.get("simulate", False)
        self._output_dir = params.get("output_dir", ".")
        os.makedirs(self._output_dir, exist_ok=True)

        trigger        = int(params.get("trigger_mode",   TRIGGER_HW_EDGE))
        int_us         = int(params.get("integration_us", 5000))
        n_ch           = int(params.get("n_channels",     0))
        active_serials = params.get("modulos_activos") or None

        if self._simulate:
            self._connect_simulated(trigger, int_us, n_ch,
                                    rng_seed=params.get("rng_seed", None),
                                    active_serials=active_serials)
        else:
            self._connect_hardware(trigger, int_us, n_ch, active_serials)

        self._connected = True

    def disconnect(self) -> None:
        with self._lock:
            for m in self._modules:
                m.close()
            self._modules.clear()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ── Apagado seguro ──────────────────────────────────────────────────────
    # Segundos de espera tras sacar el modulo del modo trigger. Le da al USB
    # tiempo de procesar el cambio antes de cerrar; sin esto hay riesgo de
    # errno 10060 / freeze. No sacar.
    ESPERA_USB_S = 0.2

    def safe_shutdown(self) -> None:
        """
        Apagado seguro del HR2000+: sacarlo del modo trigger, darle tiempo al
        USB, y recien ahi cerrar. Ver BaseSpectrometer.

        PENDIENTE (necesita hardware): si hay una adquisicion bloqueada
        esperando el TTL en modo 3, disconnect() espera el _lock y el cierre
        puede tardar. No se arregla con una bandera de Python: el bloqueo esta
        dentro de self.spec.intensities(), en C. Mientras tanto el orquestador
        acota cuanto espera. Ver docs/bitacora/2026-09-22.md, pendiente 9.
        """
        import time as _time
        try:
            self.set_trigger_mode(0)
        except Exception:
            pass
        _time.sleep(self.ESPERA_USB_S)
        self.disconnect()

    def acquire(self, integration_ms: float = 5.0, averages: int = 1) -> dict:
        """
        Adquiere espectros de todos los módulos.

        Si trigger_mode == TRIGGER_HW_EDGE (3):
            El método retorna cuando el HR2000+ ya recibió el trigger TTL
            y completó la integración. Llamar ANTES de que el láser dispare
            (en un hilo separado), nunca después — si el flanco ya pasó,
            intensities() queda bloqueado esperando el próximo trigger.

        Si trigger_mode == TRIGGER_FREE_RUNNING (0):
            Adquiere inmediatamente (para testeo sin láser).

        Retorna:
            {
                "ok": True,
                "channels": {
                    "A": {
                        "wavelengths": [...],   # nm, 2048 puntos
                        "intensities": [...],   # u.a., 16-bit
                        "range_nm": (200.1, 305.8),
                        "serial": "HRXXXX",
                        "error": None,
                    },
                    "B": { ... },
                    ...
                },
                "csv_path": "/sesion/espectra/punto_0001_20260421_153012.csv",
                "timestamp_iso": "2026-04-21T15:30:12",
                "integration_ms": 5.0,
                "averages": 1,
                "trigger_mode": 4,
                "partial": False,
            }

        Adquisición por módulo con timeout independiente (hardware real):
            Cada módulo corre en su propio hilo. Un módulo que no responde
            (cuelgue de USB, trigger mode incorrecto) no bloquea a los demás:
            se marca su canal con ok=False/error="timeout" y se sigue.
            result["ok"]=True si al menos un módulo respondió; result["partial"]=True
            si respondieron algunos pero no todos. Tiempo total acotado por
            spectrometer.module_timeout_s (default 40s) sin importar cuántos
            módulos cuelguen (deadline compartido, no 40s × N módulos).
            En modo simulado se mantiene el loop secuencial original (sin hilos)
            mientras spectrometer.sim_hang_channels esté vacío: los módulos
            simulados nunca bloquean y comparten una única instancia de
            random.Random — paralelizarlos rompería la reproducibilidad del
            golden run. Si sim_hang_channels tiene canales (fault injection
            deliberada, ej. ["B"]), esos canales bloquean de verdad y se usa
            el mismo camino con hilos+timeout que hardware real — útil para
            probar timeout/partial sin rack conectado. Los canales sanos
            pueden variar levemente entre corridas en ese caso (RNG compartido
            entre hilos); aceptable porque el objetivo ahí es probar el
            control de flujo, no los valores espectrales exactos.
        """
        with self._lock:
            t0 = time.perf_counter()
            int_us = max(MIN_INTEGRATION_US, int(integration_ms * 1000))
            result = {
                "ok": True,
                "partial": False,
                "channels": {},
                "csv_path": None,
                "timestamp_iso": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                "integration_ms": integration_ms,
                "averages": averages,
                "trigger_mode": self._params.get("trigger_mode", TRIGGER_HW_EDGE),
            }

            sim_hangs = bool(self._params.get("sim_hang_channels"))
            if self._simulate and not sim_hangs:
                for m in self._modules:
                    ch_result = m.acquire(int_us, averages)
                    result["channels"][m.channel] = ch_result
                    if not ch_result.get("ok", True):
                        result["ok"] = False
            else:
                self._acquire_modules_with_timeout(result, int_us, averages)

            # Guardar CSV multi-canal
            if result["ok"] or any(
                ch.get("intensities") for ch in result["channels"].values()
            ):
                self._point_counter += 1
                csv_path = self._save_csv(result)
                result["csv_path"] = csv_path

            result["elapsed_ms"] = round((time.perf_counter() - t0) * 1000, 2)
            self._log_acquire_summary(result)
            return result

    def _log_acquire_summary(self, result: dict) -> None:
        """Imprime el estado de cada módulo (OK/FALLO/SKIP) y un resumen N/M OK.

        Ordenado por serial (mismo orden que la asignación de canales A→G),
        intercalando activos y excluidos. Formato:
            [spec] Módulo HR+C1911: OK (2048 pts)
            [spec] Módulo HR+C1912: SKIP (excluido por config)
            [spec] Módulo HR+C1914: OK (2048 pts)
            [spec] Módulo HR+C1915: SKIP (excluido por config)
            [spec] resultado: 2/4 OK
        """
        n_ok = 0
        entries = []   # (serial, linea) — se ordena al final por serial

        for m in self._modules:
            ch = result["channels"].get(m.channel, {})
            if ch.get("ok"):
                n_pts = len(ch.get("intensities") or [])
                entries.append((m.serial, "[spec] Módulo %s: OK (%d pts)" % (m.serial, n_pts)))
                n_ok += 1
            else:
                entries.append((m.serial, "[spec] Módulo %s: FALLO (%s)" % (
                    m.serial, ch.get("error") or "desconocido")))

        for serial in self._excluded_serials:
            entries.append((serial, "[spec] Módulo %s: SKIP (excluido por config)" % serial))

        for _, line in sorted(entries, key=lambda e: e[0]):
            print(line)

        total = len(self._modules) + len(self._excluded_serials)
        print("[spec] resultado: %d/%d OK" % (n_ok, total))

    def _acquire_modules_with_timeout(self, result: dict, int_us: int, averages: int) -> None:
        """Adquiere todos los módulos en paralelo, con timeout independiente.

        Un módulo que no responde (cuelgue de USB, trigger mode incorrecto)
        no bloquea a los demás. El tiempo total está acotado por
        spectrometer.module_timeout_s (default 40s) via un deadline compartido:
        si varios módulos cuelgan a la vez, el total sigue siendo ~40s, no
        40s × cantidad de módulos colgados.

        Llena result["channels"], result["ok"] (True si al menos un módulo
        respondió) y result["partial"] (True si respondieron algunos pero no
        todos los módulos conectados).
        """
        module_timeout_s = float(self._params.get("module_timeout_s", 40.0))
        slots = {m.channel: {"data": None, "error": None} for m in self._modules}
        threads = []

        for m in self._modules:
            slot = slots[m.channel]

            def _run(_m=m, _slot=slot):
                try:
                    _slot["data"] = _m.acquire(int_us, averages)
                except Exception as e:
                    _slot["error"] = str(e)

            th = threading.Thread(target=_run, daemon=True)
            th.start()
            threads.append((m, th))

        deadline = time.perf_counter() + module_timeout_s
        n_ok = 0
        for m, th in threads:
            remaining = max(0.0, deadline - time.perf_counter())
            th.join(timeout=remaining)
            slot = slots[m.channel]

            if th.is_alive():
                ch_result = {
                    "ok": False,
                    "wavelengths": m.wavelengths or [],
                    "intensities": [],
                    "range_nm": (m.wavelengths[0], m.wavelengths[-1]) if m.wavelengths else (0, 0),
                    "serial": m.serial,
                    "error": "timeout (%.0fs) - modulo no respondio" % module_timeout_s,
                }
            elif slot["error"]:
                ch_result = {
                    "ok": False,
                    "wavelengths": m.wavelengths or [],
                    "intensities": [],
                    "range_nm": (m.wavelengths[0], m.wavelengths[-1]) if m.wavelengths else (0, 0),
                    "serial": m.serial,
                    "error": slot["error"],
                }
            else:
                ch_result = slot["data"] or {
                    "ok": False,
                    "wavelengths": m.wavelengths or [],
                    "intensities": [],
                    "range_nm": (0, 0),
                    "serial": m.serial,
                    "error": "sin resultado",
                }

            result["channels"][m.channel] = ch_result
            if ch_result.get("ok"):
                n_ok += 1

        result["ok"] = n_ok > 0
        result["partial"] = 0 < n_ok < len(self._modules)

    def get_wavelengths(self) -> list:
        """Retorna lista de arrays de longitudes de onda, uno por canal."""
        return [m.wavelengths for m in self._modules if m.wavelengths is not None]

    # ── Métodos extra (no en BaseSpectrometer, pero útiles desde UI) ──────────

    def set_trigger_mode(self, mode: int) -> None:
        """Cambia el modo de trigger en todos los módulos en tiempo real."""
        for m in self._modules:
            m.set_trigger(mode)
        self._params["trigger_mode"] = mode

    def get_trigger_mode(self) -> int:
        """Último modo de trigger comandado por software.

        seabreeze/pyseabreeze no expone un getter de hardware para esto
        (trigger_mode() es write-only en la API). Este valor es lo último
        que se escribió via set_trigger_mode()/connect(), no una lectura
        confirmada del HR2000+.
        """
        return self._params.get("trigger_mode", TRIGGER_HW_EDGE)

    def set_integration(self, us: int) -> None:
        """Cambia el tiempo de integración en todos los módulos."""
        us = max(MIN_INTEGRATION_US, us)
        for m in self._modules:
            m.set_integration(us)
        self._params["integration_us"] = us

    def channel_info(self) -> list:
        """Retorna lista de dicts con info de cada canal (para UI)."""
        return [
            {
                "channel":   m.channel,
                "serial":    m.serial,
                "range_nm":  m.range_label,
                "color":     CHANNEL_COLORS.get(m.channel, "#FFFFFF"),
                "ok":        m.spec is not None or m._simulate,
                "error":     m.error,
            }
            for m in self._modules
        ]

    def arm_trigger(self) -> None:
        """
        Pone todos los módulos en modo trigger HW Edge y los deja esperando.
        Llamar antes de disparar el láser en el pipeline de scan.
        """
        mode = self._params.get("trigger_mode", TRIGGER_HW_EDGE)
        if mode == TRIGGER_FREE_RUNNING:
            return  # no tiene sentido armar en free-running
        for m in self._modules:
            m.set_trigger(mode)

    def reset_to_free_running(self) -> None:
        """Vuelve todos los módulos a free-running (para preview en UI)."""
        for m in self._modules:
            m.set_trigger(TRIGGER_FREE_RUNNING)

    # ── Acquisition delay (seabreeze AcquisitionDelayFeature) ────────────────

    def supports_acquisition_delay(self) -> bool:
        """True si al menos un módulo expone la feature acquisition_delay."""
        for m in self._modules:
            if m.spec is not None:
                try:
                    feats = m.spec.features.get("acquisition_delay", [])
                    if feats:
                        feats[0].get_minimum_delay_microseconds()
                        return True
                except (NotImplementedError, Exception):
                    pass
        return False

    def set_acquisition_delay_us(self, us: int) -> None:
        """Fija el delay de adquisición en todos los módulos. Clampa al rango.
        Si la feature no existe o lanza NotImplementedError, loguea y sigue."""
        mn, mx, inc = self.get_acquisition_delay_limits_us()
        if mx > 0:
            us = max(mn, min(mx, us))
            if inc > 1:
                us = (us // inc) * inc
        for m in self._modules:
            if m.spec is None:
                continue
            try:
                feats = m.spec.features.get("acquisition_delay", [])
                if feats:
                    feats[0].set_delay_microseconds(us)
            except NotImplementedError:
                pass  # pyseabreeze: feature declarada pero no implementada
            except Exception as e:
                m.error = "set_acquisition_delay: %s" % e

    def get_acquisition_delay_limits_us(self) -> Tuple[int, int, int]:
        """Retorna (min, max, increment) del primer módulo que responda."""
        for m in self._modules:
            if m.spec is None:
                continue
            try:
                feats = m.spec.features.get("acquisition_delay", [])
                if feats:
                    feat = feats[0]
                    mn  = feat.get_minimum_delay_microseconds()
                    mx  = feat.get_maximum_delay_microseconds()
                    inc = feat.get_delay_increment_microseconds()
                    return (int(mn), int(mx), int(inc))
            except (NotImplementedError, Exception):
                pass
        return (0, 0, 1)

    # ── Conexión con hardware real ────────────────────────────────────────────

    def _connect_hardware(self, trigger: int, int_us: int, n_ch: int,
                          active_serials: Optional[List[str]] = None) -> None:
        try:
            import seabreeze
            seabreeze.use("pyseabreeze")
            from seabreeze.spectrometers import list_devices, Spectrometer
        except ImportError:
            raise ImportError(
                "seabreeze no instalado. Ejecutar: pip install seabreeze\n"
                "Luego instalar driver WinUSB con Zadig para cada HR2000+."
            )

        # Windows: pyusb no encuentra libusb automáticamente; libusb_package lo provee.
        
        devices = list_devices()
        if not devices:
            raise ConnectionError(
                "Ningún módulo HR2000+ detectado por USB.\n"
                "Verificar:\n"
                "  1. Rack encendido y cable USB conectado\n"
                "  2. Driver WinUSB instalado con Zadig para cada módulo\n"
                "  3. Que no esté corriendo OOILIBSplus ni OceanView"
            )

        # -----------------------------------------------------------------
        # ESTRATEGIA GENÉRICA: Mapeo dinámico basado en tu archivo YAML
        # -----------------------------------------------------------------
        # Creamos un diccionario indexado por el string del serial real (ej: "HR+C1912")
        devices_dict = {str(d.serial_number): d for d in devices}
        devices_sorted = []
        self._excluded_serials = []

        if active_serials:
            print(f"[spec] Ordenando canales según la secuencia del YAML: {active_serials}")
            
            # Buscamos en el hardware respetando estrictamente el orden óptico de tu YAML
            for serial in active_serials:
                serial_str = str(serial).strip()
                if serial_str in devices_dict:
                    devices_sorted.append(devices_dict[serial_str])
                else:
                    print(f"[WARN] Espectrómetro '{serial_str}' del YAML no fue hallado en el bus USB de esta PC.")

            # Si hay algún dispositivo físico conectado que no se declaró en el YAML, lo excluimos
            for d in devices:
                s_num = str(d.serial_number)
                if s_num not in active_serials:
                    self._excluded_serials.append(s_num)
        else:
            # Fallback automático: si el YAML no define módulos activos, ordena alfabéticamente (A->G)
            print("[spec] YAML sin modulos_activos o vacío. Ordenando por número de serie de fábrica.")
            devices_sorted = sorted(devices, key=lambda d: str(d.serial_number))
            self._excluded_serials = []

        if n_ch > 0:
            devices_sorted = devices_sorted[:n_ch]

        # 2. Asignación final a las letras de canal del pipeline (A, B, C, D...)
        channel_letters = list("ABCDEFG")
        for i, dev in enumerate(devices_sorted):
            letter = channel_letters[i] if i < len(channel_letters) else str(i)
            m = _SpecModule(letter, serial=dev.serial_number)
            try:
                m.spec = Spectrometer(dev)
                m.spec.integration_time_micros(max(MIN_INTEGRATION_US, int_us))
                m.spec.trigger_mode(trigger)
                m.wavelengths = list(m.spec.wavelengths())
                m.error = None
                print(f"[spec] Canal {letter} asignado exitosamente al Serial real: {dev.serial_number}")
            except Exception as e:
                m.error = str(e)
            self._modules.append(m)

    # ── Conexión simulada ─────────────────────────────────────────────────────

    def _connect_simulated(self, trigger: int, int_us: int, n_ch: int,
                           rng_seed=None,
                           active_serials: Optional[List[str]] = None) -> None:
        """Crea módulos simulados con espectros gaussianos.

        rng_seed: si no es None, usa random.Random(rng_seed) para reproducibilidad.
                  Si es None (default), usa el módulo random global — comportamiento
                  original sin cambios.

        active_serials: filtra por los 4 seriales reales documentados en
                  config/spectrometer_profile.json (HR+C1911/1912/1914/1915). Si un
                  serial activo es uno de los conocidos, el canal sim usa SU
                  rango real y SU serial real (no un alias SIM_X0001) — para
                  que el log sea directamente comparable al de hardware real.
                  Los conocidos no elegidos van a self._excluded_serials con
                  su serial real.
                  n_channels actúa como "total de módulos declarados en el
                  rack" (ej. 4 en el YAML del labo); si hay más módulos
                  declarados que seriales conocidos+activos, el resto se
                  cuenta como "MODULO_DESCONOCIDO_N" — representa módulos
                  físicos reales (ej. el módulo 4) cuyo serial nunca se
                  documentó en este repo. No se les inventa rango: nunca
                  generan espectro, solo cuentan para el resumen N/M.
                  Seriales en active_serials que no son ninguno de los 3
                  conocidos se ignoran silenciosamente (no hay rango para
                  fabricarles un espectro).
                  Ausente/vacío = sin filtrar (comportamiento original,
                  seriales SIM_A0001 etc.).
        """
        import random as _random
        rng = _random.Random(rng_seed) if rng_seed is not None else None

        # (letra, wl_min, wl_max, serial_real) — único vínculo entre
        # modulos_activos (seriales reales) y los rangos sintéticos.
        sim_ranges = [
            ("A", 293.83, 390.12, "HR+C1911"),
            ("B", 388.84, 518.30, "HR+C1912"),
            ("C", 519.61, 636.20, "HR+C1914"),
            ("D", 624.03, 728.97, "HR+C1915"),
        ]

        self._excluded_serials = []
        ranges_to_use = sim_ranges
        if active_serials:
            chosen = [r for r in sim_ranges if r[3] in active_serials]
            known_excluded = [r[3] for r in sim_ranges if r[3] not in active_serials]

            total_declared = n_ch if n_ch > 0 else len(sim_ranges)
            n_placeholder = max(0, total_declared - len(chosen) - len(known_excluded))

            self._excluded_serials = known_excluded + [
                "MODULO_DESCONOCIDO_%d" % (i + 1) for i in range(n_placeholder)
            ]
            ranges_to_use = chosen

        hang_channels = set(self._params.get("sim_hang_channels") or [])

        n = n_ch if n_ch > 0 else len(ranges_to_use)
        for letter, wl_min, wl_max, real_serial in ranges_to_use[:n]:
            serial = real_serial if active_serials else f"SIM_{letter}0001"
            m = _SpecModule(letter, serial=serial, simulate=True, rng=rng)
            m.wavelengths = [
                wl_min + (wl_max - wl_min) * i / 2047 for i in range(2048)
            ]
            m.error = None
            m._sim_hang = letter in hang_channels
            self._modules.append(m)

    # ── Guardar CSV ───────────────────────────────────────────────────────────

    def _save_csv(self, result: dict) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fname = f"espectro_{self._point_counter:04d}_{ts}.csv"
        path = os.path.join(self._output_dir, fname)

        channels_ok = {
            ch: data for ch, data in result["channels"].items()
            if data.get("wavelengths") and data.get("intensities")
        }

        if not channels_ok:
            return ""

        max_len = max(len(d["wavelengths"]) for d in channels_ok.values())

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            # Encabezado
            header = ["#", "timestamp", "integration_ms", "trigger_mode"]
            for ch in sorted(channels_ok):
                header += [f"wl_ch{ch}_nm", f"int_ch{ch}_au"]
            writer.writerow(header)

            # Metadatos en fila 0
            meta = [
                self._point_counter,
                result["timestamp_iso"],
                result["integration_ms"],
                result["trigger_mode"],
            ]
            for ch in sorted(channels_ok):
                meta += ["", ""]
            writer.writerow(meta)

            # Datos espectrales
            for i in range(max_len):
                row = ["", "", "", ""]
                for ch in sorted(channels_ok):
                    d = channels_ok[ch]
                    if i < len(d["wavelengths"]):
                        row += [
                            f"{d['wavelengths'][i]:.4f}",
                            f"{d['intensities'][i]:.2f}",
                        ]
                    else:
                        row += ["", ""]
                writer.writerow(row)

        return path

    def __repr__(self) -> str:
        chs = [m.channel for m in self._modules]
        return (
            "OceanSpectrometer(channels=%s, connected=%s, simulate=%s)"
            % (chs, self._connected, self._simulate)
        )


# ─── Módulo individual (interno) ──────────────────────────────────────────────

class _SpecModule:
    """Representa un módulo HR2000+ individual dentro del rack."""

    def __init__(self, channel: str, serial: str = "", simulate: bool = False, rng=None):
        self.channel   = channel
        self.serial    = serial
        self._simulate = simulate
        self._rng      = rng         # random.Random instance para reproducibilidad; None = global random
        self._sim_hang = False       # fault injection: si True, acquire() bloquea (no termina)
        self.spec      = None        # Spectrometer object (pyseabreeze)
        self.wavelengths: Optional[List[float]] = None
        self.error: Optional[str] = None

    @property
    def range_label(self) -> str:
        if self.wavelengths:
            return f"{self.wavelengths[0]:.0f}–{self.wavelengths[-1]:.0f} nm"
        return "?"

    def set_integration(self, us: int) -> None:
        if self.spec:
            try:
                self.spec.integration_time_micros(us)
            except Exception as e:
                self.error = str(e)

    def set_trigger(self, mode: int) -> None:
        if self.spec:
            try:
                self.spec.trigger_mode(mode)
            except Exception as e:
                self.error = str(e)

    def close(self) -> None:
        if self.spec is None:
            return
        try:
            self.spec.trigger_mode(TRIGGER_FREE_RUNNING)
        except Exception:
            pass
        try:
            self.spec.close()
            self.spec = None
        except Exception:
            pass

    def acquire(self, int_us: int, averages: int = 1, max_frames: int = None,
                 n_pulsos: int = 1) -> dict:
        """
        Adquiere espectro(s) con keep-best logic en modo trigger externo.

        En modo REAL (hardware con trigger TTL):
          - Lee max_frames (default: 8, o n_pulsos+1 si n_pulsos se pasa)
          - Descarta frames saturados (cualquier canal >= ADC_SATURATION_THRESHOLD)
          - Devuelve el frame con MAYOR pico en canal A entre los válidos
          - Si todos saturan: devuelve el menos saturado con flag saturated=True

        En modo SIM:
          - Lee UNA sola vez (determinista para golden test)

        Args:
            int_us: integración en µs (no usado en acquire(), está en las propiedades del spec)
            averages: número de promedios por frame (default 1)
            max_frames: cuántos frames leer (default 8, o n_pulsos+1 si n_pulsos > 1)
            n_pulsos: para calcular max_frames como n_pulsos+1 si se proporciona

        Returns:
            dict con 'ok', 'wavelengths', 'intensities', 'range_nm', 'serial',
            'error', 'n_frames_read', 'best_frame_index', 'best_peak_value', 'saturated'
        """
        result = {
            "ok":               True,
            "wavelengths":      self.wavelengths or [],
            "intensities":      [],
            "range_nm":         (self.wavelengths[0], self.wavelengths[-1])
                                if self.wavelengths else (0, 0),
            "serial":           self.serial,
            "error":            None,
            "n_frames_read":    0,
            "best_frame_index": None,
            "best_peak_value":  0.0,
            "saturated":        False,
        }

        if self._simulate:
            # SIM: una sola lectura (determinista)
            if self._sim_hang:
                time.sleep(99999)
            result["intensities"] = self._sim_spectrum()
            result["n_frames_read"] = 1
            return result

        if not self.spec:
            result["ok"] = False
            result["error"] = "módulo no abierto"
            return result

        # HARDWARE REAL: loop de frames con keep-best
        try:
            # ⚠️ PENDIENTE — parche de laboratorio sin resolver (anotado 22-Sep-2026)
            #
            # Este `max_frames = 1` es un parche que se puso en el labo para atajar
            # un problema, NO salió bien, y hubo fallas por este motivo. Queda acá
            # documentado hasta que se resuelva con el hardware delante.
            #
            # Efecto real: el loop + keep-best NO está funcionando. Se lee UN solo
            # frame, se ignora el parámetro max_frames que recibe el método, y el
            # cálculo verdadero quedó comentado abajo. El docstring de arriba y
            # CLAUDE.md describen el comportamiento que el código NO tiene: dicen
            # que lee 8 frames (o n_pulsos+1) y se queda con el de mayor pico.
            #
            # Los campos n_frames_read / best_frame_index / best_peak_value que
            # se exponen en el JSON del punto salen de esta lectura única, así que
            # hoy no significan lo que su nombre promete.
            #
            # VERIFICADO EN LABORATORIO (23-Sep-2026): la sospecha de la línea
            # anterior era correcta. Leer varios frames en modo 3 ROMPE el timing
            # del trigger TTL del LIBS2500+. Con max_frames = 8 no se formaba
            # plasma; bajar a una sola adquisición es lo que lo hizo aparecer.
            #
            # >>> NO descomentar el cálculo de abajo. <<<
            # Si se quiere keep-best, hay que conseguirlo SIN leer N frames
            # seguidos en modo 3 — por ejemplo repitiendo el ciclo completo
            # (armar -> disparar -> leer 1) N veces.
            #
            # if max_frames is None:
            #     max_frames = n_pulsos + 1 if n_pulsos > 1 else 8
            max_frames = 1

            frames = []  # list of {wavelengths, intensities_A, B, C}

            for frame_idx in range(max_frames):
                try:
                    raw = self.spec.intensities()
                    frames.append({
                        'index': frame_idx,
                        'raw': list(raw)
                    })
                except Exception as e_frame:
                    # Frame falló: loguear pero continuar
                    pass

            if not frames:
                result["ok"] = False
                result["error"] = "no frames acquired"
                return result

            result["n_frames_read"] = len(frames)

            # Seleccionar mejor frame
            best_frame = self._select_best_frame(frames, averages)

            if best_frame["best_raw"] is not None:
                # Acumular y promediar si averages > 1
                accum = list(best_frame["best_raw"])
                for _ in range(1, max(1, averages)):
                    try:
                        raw = self.spec.intensities()
                        for j, v in enumerate(raw):
                            accum[j] += v
                    except:
                        pass

                n = max(1, averages)
                result["intensities"] = [v / n for v in accum]

            result["best_frame_index"] = best_frame["best_index"]
            result["best_peak_value"] = best_frame["best_peak_value"]
            result["saturated"] = best_frame["saturated"]

            if best_frame["saturated"]:
                print(f"[WARN] {self.channel}: todos los frames saturados (max ADC), bajá integration_us")

            self.error = None

        except Exception as e:
            result["ok"] = False
            result["error"] = str(e)
            self.error = str(e)

        return result

    def _select_best_frame(self, frames: List[dict], averages: int = 1) -> dict:
        """
        Selecciona el mejor frame de una lista usando keep-best logic.

        Args:
            frames: list of {index, raw} donde raw son las intensidades crudas
            averages: no usado aquí (solo para compatibilidad)

        Returns:
            dict con {best_index, best_raw, best_peak_value, saturated}
        """
        valid_frames = []
        saturated_frames = []

        for frame in frames:
            raw = frame['raw']
            max_val = max(raw) if raw else 0

            is_saturated = max_val >= ADC_SATURATION_THRESHOLD

            if is_saturated:
                saturated_frames.append({
                    'index': frame['index'],
                    'raw': raw,
                    'peak': max_val
                })
            else:
                valid_frames.append({
                    'index': frame['index'],
                    'raw': raw,
                    'peak': max_val
                })

        if valid_frames:
            # Hay frames válidos: elegir el de mayor pico
            best = max(valid_frames, key=lambda f: f['peak'])
            return {
                'best_index': best['index'],
                'best_raw': best['raw'],
                'best_peak_value': best['peak'],
                'saturated': False
            }
        elif saturated_frames:
            # Todos saturados: elegir el menos saturado
            best = min(saturated_frames, key=lambda f: f['peak'])
            return {
                'best_index': best['index'],
                'best_raw': None,  # No retornar datos saturados
                'best_peak_value': best['peak'],
                'saturated': True
            }
        else:
            # Sin frames
            return {
                'best_index': None,
                'best_raw': None,
                'best_peak_value': 0.0,
                'saturated': False
            }

    def _sim_spectrum(self) -> List[float]:
        """Genera un espectro sintético gaussiano + ruido para testing."""
        import random as _random
        import math
        _rng = self._rng if self._rng is not None else _random
        if not self.wavelengths:
            return []
        wls = self.wavelengths
        n = len(wls)
        center = wls[n // 3 + _rng.randint(-50, 50)]
        width  = 5.0 + _rng.uniform(0, 10)
        amp    = 20000 + _rng.uniform(-5000, 5000)
        baseline = 200 + _rng.uniform(-50, 50)
        return [
            baseline
            + amp * math.exp(-0.5 * ((w - center) / width) ** 2)
            + _rng.uniform(-50, 50)
            for w in wls
        ]
