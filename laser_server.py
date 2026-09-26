# -*- coding: utf-8 -*-
"""
laser_server.py  —  Servidor de proceso para EKSPLA NL230
==========================================================
Ejecutar con Python 32-bit desde la carpeta donde están las DLLs:
 
    python32 laser_server.py [--port 27182] [--conn usb|com3|lan]
 
Protocolo: JSON newline-delimited sobre TCP localhost.
  Petición:  {"id": 1, "cmd": "arm"}\\n
  Respuesta: {"id": 1, "ok": true, "result": {}}\\n
 
Comandos disponibles:
  ping          — verifica que el servidor responde
  connect       — rcConnect (params: {})
  disconnect    — rcDisconnect
  arm           — Power → ON
  disarm        — Power → OFF
  get_state     — lee Power, Fault source, Fault code, Output enable
  get_register  — params: {"module": "CPU8000:16", "register": "Power"}
  set_register  — params: {"module": "...", "register": "...", "value": "..."}
  list_modules  — rcGetFirstDeviceName / rcGetNextDeviceName
  fire          — habilita Output enable, espera delay_ms y lo desactiva
                  params: {"delay_ms": 0}
  shutdown      — cierra el servidor limpiamente
"""
 
from __future__ import annotations
 
import argparse
import ctypes
import json
import os
import platform
import socket
import sys
import threading
import time
 
# ─── Constantes ──────────────────────────────────────────────────────────────
 
DEFAULT_PORT     = 27182          # número de Euler truncado
TIMEOUT_MS       = 3000
BUF_SIZE         = 256
 
MOD_CPU = "CPU8000:16"
 
ERR_MAP = {
    0: "OK", 1: "No more data", 2: "No REMOTECONTROL.csv",
    3: "CSV modificado", 4: "Buffer corto", 5: "Módulo no encontrado",
    6: "Registro no encontrado", 7: "No se pudo conectar", 8: "Timeout",
    9: "Solo lectura", 10: "No NV", 11: "Valor > máx", 12: "Valor < mín",
    13: "Valor no permitido", 17: "Ya conectado", 18: "No conectado",
}
 
 
def _err_str(code: int) -> str:
    c = int(code) & 0x7FFFFFFF
    return ERR_MAP.get(c, "Error %d" % c)
 
 
def _ok(code: int) -> bool:
    return (int(code) & 0x7FFFFFFF) == 0
 
 
# ─── Carga DLL ───────────────────────────────────────────────────────────────
 
