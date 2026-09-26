# -*- coding: utf-8 -*-
"""
hal/drivers/laser_proxy.py  —  LaserProxy
==========================================
Implementa BaseLaser comunicándose con laser_server.py vía socket TCP
local (JSON newline-delimited).

Desde el punto de vista de microLIBS (Python 64-bit), este objeto
se comporta exactamente igual que cualquier otro driver de láser.
Toda la lógica de DLL 32-bit vive en el proceso laser_server.py.

Uso:
    from hal.drivers.laser_proxy import LaserProxy

    laser = LaserProxy()
    laser.connect({
        "host":            "127.0.0.1",
        "port":            27182,
        "connection_type": "usb",   # "usb" | "com3" | "lan"
        "lan_host":        "",
        "auto_arm":        False,   # si True, llama arm() en connect()
    })

    laser.arm()
    result = laser.fire(pulse_us=0, delay_us=0)
    laser.disarm()
    laser.disconnect()

Protocolo de socket (heredado de laser_server.py):
    Petición:  {"id": N, "cmd": "...", "params": {...}}\\n
    Respuesta: {"id": N, "ok": bool, ...}\\n
"""

from __future__ import annotations

import json
import socket
import threading
import time
from typing import Any, Dict, Optional

from hal.base_laser import BaseLaser


# ─── Defaults ────────────────────────────────────────────────────────────────

DEFAULT_HOST    = "127.0.0.1"
DEFAULT_PORT    = 27182
SOCKET_TIMEOUT  = 5.0    # segundos para recv (operaciones normales)
CONNECT_TIMEOUT = 3.0    # segundos para la conexión TCP inicial


# ─── LaserProxy ──────────────────────────────────────────────────────────────

