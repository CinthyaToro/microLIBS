# -*- coding: utf-8 -*-
"""
hal/drivers/thorlabs_stage.py
Driver para stages Thorlabs Kinesis (BSC10x/BSC20x/BSC103).
Requiere: pip install pythonnet + Thorlabs Kinesis SDK instalado.
Parámetros de connect(): {"serial": "70123456", "channels": 3,
                           "poll_ms": 250, "vel_mm_s": 2.0,
                           "acc_mm_s2": 4.0,
                           "axis_map": {"x":1, "y":2, "z":3}}
"""
import os
import sys
import time
from hal.base_stage import BaseStage

KINESIS_DIRS = [
    r"C:\Program Files\Thorlabs\Kinesis",
    r"C:\Program Files (x86)\Thorlabs\Kinesis",
]
_AXIS_DEFAULT = {"x": 1, "y": 2, "z": 3}


def _load_kinesis():
    for d in KINESIS_DIRS:
        if os.path.isdir(d) and d not in sys.path:
            sys.path.append(d)
    import clr
    clr.AddReference("System")
    clr.AddReference("Thorlabs.MotionControl.DeviceManagerCLI")
    clr.AddReference("Thorlabs.MotionControl.Benchtop.StepperMotorCLI")
    from System import Decimal
    from Thorlabs.MotionControl.DeviceManagerCLI import DeviceManagerCLI
    from Thorlabs.MotionControl.Benchtop.StepperMotorCLI import BenchtopStepperMotor
    try:
        clr.AddReference("Thorlabs.MotionControl.DeviceConfiguration")
        from Thorlabs.MotionControl.DeviceConfiguration import DeviceSettingsUseOptionType
    except Exception:
        DeviceSettingsUseOptionType = None
    return DeviceManagerCLI, BenchtopStepperMotor, Decimal, DeviceSettingsUseOptionType