class EkspláDLL:
    """Wrapper sobre REMOTECONTROL.dll vía ctypes (solo 32-bit)."""
 
    def __init__(self, dll_dir: str = "."):
        if platform.system() != "Windows":
            raise RuntimeError("REMOTECONTROL.dll solo disponible en Windows.")
        if sys.maxsize > 2**32:
            raise RuntimeError(
                "Python 64-bit detectado. laser_server.py DEBE ejecutarse "
                "con Python 32-bit (embeddable package o instalación x86)."
            )
 
        # Cambiar al directorio de la DLL para que encuentre sus dependencias
        os.chdir(dll_dir)
 
        self._dll = ctypes.WinDLL("REMOTECONTROL.dll")
        self._setup_signatures()
 
    def _setup_signatures(self):
        d = self._dll
        c_i = ctypes.c_int
        c_c = ctypes.c_char_p
        c_d = ctypes.POINTER(ctypes.c_double)
        c_p = ctypes.POINTER(ctypes.c_int)
 
        d.rcConnect.restype            = c_i
        d.rcConnect.argtypes           = [c_i, c_i]
 
        d.rcDisconnect.restype         = c_i
        d.rcDisconnect.argtypes        = []
 
        d.rcGetRegAsString.restype     = c_i
        d.rcGetRegAsString.argtypes    = [c_c, c_c, ctypes.c_char_p, c_i, c_i, c_p]
 
        d.rcSetRegFromString.restype   = c_i
        d.rcSetRegFromString.argtypes  = [c_c, c_c, c_c]
 
        d.rcGetFirstDeviceName.restype = c_i
        d.rcGetFirstDeviceName.argtypes = [ctypes.c_char_p, c_i]
 
        d.rcGetNextDeviceName.restype  = c_i
        d.rcGetNextDeviceName.argtypes = [ctypes.c_char_p, c_i]
 
        # rcConnect2 (LAN) — opcional
        try:
            d.rcConnect2.restype   = c_i
            d.rcConnect2.argtypes  = [c_p, c_i, c_c, c_c]
            self._has_connect2 = True
        except Exception:
            self._has_connect2 = False
 
    # ── API ──────────────────────────────────────────────────────────────────
 
    def connect(self, conn_type: str = "usb", lan_host: str = "") -> dict:
        """Conecta al láser vía rcConnect. conn_type: 'usb' | 'comN' | 'lan'. Retorna ok/error."""
        ct = conn_type.strip().lower()
        if ct == "usb":
            ret = self._dll.rcConnect(ctypes.c_int(0), ctypes.c_int(0))
        elif ct.startswith("com"):
            import re
            n = int(re.search(r"\d+", ct).group())
            ret = self._dll.rcConnect(ctypes.c_int(1), ctypes.c_int(n))
        elif ct == "lan":
            if not self._has_connect2:
                return {"ok": False, "error": "rcConnect2 no disponible en esta DLL"}
            h = ctypes.c_int(0)
            ret = self._dll.rcConnect2(
                ctypes.byref(h), ctypes.c_int(2),
                lan_host.encode("ascii"), None
            )
        else:
            return {"ok": False, "error": "Tipo de conexión desconocido: %s" % ct}
 
        code = int(ret) & 0x7FFFFFFF
        if code in (0, 17):
            return {"ok": True, "already_connected": code == 17}
        return {"ok": False, "error": _err_str(code), "code": code}
 
    def disconnect(self) -> dict:
        """Cierra la conexión con el láser vía rcDisconnect."""
        ret = self._dll.rcDisconnect()
        return {"ok": _ok(ret), "error": None if _ok(ret) else _err_str(ret)}
 
    def get_register(self, module: str, register: str) -> dict:
        """Lee un registro del láser como string. Nombres exactos del REMOTECONTROL.csv (case-sensitive)."""
        buf = ctypes.create_string_buffer(BUF_SIZE)
        ret = self._dll.rcGetRegAsString(
            module.encode("ascii"), register.encode("ascii"),
            buf, ctypes.c_int(BUF_SIZE), ctypes.c_int(TIMEOUT_MS), None
        )
        if _ok(ret):
            return {"ok": True, "value": buf.value.decode("ascii", "ignore").strip()}
        return {"ok": False, "error": _err_str(ret), "code": int(ret) & 0x7FFFFFFF}
 
    def set_register(self, module: str, register: str, value: str) -> dict:
        """Escribe un registro del láser. Nombres exactos del REMOTECONTROL.csv (case-sensitive)."""
        ret = self._dll.rcSetRegFromString(
            module.encode("ascii"),
            register.encode("ascii"),
            value.encode("ascii")
        )
        return {"ok": _ok(ret), "error": None if _ok(ret) else _err_str(ret)}
 
    def list_modules(self) -> dict:
        """Lista los módulos CAN disponibles en el bus (CPU8000:16, HV+4-4kV:40, UCP:4)."""
        buf = ctypes.create_string_buffer(128)
        modules = []
        ret = self._dll.rcGetFirstDeviceName(buf, ctypes.c_int(128))
        while _ok(ret):
            m = buf.value.decode("ascii", "ignore").strip()
            if m:
                modules.append(m)
            ret = self._dll.rcGetNextDeviceName(buf, ctypes.c_int(128))
        return {"ok": True, "modules": modules}
 
    def get_state(self) -> dict:
        """Lee de una vez Power, Output enable, Fault source, Fault code y Repetition rate."""
        regs = [
            ("Power",         "power"),
            ("Output enable", "output_enable"),
            ("Fault source",  "fault_source"),
            ("Fault code",    "fault_code"),
            ("Repetition rate", "rep_rate_hz"),
        ]
        state = {}
        for reg_name, key in regs:
            r = self.get_register(MOD_CPU, reg_name)
            state[key] = r.get("value") if r["ok"] else None
        return {"ok": True, "state": state}
 
    def arm(self) -> dict:
        """Arma el láser: Power → ON. El flashlamp tarda ~6–10 s en estabilizarse."""
        return self.set_register(MOD_CPU, "Power", "ON")
 
    def disarm(self) -> dict:
        """Desarma el láser: Power → OFF."""
        return self.set_register(MOD_CPU, "Power", "OFF")
 
    def fire(self, delay_ms: float = 0.0) -> dict:
        """
        Togglea Output enable: ON → espera delay_ms → OFF.
 
        Este comando es "dumb": solo pulsa el shutter. La configuración del modo burst
        (Burst length, Continuous/Burst/Trigger) debe hacerse vía set_register ANTES de
        llamar a fire. El flujo para un burst de N pulsos desde el cliente 64-bit es:
 
            set_register("Continuous / Burst mode / Trigger burst", "Burst")
            set_register("Burst length", str(N))
            fire(delay_ms=0)   ← Output enable ON
            set_register("Continuous / Burst mode / Trigger burst", "Trigger")  ← dispara
            # esperar N/rep_rate + margen
            # el cliente 64-bit puede emitir set_register("Output enable", "OFF") o
            # llamar a fire con delay_ms suficiente para que complete el burst.
        """
        t0 = time.perf_counter()
        r = self.set_register(MOD_CPU, "Output enable", "ON")
        if not r["ok"]:
            return {"ok": False, "error": "No se pudo habilitar output: " + r.get("error", "")}
 
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)
 
        r2 = self.set_register(MOD_CPU, "Output enable", "OFF")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
 
        if not r2["ok"]:
            return {
                "ok": False,
                "error": "Output ON pero no se pudo apagar: " + r2.get("error", ""),
                "elapsed_ms": round(elapsed_ms, 2),
            }
        return {"ok": True, "elapsed_ms": round(elapsed_ms, 2)}
 
    def fire_burst(self, n_pulsos: int = 1, rep_rate_hz: float = 100.0) -> dict:
        """
        Dispara exactamente n_pulsos a rep_rate_hz Hz.
        Encapsula la secuencia completa Burst→enable→Trigger de forma atómica.
        El láser debe estar armado (Power=ON) y calentado antes de llamar esto.
 
        Secuencia interna (verificada con hardware, ver PROGRESS.md sección E):
            Synchronization mode = Internal
            Burst mode           = Burst
            Burst length         = N
            Output enable        = ON
            Burst mode           = Trigger   ← dispara el burst
            esperar N/rep_rate + 4 s
            Output enable        = OFF
        """
        t0 = time.perf_counter()
 
        steps = [
            ("Synchronization mode",                   "Internal"),
            ("Continuous / Burst mode / Trigger burst", "Burst"),
            ("Burst length",                            str(int(n_pulsos))),
        ]
        for reg, val in steps:
            r = self.set_register(MOD_CPU, reg, val)
            if not r["ok"]:
                return {"ok": False, "error": "set '%s'='%s': %s" % (reg, val, r.get("error", ""))}
 
        r = self.set_register(MOD_CPU, "Output enable", "ON")
        if not r["ok"]:
            return {"ok": False, "error": "Output enable ON: " + r.get("error", "")}
 
        r = self.set_register(MOD_CPU, "Continuous / Burst mode / Trigger burst", "Trigger")
        if not r["ok"]:
            self.set_register(MOD_CPU, "Output enable", "OFF")
            return {"ok": False, "error": "set Trigger: " + r.get("error", "")}
 
        wait_s = float(n_pulsos) / rep_rate_hz + 4.0
        time.sleep(wait_s)
 
        r = self.set_register(MOD_CPU, "Output enable", "OFF")
        elapsed_ms = (time.perf_counter() - t0) * 1000.0
 
        if not r["ok"]:
            return {
                "ok": False,
                "error": "Output enable OFF: " + r.get("error", ""),
                "n_pulsos": n_pulsos,
                "elapsed_ms": round(elapsed_ms, 2),
            }
        return {
            "ok": True,
            "n_pulsos": n_pulsos,
            "rep_rate_hz": rep_rate_hz,
            "elapsed_ms": round(elapsed_ms, 2),
        }
 
 
