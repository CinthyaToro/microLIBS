# -*- coding: utf-8 -*-
"""
scan_runner.py  —  Orquestador de scan microLIBS  (v1.5)
==========================================================

Responsabilidad única: ejecutar un scan_plan.json punto a punto,
coordinando en secuencia los subsistemas disponibles:

    MOVER  →  VERIFICAR POSICIÓN  →  CAPTURA_PRE  →  LASER (EKSPLA)
    →  ESPECTRÓMETRO (Ocean)  →  CAPTURA_POST  →  LOG JSON

Diseño:
  - Cada "paso" del scan es una lista de Steps (objetos con .run()).
  - Un Step que falla escribe el error en el JSON pero NO interrumpe
    los demás Steps del mismo punto (a menos que sea crítico).
  - El runner corre en un thread de fondo. La UI llama a
    start() / stop() y suscribe un callback on_progress para actualizarse.
  - Para agregar láser o espectrómetro: crear una subclase de Step
    y agregarlo a la lista pipeline en ScanRunner.__init__().

Compatibilidad de hardware:
  - Stage MoVi  (ejes X, Y)  →  Z ignorado automáticamente.
  - Stage Thorlabs (ejes X, Y, Z) → Z usado si está en el plan.
  - Cámara webcam (OpenCV) o Chameleon (FlyCapture) → mismo VisionController.

Verificación de calidad:
  - Verificación de movimiento: compara posición pedida vs posición real
    (Thorlabs) o posición trackeada (MoVi). Registra delta en JSON.
  - Verificación de captura: comprueba que el archivo existe y tiene
    tamaño > umbral. Registra en JSON.
  - Si el archivo de captura es idéntico al anterior (mismo hash MD5),
    registra advertencia "frame_frozen" en el JSON.
Laser: Se debe ejecutar antes laser_server.py con python de 32bits

Espectrómetro: se esta desarrollando
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from service.libs_point_step import LibsPointStep


# ---------------------------------------------------------------------------
# Helper para parsear integración (fix de unidades)
# ---------------------------------------------------------------------------

def _parse_integration_ms(params: dict, default_ms: float = 5.0) -> float:
    """
    Parsea tiempo de integración desde params (dict del YAML).

    Lee integration_us CON PRIORIDAD. Si no existe, intenta integration_ms.
    Si existen ambas, avisa warning.

    Args:
        params: dict de configuración (ej. exp_cfg.get("spectrometer", {}))
        default_ms: default en milisegundos si no encuentra ninguno

    Returns:
        Integración en milisegundos (float)
    """
    int_us = params.get("integration_us")
    int_ms = params.get("integration_ms")

    if int_us is not None:
        # Prioridad a integration_us (correcto en YAML)
        if int_ms is not None:
            # Ambas presentes: warning
            print("[WARN] Ambos integration_us e integration_ms presentes; usando integration_us")
        return float(int_us) / 1000.0
    elif int_ms is not None:
        # Si solo integration_ms (retrocompatibilidad)
        return float(int_ms)
    else:
        # Ninguno presente: default
        return default_ms


# ---------------------------------------------------------------------------
# Resultado de un Step individual
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    step_name: str
    ok: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration_s: float = 0.0


# ---------------------------------------------------------------------------
# Resultado completo de un punto del scan
# ---------------------------------------------------------------------------

@dataclass
class PointResult:
    point_index: int          # 1-based
    point: dict               # {i, x, y, ...} del scan_plan
    timestamp_iso: str = ""
    steps: List[StepResult] = field(default_factory=list)
    overall_ok: bool = True
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "point_index": self.point_index,
            "point":       self.point,
            "timestamp_iso": self.timestamp_iso,
            "overall_ok":  self.overall_ok,
            "notes":       self.notes,
            "steps": [
                {
                    "step": r.step_name,
                    "ok":   r.ok,
                    "duration_s": round(r.duration_s, 4),
                    "data": r.data,
                    "error": r.error,
                }
                for r in self.steps
            ],
        }


# ---------------------------------------------------------------------------
# Steps base
# ---------------------------------------------------------------------------

class Step:
    """Clase base para todos los pasos del pipeline."""

    name: str = "base_step"
    critical: bool = False   # Si True, un fallo detiene el punto completo.

    def run(self, ctx: "ScanContext") -> StepResult:
        raise NotImplementedError


class MoveStep(Step):
    """
    Mueve la plataforma a la posición del punto actual (coordenadas en mm).

    El scan_plan DEBE tener x_mm / y_mm calculados con la escala correcta
    (px/mm ingresada en el preview). Si no existen o están fuera del rango
    físico del stage, el step se omite con advertencia — no envía comandos
    imposibles al hardware.

    Rango físico por defecto: 0.0–4.0 mm (MoVi). Ajustable con RANGE_MM.
    Tolerancia de verificación: 0.05 mm (50 µm) para MoVi sin encoder.
    """

    name = "move"
    critical = True
    TOLERANCE_MM = 0.05      # 50 um (MoVi no tiene encoder, trackea internamente)
    RANGE_MM = (-0.1, 4.1)   # rango por defecto (Thorlabs); sobreescrito en run() segun driver

    # Rangos fisicos por driver importados desde factory.
    # MoVi: acepta negativos (origen puede estar en cualquier punto del recorrido).
    # Thorlabs: solo positivos (home = limite fisico = 0 mm).
    KNOWN_RANGES = {
        "movi":         (-35.0, 35.0),   # rango total 35 mm, origen variable
        "thorlabs":     (  0.0,  4.0),   # home=0, solo positivos
        "thorlabs_sim": (  0.0,  4.0),
        "sim":          (-50.0, 50.0),
    }

    def run(self, ctx: "ScanContext") -> StepResult:
        t0 = time.time()
        result = StepResult(step_name=self.name)

        if ctx.stage is None:
            result.data["skipped"] = "no stage connected"
            return result

        pt = ctx.current_point

        # Leer coordenadas mm del plan.
        x_mm = pt.get("x_mm")
        y_mm = pt.get("y_mm")

        if x_mm is None and y_mm is None:
            result.data["skipped"] = (
                "plan sin coordenadas mm — solo tiene px. "
                "Ingresa la escala px/mm en el preview antes de exportar el plan."
            )
            # NO es error crítico: captura igual en la posición actual
            result.ok = True
            result.duration_s = time.time() - t0
            ctx.pr.notes.append(
                "INFO move: sin coordenadas mm, no se movió el stage. "
                "Verifica la escala px/mm en el preview."
            )
            return result

        # Validar rango antes de enviar cualquier comando
        _driver = ctx.stage.__class__.__name__.lower().replace("stage", "")
        _rng = self.KNOWN_RANGES.get(_driver, (-35.0, 35.0))
        rmin, rmax = _rng[0], _rng[1]
        out_of_range = {}
        for axis, val in [("x", x_mm), ("y", y_mm)]:
            if val is None:
                continue
            fval = float(val)
            if not (rmin <= fval <= rmax):
                out_of_range[axis] = fval

        if out_of_range:
            msg = (
                "Coordenadas mm fuera del rango fisico del stage "
                "(%.1f-%.1f mm): %s. "
                "Probablemente la escala px/mm es incorrecta (escala=1 => px=mm). "
                "Corrige la escala en el preview y vuelve a exportar el plan."
                % (rmin, rmax, out_of_range)
            )
            result.ok = False
            result.error = msg
            ctx.pr.notes.append("ERROR move: " + msg)
            result.duration_s = time.time() - t0
            return result

        requested = {}
        errors = {}

        # ── Inversión Y para stages con eje físico invertido respecto de imagen ──
        # Se detecta por nombre de driver (Thorlabs) o por profile.invert_y_axis.
        _driver = ctx.stage.__class__.__name__.lower().replace("stage", "").strip()
        _inv_y = getattr(ctx, "invert_y_axis", None)
        if _inv_y is None:
            _inv_y = _driver in ("thorlabs",)
        if _inv_y and y_mm is not None:
            yr = self.KNOWN_RANGES.get(_driver, (0.0, 4.0))
            y_mm = yr[0] + yr[1] - float(y_mm)
            result.data["y_inverted"] = True

        for axis, val_mm in [("x", x_mm), ("y", y_mm)]:
            if val_mm is None:
                continue
            if not ctx.stage.has_axis(axis):
                result.data[f"{axis}_skipped"] = "eje no disponible en este stage"
                continue
            try:
                ctx.stage.move_abs(axis, float(val_mm))
                requested[axis] = float(val_mm)
            except Exception as e:
                errors[axis] = repr(e)
                result.ok = False

        # Verificar posición real post-movimiento
        pos_real = {}
        deltas = {}
        for axis, req in requested.items():
            try:
                real = ctx.stage.position(axis)
                pos_real[axis] = real
                deltas[axis] = round(abs(real - req), 6)
                if deltas[axis] > self.TOLERANCE_MM:
                    msg = f"posición {axis}: pedida={req:.4f} real={real:.4f} delta={deltas[axis]:.4f} mm"
                    result.notes.append(f"WARN move: {msg}")
                    ctx.pr.notes.append(f"WARN move: {msg}")
            except Exception as e:
                pos_real[axis] = None
                deltas[axis] = None

        result.data.update({
            "requested_mm": requested,
            "real_mm":      pos_real,
            "delta_mm":     deltas,
            "move_errors":  errors,
        })
        if errors:
            result.error = str(errors)
        result.duration_s = time.time() - t0
        return result


class SettleStep(Step):
    """Espera un tiempo de estabilización después del movimiento."""

    name = "settle"
    critical = False

    def run(self, ctx: "ScanContext") -> StepResult:
        t0 = time.time()
        time.sleep(max(0.0, ctx.settle_s))
        return StepResult(
            step_name=self.name,
            duration_s=time.time() - t0,
            data={"settle_s": ctx.settle_s},
        )


class CaptureStep(Step):
    """
    Captura una imagen (PRE o POST) y verifica:
    - El archivo existe y tiene tamaño > MIN_BYTES.
    - El frame no está congelado (hash MD5 distinto al anterior).
    """

    MIN_BYTES = 1024   # < 1 KB → probablemente frame vacío

    def __init__(self, kind: str = "pre"):
        self.kind = kind          # "pre" | "post"
        self.name = f"capture_{kind}"
        self.critical = True

    def run(self, ctx: "ScanContext") -> StepResult:
        t0 = time.time()
        result = StepResult(step_name=self.name)

        extra = {
            "sample_name":   ctx.sample_name,
            "operator":      ctx.operator,
            "session_dir":   ctx.session_dir,
            "scan_point_index": ctx.current_point_index,
            "scan_point":    ctx.current_point,
            "microLIBS_kind": self.kind,
        }

        try:
            out = ctx.vc.request_capture(
                save_dir=ctx.images_dir,
                base_name=ctx.base_name,
                kind=self.kind,
                extra_meta=extra,
            )
            path = out.get("image_path", "")
            result.data["image_path"] = path

            # Verificar existencia y tamaño
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Archivo de imagen no encontrado: {path}")
            size = os.path.getsize(path)
            result.data["file_size_bytes"] = size
            if size < self.MIN_BYTES:
                result.ok = False
                result.error = f"Imagen demasiado pequeña ({size} bytes) — posible frame vacío."
                ctx.pr.notes.append(f"WARN capture_{self.kind}: {result.error}")
            else:
                # Verificar frame congelado (mismo hash que captura anterior del mismo kind)
                md5 = _md5(path)
                result.data["md5"] = md5
                prev_key = f"last_md5_{self.kind}"
                if ctx.shared.get(prev_key) == md5:
                    warn = "frame_frozen: imagen idéntica a la captura anterior"
                    result.data["frame_frozen"] = True
                    result.ok = False
                    result.error = warn
                    ctx.pr.notes.append(f"WARN capture_{self.kind}: {warn}")
                else:
                    result.data["frame_frozen"] = False
                ctx.shared[prev_key] = md5

        except Exception as e:
            result.ok = False
            result.error = repr(e)
            ctx.pr.notes.append(f"ERROR capture_{self.kind}: {repr(e)}")

        result.duration_s = time.time() - t0
        return result


# ---------------------------------------------------------------------------
# Steps futuros — skeleton listo para implementar
# ---------------------------------------------------------------------------

class SimDwellStep(Step):
    """
    Simula el disparo del láser + adquisición espectral cuando el hardware
    real no está controlado aún.

    Se activa automáticamente en ScanRunner cuando profile.laser_controlled
    y profile.spectrometer_controlled son False.

    Parámetro: ctx.sim_dwell_ms (default: 500 ms).
    Registra en el JSON que es una adquisición simulada.
    """

    name = "sim_dwell"
    critical = False

    def run(self, ctx: "ScanContext") -> StepResult:
        t0 = time.time()
        dwell_s = max(0.0, ctx.shared.get("sim_dwell_ms", 500) / 1000.0)
        time.sleep(dwell_s)
        return StepResult(
            step_name=self.name,
            data={"simulated": True, "dwell_ms": dwell_s * 1000},
            duration_s=time.time() - t0,
        )


class LaserStep(Step):
    """
    Dispara el láser en el punto actual del scan.

    Requiere que ctx.laser sea un objeto BaseLaser (LaserProxy o SimLaser)
    ya conectado y armado. Si ctx.laser es None, el step se omite con
    advertencia (igual que antes para compatibilidad con scans sin láser).

    Parámetros leídos de ctx.laser_params:
        pulse_us   — ancho de pulso en µs (informativo para el NL230)
        delay_us   — delay adicional en µs después de habilitar output
        arm_each   — si True, arma/desarma en cada punto (default: False)
                     Normalmente se arma una vez antes del scan.

    El resultado del disparo se guarda en el JSON del punto.
    Si el disparo falla y critical=True, el punto se cancela.
    """

    name     = "laser"
    critical = True   # un fallo de láser detiene el punto

    def run(self, ctx: "ScanContext") -> StepResult:
        t0 = time.time()
        result = StepResult(step_name=self.name)

        # Sin láser configurado → omitir silenciosamente
        if ctx.laser is None:
            result.data["skipped"] = "no laser configured"
            result.critical = False
            return result

        if not ctx.laser.is_connected:
            result.ok    = False
            result.error = "Láser no conectado (is_connected=False)."
            ctx.pr.notes.append("ERROR laser: %s" % result.error)
            result.duration_s = time.time() - t0
            return result

        params   = ctx.laser_params or {}
        pulse_us = int(params.get("pulse_us", 0))
        delay_us = int(params.get("delay_us", 0))
        arm_each = bool(params.get("arm_each", False))
        n_pulsos = int(params.get("n_pulsos", 1))

        try:
            # Armar por punto si se requiere
            if arm_each:
                ctx.laser.arm()

            # Disparo
            fire_result = ctx.laser.fire_burst(n_pulsos)

            result.data.update({
                "fire": fire_result,
                "n_pulsos": n_pulsos,
                "pulse_us": pulse_us,
                "delay_us": delay_us,
                "arm_each": arm_each,
            })

            if not fire_result.get("ok", False):
                result.ok    = False
                result.error = "fire_burst() falló: %s" % fire_result.get("error", "desconocido")
                ctx.pr.notes.append("ERROR laser: %s" % result.error)
            else:
                result.ok = True

            # Desarmar por punto si se requiere
            if arm_each:
                ctx.laser.disarm()

        except Exception as e:
            result.ok    = False
            result.error = "Excepción en LaserStep: %s" % repr(e)
            ctx.pr.notes.append("ERROR laser: %s" % result.error)

        result.duration_s = time.time() - t0
        return result


class SpectrometerStep(Step):
    name     = "spectrometer"
    critical = False

    def run(self, ctx: "ScanContext") -> StepResult:
        t0 = time.time()
        result = StepResult(step_name=self.name)

        spec = getattr(ctx, "spectrometer", None)
        if spec is None:
            result.data["skipped"] = "no spectrometer configured"
            return result

        if not spec.is_connected:
            result.ok    = False
            result.error = "Espectrómetro no conectado."
            ctx.pr.notes.append("ERROR spectrometer: no conectado")
            result.duration_s = time.time() - t0
            return result

        params         = ctx.spectrometer_params or {}
        integration_ms = _parse_integration_ms(params, default_ms=5.0)
        averages       = int(params.get("averages", 1))

        spectra_dir = os.path.join(ctx.session_dir, "spectra")
        os.makedirs(spectra_dir, exist_ok=True)
        spec._output_dir = spectra_dir

        try:
            acq = spec.acquire(integration_ms=integration_ms, averages=averages)
            result.ok = acq.get("ok", False)

            ch_summary = {}
            for ch, data in acq.get("channels", {}).items():
                if data.get("intensities"):
                    ints = data["intensities"]
                    ch_summary[ch] = {
                        "range_nm":      data.get("range_nm"),
                        "max_intensity": round(max(ints), 1),
                        "mean_intensity": round(sum(ints) / len(ints), 1),
                        "ok":            data.get("ok", True),
                        "error":         data.get("error"),
                    }

            result.data = {
                "channels":       ch_summary,
                "csv_path":       acq.get("csv_path"),
                "integration_ms": integration_ms,
                "averages":       averages,
                "trigger_mode":   acq.get("trigger_mode"),
                "elapsed_ms":     acq.get("elapsed_ms"),
            }

            if not result.ok:
                errors = [
                    f"ch{ch}: {d.get('error')}"
                    for ch, d in acq.get("channels", {}).items()
                    if d.get("error")
                ]
                result.error = "; ".join(errors) or "acquire() falló"
                ctx.pr.notes.append("WARN spectrometer: " + result.error)

        except Exception as e:
            result.ok    = False
            result.error = repr(e)
            ctx.pr.notes.append("ERROR spectrometer: " + repr(e))

        result.duration_s = time.time() - t0
        return result




class FocusStep(Step):
    """
    FUTURO: ajuste de foco en eje Z (sólo para stages con Z, como Thorlabs).
    Se activa automáticamente si ctx.stage.has_z() == True.
    """

    name = "focus_z"
    critical = False

    def run(self, ctx: "ScanContext") -> StepResult:
        if ctx.stage is None or not ctx.stage.has_z():
            return StepResult(step_name=self.name, data={"skipped": "sin eje Z"})
        return StepResult(
            step_name=self.name,
            data={"status": "not_implemented"},
        )


# ---------------------------------------------------------------------------
# Contexto compartido entre steps para un punto
# ---------------------------------------------------------------------------

class ScanContext:
    """
    Objeto que cada Step recibe en run().
    Contiene todo lo necesario para ejecutar sin depender de globales.
    """

    def __init__(
        self,
        vc,
        stage,
        images_dir: str,
        events_dir: str,
        session_dir: str,
        sample_name: str,
        operator: str,
        base_name: str,
        settle_s: float,
        laser_params: dict,
        spectrometer_params: dict,
        shared: dict,          # estado compartido entre puntos (hashes, contadores...)
        laser=None,            # instancia BaseLaser (LaserProxy o SimLaser), o None
        spectrometer=None,     # instancia el espectrometro
        invert_y_axis=None,    # True/False override; None = auto por nombre de driver
    ):
        self.vc = vc
        self.stage = stage
        self.laser = laser
        self.spectrometer  = spectrometer    # agregado 21Abr26
        self.invert_y_axis = invert_y_axis
        self.images_dir = images_dir
        self.events_dir = events_dir
        self.session_dir = session_dir
        self.sample_name = sample_name
        self.operator = operator
        self.base_name = base_name
        self.settle_s = settle_s
        self.laser_params = laser_params
        self.spectrometer_params = spectrometer_params
        self.shared = shared

        # Se actualizan por el runner antes de cada punto
        self.current_point: dict = {}
        self.current_point_index: int = 0
        self.pr: PointResult = None   # resultado del punto actual


# ---------------------------------------------------------------------------
# Runner principal
# ---------------------------------------------------------------------------

class ScanRunner:
    """
    Orquestador del scan microLIBS.

    Uso:
        runner = ScanRunner(vc=vc, stage=stage, ...)
        runner.on_progress = lambda pr: ui_update(pr)
        runner.start(points, max_points=0)
        # ...
        runner.stop()

    Pipeline por defecto:
        MoveStep → SettleStep → CaptureStep("pre")
        → LaserStep (skeleton) → SpectrometerStep (skeleton)
        → CaptureStep("post")

    Para agregar hardware real: sobreescribir build_pipeline() en una subclase
    o pasar pipeline= al constructor.
    """

    def __init__(
        self,
        vc,
        stage,
        images_dir: str,
        events_dir: str,
        session_dir: str,
        sample_name: str,
        operator: str,
        settle_s: float = 0.2,
        laser_params: Optional[dict] = None,
        spectrometer_params: Optional[dict] = None,
        stop_on_error: bool = True,
        pipeline: Optional[List[Step]] = None,
        sim_dwell_ms: int = 500,
        use_sim_dwell: bool = True,
        laser=None,    # instancia BaseLaser (LaserProxy o SimLaser), o None
        spectrometer=None,	# instancia el espectrometro
	invert_y_axis=None,  # None = auto por driver; True/False = override
    ):
        self._use_sim_dwell = use_sim_dwell
        self.ctx = ScanContext(
            vc=vc,
            stage=stage,
            images_dir=images_dir,
            events_dir=events_dir,
            session_dir=session_dir,
            sample_name=sample_name,
            operator=operator,
            base_name=_sanitize(sample_name),
            settle_s=settle_s,
            laser_params=laser_params or {},
            spectrometer_params=spectrometer_params or {},
            shared={"sim_dwell_ms": sim_dwell_ms},
            laser=laser,
	    spectrometer=spectrometer,
            invert_y_axis=invert_y_axis,
        )
        self.stop_on_error = stop_on_error
        self.pipeline: List[Step] = pipeline if pipeline is not None else self.build_pipeline()

        # Callbacks (asignables desde la UI)
        self.on_progress: Optional[Callable[[PointResult], None]] = None
        self.on_finished: Optional[Callable[[str], None]] = None
        self.on_log: Optional[Callable[[str], None]] = None

        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.running = False

    # ---- pipeline -------------------------------------------------------

    def build_pipeline(self) -> List[Step]:
        """
        Pipeline por defecto.

        Lógica de selección:
        - Si use_sim_dwell=True  → SimDwellStep (sin hardware de láser)
        - Si use_sim_dwell=False → LaserStep real (usa ctx.laser si está configurado)

        LaserStep ya maneja el caso ctx.laser=None omitiendo el disparo,
        por lo que es seguro incluso si el láser no está conectado.
        """
        if getattr(self, "_use_sim_dwell", True):
            return [
                MoveStep(),
                SettleStep(),
                CaptureStep("pre"),
                SimDwellStep(),   # simula laser+espectro con espera configurable
                FocusStep(),
                CaptureStep("post"),
            ]
        return [
            MoveStep(),
            SettleStep(),
            CaptureStep("pre"),
            LibsPointStep(),      # replaza LaserStep + SpectrometerStep
            FocusStep(),
            CaptureStep("post"),
        ]

    # ---- control --------------------------------------------------------

    def start(self, points: List[dict], max_points: int = 0) -> None:
        if self.running:
            return
        pts = points[:max_points] if (max_points and max_points > 0) else points
        if not pts:
            self._log("WARN scan_plan vacio -- nada que ejecutar.")
            return
        self._stop_flag.clear()
        self.running = True
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(pts,),
            daemon=True,
            name="ScanRunner",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_flag.set()
        self._log("STOP solicitado...")

    def join(self, timeout: float = None) -> None:
        if self._thread:
            self._thread.join(timeout=timeout)

    # ---- loop interno ---------------------------------------------------

    def _run_loop(self, points: List[dict]) -> None:
        total = len(points)
        self._log(f">> ScanRunner: {total} puntos | pipeline: {[s.name for s in self.pipeline]}")

        summary = {
            "total_points": total,
            "ok": 0,
            "warn": 0,
            "error": 0,
            "started_iso": _now_iso(),
            "finished_iso": None,
        }

        for idx, pt in enumerate(points):
            if self._stop_flag.is_set():
                self._log("STOP Loop detenido por usuario.")
                break

            pr = PointResult(
                point_index=idx + 1,
                point=pt,
                timestamp_iso=_now_iso(),
            )
            self.ctx.current_point = pt
            self.ctx.current_point_index = idx + 1
            self.ctx.pr = pr

            self._log(f"-> Punto {idx+1}/{total}: {pt}")

            point_abort = False
            _has_spec = any(isinstance(s, SpectrometerStep) for s in self.pipeline)

            for step in self.pipeline:
                if self._stop_flag.is_set():
                    point_abort = True
                    break

                try:
                    sr = step.run(self.ctx)
                except Exception as e:
                    sr = StepResult(
                        step_name=step.name,
                        ok=False,
                        error=repr(e),
                    )
                    pr.notes.append(f"EXCEPTION en step {step.name}: {repr(e)}")

                pr.steps.append(sr)

                if not sr.ok:
                    pr.overall_ok = False
                    self._log(f"  WARN Step '{sr.step_name}': {sr.error}")
                    if step.critical and self.stop_on_error:
                        pr.notes.append(f"ABORT: step crítico '{step.name}' falló.")
                        point_abort = True
                        break

            # Guardar JSON del punto
            suffix = "" if pr.overall_ok else "_WARN" if not point_abort else "_ERROR"
            log_path = os.path.join(
                self.ctx.events_dir,
                f"point_{pr.point_index:04d}_{_ts()}{suffix}.json"
            )
            try:
                _write_json(log_path, pr.to_dict())
            except Exception as e:
                self._log(f"  WARN No se pudo guardar log: {e}")

            if pr.overall_ok:
                summary["ok"] += 1
            elif point_abort:
                summary["error"] += 1
            else:
                summary["warn"] += 1

            self._log(
                f"  {'OK' if pr.overall_ok else 'WARN' if not point_abort else 'ERR'} "
                f"Punto {idx+1}: ok={pr.overall_ok} | {len(pr.notes)} notas"
            )

            if self.on_progress:
                try:
                    self.on_progress(pr)
                except Exception:
                    pass

            if point_abort and self.stop_on_error:
                self._log("ERR Stop on error: abortando scan.")
                break

        # Resumen final
        summary["finished_iso"] = _now_iso()
        summary_path = os.path.join(self.ctx.events_dir, "scan_summary.json")
        try:
            _write_json(summary_path, summary)
        except Exception:
            pass

        msg = (
            f"OK Scan finalizado: {summary['ok']} OK | "
            f"{summary['warn']} WARN | {summary['error']} ERROR"
        )
        self._log(msg)
        self.running = False

        if self.on_finished:
            try:
                self.on_finished(msg)
            except Exception:
                pass

    def _acquire_point_with_retry(
        self, max_attempts: int = 3, signal_threshold: float = 300
    ) -> tuple:
        """
        Dispara el láser y adquiere espectro con reintento automático.

        Orden correcto para trigger modo 3 (TTL hardware):
          a. spec.acquire() en Thread — queda bloqueado esperando el flanco TTL
          b. LaserStep.run()          — fire_burst genera el TTL
          c. join del thread con timeout
          d. evaluar p2p canal A; si < signal_threshold → reintentar

        Retorna (fire_sr, spec_sr, attempts_used).
        Si agota intentos: spec_sr.ok=False, spec_sr.data["nan_placeholder"]=True.
        El scan continúa en todos los casos (SpectrometerStep no es crítico).
        """
        ctx = self.ctx
        spec = getattr(ctx, "spectrometer", None)
        params = ctx.spectrometer_params or {}
        integration_ms = _parse_integration_ms(params, default_ms=5.0)
        averages = int(params.get("averages", 1))
        timeout_s = integration_ms / 1000.0 + 35.0

        if spec is not None and spec.is_connected:
            spectra_dir = os.path.join(ctx.session_dir, "spectra")
            os.makedirs(spectra_dir, exist_ok=True)
            spec._output_dir = spectra_dir

        last_fire_sr = StepResult(step_name="laser",
                                  data={"skipped": "no laser"})
        last_spec_sr = StepResult(step_name="spectrometer",
                                  data={"skipped": "no spectrometer"})
        p2p = 0.0

        for attempt in range(1, max_attempts + 1):
            self._log("[acq] intento %d/%d" % (attempt, max_attempts))

            # Sin espectrómetro: disparar y salir (no hay nada que validar)
            if spec is None or not spec.is_connected:
                fire_sr = LaserStep().run(ctx)
                last_fire_sr = fire_sr
                return last_fire_sr, last_spec_sr, attempt

            # a. Armar adquisición PRIMERO — queda bloqueado esperando TTL
            try:
                tm = spec.get_trigger_mode()
            except Exception as e:
                tm = "?(%s)" % e
            self._log("[acq] trigger_mode comandado=%s antes de armar (sin lectura de hardware, ver get_trigger_mode)" % tm)

            acq = {"data": None, "error": None}

            def _acquire(_acq=acq, ms=integration_ms, avg=averages):
                try:
                    _acq["data"] = spec.acquire(integration_ms=ms, averages=avg)
                except Exception as e:
                    _acq["error"] = str(e)

            acq_thread = threading.Thread(target=_acquire, daemon=True)
            acq_thread.start()

            # b. Disparar DESPUÉS (fire_burst genera el TTL que desbloquea acq_thread)
            fire_sr = LaserStep().run(ctx)
            last_fire_sr = fire_sr

            # c. Esperar que el espectro esté listo
            acq_thread.join(timeout=timeout_s)

            # Shutdown solicitado durante el join — salir sin reintentar
            if self._stop_flag.is_set():
                self._log("[acq] shutdown solicitado — abortando retry en intento %d" % attempt)
                ctx.pr.notes.append("spec: shutdown durante adquisicion, intento %d" % attempt)
                last_spec_sr.ok = False
                last_spec_sr.error = "shutdown durante adquisicion"
                return last_fire_sr, last_spec_sr, attempt

            # Fallo de laser — loguear, no abortar (el espectrómetro pudo haber captado algo)
            if not fire_sr.ok:
                self._log("[acq] fallo laser intento %d: %s" % (attempt, fire_sr.error))
                if attempt < max_attempts:
                    continue
                break

            if acq_thread.is_alive():
                self._log("[acq] timeout (%.0f s) — trigger no llego, intento %d"
                          % (timeout_s, attempt))
                if attempt < max_attempts:
                    continue
                break

            if acq["error"]:
                self._log("[acq] excepcion espectro intento %d: %s"
                          % (attempt, acq["error"]))
                last_spec_sr = StepResult(step_name="spectrometer",
                                          ok=False, error=acq["error"])
                if attempt < max_attempts:
                    continue
                break

            acq_data = acq["data"]
            if not acq_data:
                self._log("[acq] adquisicion vacia intento %d" % attempt)
                if attempt < max_attempts:
                    continue
                break

            # d. Validar señal — peak-to-peak canal A
            ch_a = acq_data.get("channels", {}).get("A", {})
            ints_a = ch_a.get("intensities", [])
            p2p = (max(ints_a) - min(ints_a)) if ints_a else 0.0
            self._log("[acq] p2p chA=%.0f (umbral=%.0f)" % (p2p, signal_threshold))

            ch_summary = {}
            for ch, cdata in acq_data.get("channels", {}).items():
                ints_ch = cdata.get("intensities", [])
                if ints_ch:
                    ch_summary[ch] = {
                        "range_nm":       cdata.get("range_nm"),
                        "max_intensity":  round(max(ints_ch), 1),
                        "mean_intensity": round(sum(ints_ch) / len(ints_ch), 1),
                        "ok":             cdata.get("ok", True),
                        "error":          cdata.get("error"),
                    }

            spec_sr = StepResult(step_name="spectrometer",
                                 ok=bool(acq_data.get("ok", False)))
            spec_sr.data = {
                "channels":       ch_summary,
                "csv_path":       acq_data.get("csv_path"),
                "integration_ms": integration_ms,
                "averages":       averages,
                "trigger_mode":   acq_data.get("trigger_mode"),
                "elapsed_ms":     acq_data.get("elapsed_ms"),
                "attempt":        attempt,
                "p2p_ch_a":       round(p2p, 1),
            }
            last_spec_sr = spec_sr

            if acq_data.get("ok") and p2p >= signal_threshold:
                ctx.pr.notes.append(
                    "spec: OK intento %d p2p=%.0f" % (attempt, p2p)
                )
                return last_fire_sr, last_spec_sr, attempt

            if attempt < max_attempts:
                self._log("[acq] senal insuficiente (p2p=%.0f<%.0f), reintentando..."
                          % (p2p, signal_threshold))

        # Intentos agotados — placeholder NaN para que el scan continúe
        ctx.pr.notes.append(
            "spec: sin senal en %d intentos (p2p=%.0f)" % (max_attempts, p2p)
        )
        last_spec_sr.ok = False
        last_spec_sr.error = "sin senal en %d intentos" % max_attempts
        last_spec_sr.data["nan_placeholder"] = True
        last_spec_sr.data["p2p_ch_a"] = round(p2p, 1)
        return last_fire_sr, last_spec_sr, max_attempts

    def _log(self, msg: str) -> None:
        print(f"[ScanRunner] {msg}")
        if self.on_log:
            try:
                self.on_log(msg)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------

def _md5(path: str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _ts() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _sanitize(name: str) -> str:
    name = (name or "").strip()
    bad = '<>:"/\\|?* '
    for ch in bad:
        name = name.replace(ch, "_")
    return name or "muestra"


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
