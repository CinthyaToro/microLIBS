# -*- coding: utf-8 -*-
"""
laser_client.py  —  Cliente 64-bit para laser_server.py (EKSPLA NL301)
=======================================================================
Solo stdlib: socket + json + time. Compatible con Python 64-bit.

Uso rápido (CLI para probar sin disparar):
    python laser_client.py --probe              # ping + connect + get_state
    python laser_client.py --state             # solo get_state

Uso programático:
    from laser_client import LaserClient

    with LaserClient() as lc:
        print(lc.ping())
        print(lc.connect())
        print(lc.get_state())
        lc.arm(warmup_s=10)
        lc.fire_burst(n_pulsos=1, rep_rate_hz=100)
        lc.disarm()

El servidor laser_server.py debe estar corriendo en Python 32-bit:
    python32 laser_server.py --conn usb
"""

from __future__ import print_function

import argparse
import json
import socket
import sys
import time

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 27182
DEFAULT_TIMEOUT = 10.0   # segundos para respuesta normal
FIRE_TIMEOUT   = 120.0   # segundos para fire_burst (incluye warmup + disparo)


class LaserClient:
    """
    Cliente JSON newline-delimited para laser_server.py.

    Puede usarse como context manager (with LaserClient() as lc: ...) o
    manualmente: lc = LaserClient(); lc._connect_socket(); ...; lc.close()
    """

    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, timeout=DEFAULT_TIMEOUT):
        self._host    = host
        self._port    = port
        self._timeout = timeout
        self._sock    = None
        self._fobj    = None
        self._req_id  = 0

    # ── Context manager ──────────────────────────────────────────────────────

    def __enter__(self):
        self._connect_socket()
        return self

    def __exit__(self, *_):
        self.close()

    # ── Conexión TCP ─────────────────────────────────────────────────────────

    def _connect_socket(self):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(self._timeout)
        self._sock.connect((self._host, self._port))
        self._fobj = self._sock.makefile("rb")

    def close(self):
        try:
            if self._fobj:
                self._fobj.close()
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = self._fobj = None

    # ── Protocolo ────────────────────────────────────────────────────────────

    def _send(self, cmd, params=None, timeout=None):
        """Envía un comando y espera la respuesta JSON."""
        if self._sock is None:
            self._connect_socket()

        self._req_id += 1
        req = {"id": self._req_id, "cmd": cmd}
        if params:
            req["params"] = params

        line = (json.dumps(req) + "\n").encode("utf-8")
        self._sock.settimeout(timeout or self._timeout)
        self._sock.sendall(line)

        raw = self._fobj.readline()
        if not raw:
            raise ConnectionError("Servidor cerró la conexión.")
        return json.loads(raw.decode("utf-8").strip())

    # ── API pública ───────────────────────────────────────────────────────────

    def ping(self):
        """Verifica que el servidor responde. Retorna {"ok": True, "pong": True, ...}."""
        return self._send("ping")

    def connect(self, connection_type="usb", lan_host=""):
        """Conecta el servidor al láser (rcConnect). connection_type: 'usb'|'comN'|'lan'."""
        params = {"connection_type": connection_type}
        if lan_host:
            params["lan_host"] = lan_host
        return self._send("connect", params)

    def disconnect(self):
        """Desconecta el servidor del láser (rcDisconnect)."""
        return self._send("disconnect")

    def arm(self, warmup_s=10):
        """
        Arma el láser (Power → ON) y espera warmup_s segundos.
        El flashlamp tarda 6–10 s en estabilizarse; 10 s es el valor recomendado.
        """
        r = self._send("arm")
        if r.get("ok"):
            print("[laser_client] Armado. Esperando warmup (%d s)..." % warmup_s)
            time.sleep(warmup_s)
            print("[laser_client] Warmup completo.")
        return r

    def disarm(self):
        """Desarma el láser (Power → OFF)."""
        return self._send("disarm")

    def get_state(self):
        """
        Lee Power, Output enable, Fault source, Fault code y Rep rate.
        Retorna {"ok": True, "state": {"power": "OFF", ...}}.
        """
        return self._send("get_state")

    def fire_burst(self, n_pulsos=1, rep_rate_hz=100.0):
        """
        Dispara exactamente n_pulsos a rep_rate_hz Hz.
        Encapsula la secuencia Burst→enable→Trigger en el servidor.
        El láser debe estar armado y calentado antes de llamar esto.
        Bloquea hasta que el servidor confirma que el burst completó (~n/rep + 4 s).
        """
        wait_est = float(n_pulsos) / rep_rate_hz + 4.0 + 2.0   # + margen de red
        return self._send(
            "fire_burst",
            {"n_pulsos": int(n_pulsos), "rep_rate_hz": float(rep_rate_hz)},
            timeout=self._timeout + wait_est,
        )

    def fire(self, delay_ms=0.0):
        """
        Pulso de Output enable: ON → delay_ms → OFF.
        Comando dumb — la configuración burst debe hacerse vía set_register antes.
        """
        return self._send("fire", {"delay_ms": float(delay_ms)})

    def get_register(self, module, register):
        """Lee un registro del láser. Nombres exactos del REMOTECONTROL.csv."""
        return self._send("get_register", {"module": module, "register": register})

    def set_register(self, module, register, value):
        """Escribe un registro del láser."""
        return self._send("set_register",
                          {"module": module, "register": register, "value": str(value)})

    def list_modules(self):
        """Lista los módulos CAN disponibles (CPU8000:16, HV+4-4kV:40, UCP:4)."""
        return self._send("list_modules")

    def shutdown_server(self):
        """Cierra el servidor laser_server.py limpiamente."""
        return self._send("shutdown")