# ─── Servidor TCP ─────────────────────────────────────────────────────────────
 
class LaserServer:
    """Servidor JSON newline-delimited. Un cliente a la vez (microLIBS es monohilo)."""
 
    def __init__(self, dll: EkspláDLL, port: int, conn_type: str, lan_host: str):
        self._dll       = dll
        self._port      = port
        self._conn_type = conn_type
        self._lan_host  = lan_host
        self._running   = False
        self._sock      = None
 
    # ── dispatch ─────────────────────────────────────────────────────────────
 
    def _handle(self, req: dict) -> dict:
        """
        Despacha un comando JSON al método correspondiente de EkspláDLL.
 
        Comandos: ping, connect, disconnect, arm, disarm, get_state,
                  get_register, set_register, list_modules, fire, shutdown.
        """
        cmd = req.get("cmd", "")
        params = req.get("params", {})
        req_id = req.get("id", None)
 
        try:
            if cmd == "ping":
                result = {"pong": True, "version": "1.0"}
 
            elif cmd == "connect":
                result = self._dll.connect(
                    conn_type=params.get("connection_type", self._conn_type),
                    lan_host=params.get("lan_host", self._lan_host),
                )
 
            elif cmd == "disconnect":
                result = self._dll.disconnect()
 
            elif cmd == "arm":
                result = self._dll.arm()
 
            elif cmd == "disarm":
                result = self._dll.disarm()
 
            elif cmd == "get_state":
                result = self._dll.get_state()
 
            elif cmd == "get_register":
                result = self._dll.get_register(
                    params["module"], params["register"]
                )
 
            elif cmd == "set_register":
                result = self._dll.set_register(
                    params["module"], params["register"], params["value"]
                )
 
            elif cmd == "list_modules":
                result = self._dll.list_modules()
 
            elif cmd == "fire":
                result = self._dll.fire(
                    delay_ms=float(params.get("delay_ms", 0))
                )
 
            elif cmd == "fire_burst":
                result = self._dll.fire_burst(
                    n_pulsos=int(params.get("n_pulsos", 1)),
                    rep_rate_hz=float(params.get("rep_rate_hz", 100.0)),
                )
 
            elif cmd == "shutdown":
                self._running = False
                result = {"ok": True, "message": "Servidor cerrando..."}
 
            else:
                result = {"ok": False, "error": "Comando desconocido: %s" % cmd}
 
        except Exception as e:
            result = {"ok": False, "error": "Excepción: %s" % repr(e)}
 
        resp = {"id": req_id}
        resp.update(result)
        return resp
 
    # ── loop de conexión ──────────────────────────────────────────────────────
 
    def _handle_client(self, conn: socket.socket, addr):
        print("[laser_server] Cliente conectado: %s" % str(addr))
        buffer = b""
        try:
            while self._running:
                try:
                    chunk = conn.recv(4096)
                except OSError:
                    break
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        req = json.loads(line.decode("utf-8"))
                    except json.JSONDecodeError as e:
                        resp = {"ok": False, "error": "JSON inválido: %s" % str(e)}
                        conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
                        continue
 
                    resp = self._handle(req)
                    conn.sendall((json.dumps(resp) + "\n").encode("utf-8"))
 
                    if req.get("cmd") == "shutdown":
                        return
 
        except Exception as e:
            print("[laser_server] Error en cliente: %s" % repr(e))
        finally:
            conn.close()
            print("[laser_server] Cliente desconectado.")
 
    def run(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", self._port))
        self._sock.listen(1)
        self._running = True
 
        print("[laser_server] Escuchando en 127.0.0.1:%d" % self._port)
        print("[laser_server] Conexión láser: %s" % self._conn_type)
        print("[laser_server] Python %s (%s)" % (
            sys.version.split()[0],
            "32-bit" if sys.maxsize <= 2**32 else "64-bit"
        ))
        print("[laser_server] Listo. Ctrl+C para salir.")
 
        self._sock.settimeout(1.0)  # para poder chequear _running periódicamente
        while self._running:
            try:
                conn, addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
 
            # Un hilo por cliente (en la práctica solo habrá uno)
            t = threading.Thread(
                target=self._handle_client,
                args=(conn, addr),
                daemon=True,
            )
            t.start()
 
        self._sock.close()
        print("[laser_server] Servidor cerrado.")
 
 
# ─── Main ─────────────────────────────────────────────────────────────────────
 
def main():
    parser = argparse.ArgumentParser(
        description="laser_server.py — Servidor EKSPLA NL230 (Python 32-bit)"
    )
    parser.add_argument("--port",    type=int, default=DEFAULT_PORT,
                        help="Puerto TCP local (default: %d)" % DEFAULT_PORT)
    parser.add_argument("--conn",    default="usb",
                        help="Tipo de conexión: usb | com3 | lan (default: usb)")
    parser.add_argument("--lan-host", default="192.168.1.100",
                        help="IP del láser para conexión LAN")
    parser.add_argument("--dll-dir", default=".",
                        help="Carpeta con REMOTECONTROL.dll (default: directorio actual)")
    args = parser.parse_args()
 
    print("=" * 60)
    print("  laser_server.py — EKSPLA NL230")
    print("  Protocolo: JSON newline-delimited sobre TCP localhost")
    print("=" * 60)
 
    try:
        dll = EkspláDLL(dll_dir=os.path.abspath(args.dll_dir))
        print("[laser_server] DLL cargada correctamente.")
    except RuntimeError as e:
        print("[laser_server] ERROR: %s" % e)
        sys.exit(1)
    except OSError as e:
        print("[laser_server] ERROR cargando DLL: %s" % e)
        if "193" in str(e):
            print("[laser_server] Código 193 = DLL 32-bit con Python 64-bit.")
            print("[laser_server] Usar: python32 laser_server.py")
        sys.exit(1)
 
    server = LaserServer(
        dll=dll,
        port=args.port,
        conn_type=args.conn,
        lan_host=args.lan_host,
    )
 
    try:
        server.run()
    except KeyboardInterrupt:
        print("\n[laser_server] Interrumpido por usuario.")
 
 
if __name__ == "__main__":
    main()