class ThorlabsStage(BaseStage):
    AXES = ("x", "y", "z")

    def __init__(self):
        self._DevMgr = self._BSC = self._Decimal = self._SettingsOpt = None
        self._device = None
        self._serial_str = None
        self._channels: dict = {}
        self._axis_map: dict = {}

    def connect(self, params: dict) -> None:
        if self._DevMgr is None:
            self._DevMgr, self._BSC, self._Decimal, self._SettingsOpt = _load_kinesis()
        serial = str(params.get("serial", "")).strip()
        if not serial:
            self._DevMgr.BuildDeviceList()
            serials = [str(s) for s in list(self._DevMgr.GetDeviceList())]
            if not serials:
                raise RuntimeError("Thorlabs: no se encontró ningún dispositivo Kinesis.")
            serial = serials[0]
            print("ThorlabsStage: usando dispositivo: %s" % serial)
        n_ch     = int(params.get("channels",   3))
        poll_ms  = int(params.get("poll_ms",  250))
        vel      = float(params.get("vel_mm_s",  2.0))
        acc      = float(params.get("acc_mm_s2", 4.0))
        axis_map = params.get("axis_map", _AXIS_DEFAULT)
        self._DevMgr.BuildDeviceList()
        self._device = self._BSC.CreateBenchtopStepperMotor(serial)
        self._device.Connect(serial)
        time.sleep(0.3)
        n_found = int(self._device.ChannelCount)
        self._serial_str = serial
        self._channels.clear()
        for ch in range(1, min(n_ch, n_found) + 1):
            c = self._device.GetChannel(ch)
            try: c.WaitForSettingsInitialized(5000)
            except Exception: pass
            c.StartPolling(poll_ms); time.sleep(0.2)
            c.EnableDevice();        time.sleep(0.3)
            self._load_motor_config(c)
            self._set_vel_acc(c, vel, acc)
            self._channels[ch] = c
        self._axis_map = {k.lower(): v for k, v in axis_map.items()}
        print("ThorlabsStage: conectado a %s (%d canales)." % (serial, len(self._channels)))

    def disconnect(self) -> None:
        for c in self._channels.values():
            try: c.StopPolling()
            except Exception: pass
        self._channels.clear()
        if self._device is not None:
            try: self._device.Disconnect(True)
            except Exception: pass
        self._device = None
        print("ThorlabsStage: desconectado.")

    @property
    def is_connected(self) -> bool:
        return self._device is not None and bool(self._channels)

    def home(self, axis: str) -> None:
        self._channels[self._resolve(axis)].Home(60_000)

    def has_homing(self, axis: str) -> bool:
        return True

    def move_abs(self, axis: str, pos_mm: float) -> None:
        self._channels[self._resolve(axis)].MoveTo(self._Decimal(float(pos_mm)), 60_000)

    def move_rel(self, axis: str, delta_mm: float) -> None:
        """
        Movimiento relativo: lee la posición actual y llama a move_abs(pos+delta).

        No usa MoveRelative() del SDK .NET porque su firma real es
        MoveRelative(MotorDirection, Decimal, timeoutMs) — pasar directamente
        un Decimal como primer argumento falla silenciosamente.
        """
        cur = self.position(axis)
        self.move_abs(axis, cur + delta_mm)

    def stop(self, axis: str) -> None:
        c = self._channels[self._resolve(axis)]
        try: c.StopImmediate()
        except Exception:
            try: c.Stop(0)
            except Exception: pass

    def position(self, axis: str) -> float:
        # System.Decimal (pythonnet) no soporta float() directo en pythonnet 2.x;
        # pasar por str() funciona en cualquier versión y en cualquier locale.
        raw = self._channels[self._resolve(axis)].Position
        return float(str(raw).replace(",", "."))

    def _resolve(self, axis: str) -> int:
        ch = self._axis_map.get(axis.lower())
        if ch is None:
            raise KeyError("ThorlabsStage: eje '%s' no mapeado." % axis)
        if ch not in self._channels:
            raise RuntimeError("ThorlabsStage: canal %d (eje '%s') no conectado." % (ch, axis))
        return ch

    def _load_motor_config(self, c) -> None:
        opt = self._SettingsOpt
        loaded = False
        if hasattr(c, "LoadMotorConfiguration"):
            for mode in ([opt.UseDeviceSettings, opt.UseFileSettings] if opt else []):
                if loaded: break
                try: c.LoadMotorConfiguration(c.DeviceID, mode); loaded = True
                except Exception: pass
            if not loaded:
                try: c.LoadMotorConfiguration(c.DeviceID); loaded = True
                except Exception: pass
        if not loaded and hasattr(c, "GetMotorConfiguration"):
            try: _ = c.GetMotorConfiguration(c.DeviceID)
            except Exception: pass
        try:
            if hasattr(c, "ApplySettings"): c.ApplySettings()
        except Exception: pass

    def _set_vel_acc(self, c, vel_mm_s: float, acc_mm_s2: float) -> None:
        if hasattr(c, "GetVelocityParams") and hasattr(c, "SetVelocityParams"):
            try:
                vp = c.GetVelocityParams()
                vp.MaxVelocity = self._Decimal(float(vel_mm_s))
                vp.Acceleration = self._Decimal(float(acc_mm_s2))
                c.SetVelocityParams(vp)
            except Exception: pass

    # ── Apagado seguro ──────────────────────────────────────────────────────
    # Segundos de espera por eje al homear en el apagado. El home de este
    # hardware puede colgarse, asi que cada eje va en su hilo con limite:
    # el cierre del sistema no puede quedar tomado por una platina trabada.
    ESPERA_HOME_EJE_S = 30.0

    def safe_shutdown(self) -> None:
        """
        Apagado seguro: llevar x e y a home (con limite de tiempo por eje) y
        desconectar. Ver BaseStage.
        """
        import threading as _threading

        def _home(ax):
            try:
                self.home(ax)
            except Exception:
                pass

        for _ax in ("x", "y"):
            _th = _threading.Thread(target=_home, args=(_ax,), daemon=True)
            _th.start()
            _th.join(self.ESPERA_HOME_EJE_S)
        self.disconnect()