# ─── CLI para diagnóstico sin disparar ───────────────────────────────────────

def cmd_probe(host, port):
    """ping → connect → get_state (sin armar, sin disparar)."""
    print("Conectando a laser_server en %s:%d..." % (host, port))
    try:
        lc = LaserClient(host=host, port=port, timeout=5.0)
        lc._connect_socket()
    except (ConnectionRefusedError, OSError) as e:
        print("ERROR: no se pudo conectar. ¿Está corriendo laser_server.py?")
        print("  %s" % e)
        sys.exit(1)

    print()
    print("--- ping ---")
    r = lc.ping()
    print(json.dumps(r, indent=2))

    print()
    print("--- connect (USB) ---")
    r = lc.connect()
    print(json.dumps(r, indent=2))

    print()
    print("--- get_state ---")
    r = lc.get_state()
    print(json.dumps(r, indent=2))

    if r.get("ok") and r.get("state"):
        s = r["state"]
        print()
        print("Estado del láser:")
        print("  Power:          %s" % s.get("power", "?"))
        print("  Output enable:  %s" % s.get("output_enable", "?"))
        print("  Fault source:   %s" % s.get("fault_source", "?"))
        print("  Fault code:     %s" % s.get("fault_code", "?"))
        print("  Rep rate:       %s Hz" % s.get("rep_rate_hz", "?"))

    lc.close()


def main():
    p = argparse.ArgumentParser(description="laser_client.py — diagnóstico EKSPLA NL301")
    p.add_argument("--host",  default=DEFAULT_HOST)
    p.add_argument("--port",  type=int, default=DEFAULT_PORT)
    p.add_argument("--probe", action="store_true",
                   help="ping + connect + get_state (sin disparar)")
    p.add_argument("--state", action="store_true",
                   help="solo get_state (asume ya conectado)")
    args = p.parse_args()

    if args.probe:
        cmd_probe(args.host, args.port)
    elif args.state:
        with LaserClient(host=args.host, port=args.port) as lc:
            r = lc.get_state()
            print(json.dumps(r, indent=2))
    else:
        p.print_help()


if __name__ == "__main__":
    main()