class LaserProxy(BaseLaser):
    """
    Proxy 64-bit → laser_server.py (32-bit) vía socket localhost.

    Thread-safety: usa un lock interno. Llamadas simultáneas desde
    distintos hilos se serializan automáticamente.
    """

    def __init__(self):
        self._sock: Optional[socket.socket]  = None
        self._fh   = None           # file handle para readline()
        self._lock  = threading.Lock()
        self._seq   = 0             # contador de IDs de petición
        self._connected_to_server  = False
        self._connected_to_laser   = False
        self._params: Dict[str, Any] = {}

    # ── BaseLaser API ─────────────────────────────────────────────────────────

    def connect(self, params: dict) -> None:
        """
        Conecta al laser_server.py y luego al hardware del láser.

        params:
            host            — IP del servidor (default: "127.0.0.1")
            port            — Puerto TCP    (default: 27182)
            connection_type — "usb" | "com3" | "lan"
            lan_host        — IP del láser si connection_type="lan"
            auto_arm        — si True llama arm() automáticamente
        """
        self._params = dict(params)
        host  = params.get("host",  DEFAULT_HOST)
        port  = int(params.get("port", DEFAULT_PORT))

        # 1. Conectar TCP al servidor
        self._connect_socket(host, port)

        # 2. Ping para verificar que el servidor responde
        r = self._send("ping")
        if not r.get("pong"):
            raise ConnectionError("laser_server no respondió al ping.")

        # 3. Conectar el servidor al hardware del láser
        r = self._send("connect", {
            "connection_type": params.get("connection_type", "usb"),
            "lan_host":        params.get("lan_host", ""),
        })
        if not r.get("ok"):
            raise ConnectionError(
                "laser_server no pudo conectar al láser: %s" % r.get("error")
            )

        self._connected_to_laser = True

        # 4. Auto-arm opcional
        if params.get("auto_arm", False):
            self.arm()

    def disconnect(self) -> None:
        try:
            # Si el socket se rompió pero tenemos parámetros, reconectar para poder desarmar
            if not self._connected_to_server and self._params:
                try:
                    host = self._params.get("host", DEFAULT_HOST)
                    port = int(self._params.get("port", DEFAULT_PORT))
                    self._connect_socket(host, port)
                    self._connected_to_laser = True
                except Exception:
                    pass
            if self._connected_to_laser:
                self.disarm()
                self._send("disconnect")
        except Exception:
            pass
        finally:
            self._connected_to_laser  = False
            self._close_socket()

    @property
    def is_connected(self) -> bool:
        return self._connected_to_server and self._connected_to_laser

    def arm(self) -> None:
        r = self._send("arm")
        if not r.get("ok"):
            raise RuntimeError("arm() falló: %s" % r.get("error"))

    def disarm(self) -> None:
        r = self._send("disarm")
        if not r.get("ok"):
            raise RuntimeError("disarm() falló: %s" % r.get("error"))

    def fire(self, pulse_us: int = 0, delay_us: int = 0) -> dict:
        """
        Dispara el láser habilitando Output enable.

        pulse_us  — no usado directamente (la duración la controla el NL230
                    según su frecuencia interna); se pasa como metadata al log.
        delay_us  — delay EXTRA en microsegundos después de habilitar
                    el output (antes de deshabilitarlo). Útil para sincronizar
                    con la adquisición del espectrómetro.

        Retorna dict con ok, elapsed_ms y cualquier error.
        """
        delay_ms = delay_us / 1000.0
        # Servidor hace 2 llamadas DLL × 3 s cada una + delay + margen
        fire_timeout = delay_ms / 1000.0 + 12.0
        r = self._send("fire", {"delay_ms": delay_ms}, timeout=fire_timeout)
        r["pulse_us"]  = pulse_us
        r["delay_us"]  = delay_us
        return r

    def fire_burst(self, n_pulsos: int) -> dict:
        """
        Dispara un burst de n_pulsos a 100 Hz (frecuencia fija del NL230).
        El láser debe estar armado antes de llamar este método.
        Bloquea hasta que el servidor confirma que el burst completó.
        """
        # 100 Hz es la única frecuencia válida del NL230 en este setup.
        # El timeout se extiende para cubrir n/rep_rate + margen de red (6 s).
        REP_RATE = 100.0
        wait_est = float(n_pulsos) / REP_RATE + 4.0 + 2.0
        return self._send(
            "fire_burst",
            {"n_pulsos": int(n_pulsos), "rep_rate_hz": REP_RATE},
            timeout=SOCKET_TIMEOUT + wait_est,
        )

    @property
    def rep_rate_hz(self) -> float:
        """Frecuencia de disparo en Hz a la que opera este láser."""
        return 100.0

    # ── Extensiones propias del EKSPLA ────────────────────────────────────────

    def get_state(self) -> dict:
        """Retorna dict con power, output_enable, fault_source, fault_code."""
        r = self._send("get_state")
        return r.get("state", {})

    def get_register(self, module: str, register: str) -> str:
        """Lee un registro arbitrario del láser. Retorna string o lanza RuntimeError."""
        r = self._send("get_register", {"module": module, "register": register})
        if not r.get("ok"):
            raise RuntimeError("get_register(%s, %s) falló: %s" % (
                module, register, r.get("error")))
        return r["value"]

    def set_register(self, module: str, register: str, value: str) -> None:
        """Escribe un registro arbitrario del láser."""
        r = self._send("set_register", {
            "module": module, "register": register, "value": value
        })
        if not r.get("ok"):
            raise RuntimeError("set_register(%s, %s, %s) falló: %s" % (
                module, register, value, r.get("error")))

    def list_modules(self) -> list:
        r = self._send("list_modules")
        return r.get("modules", [])

    # ── Socket interno ────────────────────────────────────────────────────────

    def _connect_socket(self, host: str, port: int) -> None:
        self._close_socket()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(CONNECT_TIMEOUT)
        try:
            s.connect((host, port))
        except (ConnectionRefusedError, socket.timeout) as e:
            s.close()
            raise ConnectionError(
                "No se pudo conectar a laser_server en %s:%d. "
                "¿Está corriendo laser_server.py con Python 32-bit? "
                "Error: %s" % (host, port, e)
            )
        s.settimeout(SOCKET_TIMEOUT)
        self._sock = s
        self._fh   = s.makefile("r", encoding="utf-8")
        self._connected_to_server = True

    def _close_socket(self) -> None:
        try:
            if self._fh:
                self._fh.close()
        except Exception:
            pass
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
        self._fh   = None
        self._connected_to_server = False

    def _send(self, cmd: str, params: dict = None, timeout: float = None) -> dict:
        """Envía un comando y espera la respuesta. Thread-safe."""
        with self._lock:
            self._seq += 1
            req = {"id": self._seq, "cmd": cmd}
            if params:
                req["params"] = params

            raw = (json.dumps(req) + "\n").encode("utf-8")
            if timeout is not None and self._sock:
                self._sock.settimeout(timeout)
            try:
                self._sock.sendall(raw)
                line = self._fh.readline()
            except (OSError, AttributeError) as e:
                self._connected_to_server = False
                self._connected_to_laser  = False
                self._close_socket()
                raise ConnectionError(
                    "Socket laser_server perdido durante '%s': %s" % (cmd, e)
                )
            finally:
                if timeout is not None and self._sock:
                    self._sock.settimeout(SOCKET_TIMEOUT)

            if not line:
                self._connected_to_server = False
                self._connected_to_laser  = False
                self._close_socket()
                raise ConnectionError(
                    "laser_server cerró la conexión durante '%s'." % cmd
                )
            try:
                return json.loads(line.strip())
            except json.JSONDecodeError as e:
                raise ValueError(
                    "Respuesta JSON inválida de laser_server: %s | raw=%r" % (e, line)
                )

    def __repr__(self) -> str:
        return (
            "LaserProxy(connected=%s, server=%s)" % (
                self.is_connected, self._params.get("host", "?")
            )
        )

    # ── Apagado seguro ──────────────────────────────────────────────────────
    # Registros del NL230 que se dejan en un estado seguro conocido antes de
    # desconectar, para que el equipo no quede armado. Extraidos de la
    # secuencia que vivia en presentation/main_window.py hasta 2026-09-22.
    _SHUTDOWN_MODULO = "CPU8000:16"
    _SHUTDOWN_REGISTROS = [
        ("Output enable",                           "OFF"),
        ("Continuous / Burst mode / Trigger burst", "Burst"),
        ("Burst length",                            "1"),
        ("Synchronization mode",                    "Internal"),
    ]

    def safe_shutdown(self) -> None:
        """
        Apagado seguro del EKSPLA NL230: desarmar, dejar los registros en
        estado seguro conocido, y recien ahi desconectar. Ver BaseLaser.
        """
        try:
            self.disarm()
        except Exception:
            pass
        for _reg, _val in self._SHUTDOWN_REGISTROS:
            try:
                self.set_register(self._SHUTDOWN_MODULO, _reg, _val)
            except Exception:
                pass
        self.disconnect()
