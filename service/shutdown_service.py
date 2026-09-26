# -*- coding: utf-8 -*-
"""
service/shutdown_service.py
===========================
Orquestación del apagado seguro de microLIBS.

Esta capa decide **el ORDEN** en que se apagan los instrumentos y **cuánto
espera** por cada uno. No sabe qué hay que hacerle a ninguno: eso lo sabe cada
driver, detrás de `safe_shutdown()` (ver `hal/base_*.py`). Acá no aparece
ninguna marca ni modelo. Eso es R2 — por capacidad, no por marca.

CONTRATO (verificado por tests/test_shutdown_sequence.py):

  Orden FIJO, por rol:
      ScanRunner → espectrómetro → láser → platina → cámara → Arduino

  El orden es un invariante de seguridad, no una configuración: el
  espectrómetro va primero para soltarle el latch del USB, y el láser antes
  que la platina para que nada se mueva con el equipo armado. Por eso NO se
  lee del YAML: si fuera configurable, se podría configurar mal.

  - Un instrumento que falla NUNCA bloquea a los demás.
  - Un instrumento que NO RESPONDE tampoco: cada uno tiene un techo de espera
    y, si lo pasa, se registra y se sigue. Ver "Sobre el techo de espera".
  - Si un instrumento es None, se saltea en silencio.
  - La secuencia es idempotente y nunca lanza.

Si se agrega un instrumento nuevo, va en el orden que le corresponda por rol,
y su receta va en SU driver, no acá.

── Sobre el techo de espera ────────────────────────────────────────────────
Cerrar el programa mientras el Ocean tiene una adquisición bloqueada esperando
el TTL en modo 3 dejaba la ventana congelada, sin explicación, hasta que
expirara. La causa de fondo no se puede arreglar desde Python: el bloqueo está
dentro de `self.spec.intensities()`, en C. Ver docs/bitacora/2026-09-22.md,
pendiente 9.

Mientras tanto, acá se acota cuánto se espera. Decisión tomada con el
compromiso a la vista (22-Sep-2026): es preferible cerrar en un tiempo acotado
y AVISAR que un instrumento no cerró limpio, antes que dejar la ventana
colgada. El costo es que, si el proceso termina mientras un instrumento está a
medio cerrar, el USB puede quedar tomado y haya que desenchufarlo.
"""
from __future__ import annotations

import threading
from typing import Callable, Optional

# Techo de espera por instrumento, en segundos. Son por ROL, no por marca.
# La platina tiene el techo más alto porque homear es lento por naturaleza y
# su driver ya acota cada eje por separado: este es el techo de todo el gesto.
ESPERA_SCANRUNNER_S    = 2.0
ESPERA_ESPECTROMETRO_S = 10.0
ESPERA_LASER_S         = 10.0
ESPERA_PLATINA_S       = 70.0
ESPERA_CAMARA_S        = 10.0
ESPERA_ARDUINO_S       = 5.0


class ShutdownSequence:
    """
    Apaga los instrumentos en el orden fijo del contrato.

    Es independiente de la UI y de las marcas: recibe un callback de log y los
    instrumentos por parámetro, y a cada uno le pide `safe_shutdown()`.

        seq = ShutdownSequence(log=ui_log)
        reporte = seq.run(runner=..., spectrometer=..., laser=...,
                          stage=..., vision=..., arduino=...)
    """

    def __init__(self, log: Optional[Callable[[str], None]] = None) -> None:
        self._log = log if log is not None else (lambda _msg: None)
        self._hecho = False

    @property
    def hecho(self) -> bool:
        """True si la secuencia ya corrió (segunda llamada = no-op)."""
        return self._hecho

    def run(
        self,
        *,
        runner=None,
        spectrometer=None,
        laser=None,
        stage=None,
        vision=None,
        arduino=None,
    ) -> dict:
        """
        Ejecuta la secuencia completa. Nunca lanza excepción.

        Retorna un dict con:
            ya_estaba  bool   True si la secuencia ya había corrido; en ese
                              caso no se tocó nada y el llamador NO debería
                              cerrar la ventana tampoco.
            pasos      list   rol de cada instrumento que se intentó, en orden.
            errores    list   (rol, motivo) de lo que falló o no respondió.
                              Que haya errores NO significa que se abortó.
            colgados   list   roles que pasaron su techo de espera. Su hilo
                              sigue vivo en background: el instrumento puede
                              quedar sin cerrar del todo.
        """
        if self._hecho:
            return {"ya_estaba": True, "pasos": [], "errores": [], "colgados": []}
        self._hecho = True

        pasos: list = []
        errores: list = []
        colgados: list = []

        def _apagar(rol: str, instrumento, techo_s: float) -> None:
            """
            Le pide a un instrumento que se apague, con techo de espera.

            El instrumento sabe QUÉ hacer; acá solo se decide CUÁNTO esperarlo.
            """
            if instrumento is None:
                return
            pasos.append(rol)
            fallo = {}

            def _correr():
                try:
                    instrumento.safe_shutdown()
                except Exception as e:
                    fallo["e"] = e

            hilo = threading.Thread(
                target=_correr, daemon=True, name="shutdown-%s" % rol
            )
            hilo.start()
            hilo.join(techo_s)

            if hilo.is_alive():
                colgados.append(rol)
                errores.append(
                    (rol, "no respondio en %.0f s — se sigue sin esperarlo" % techo_s)
                )
                self._log(
                    "[shutdown] %s: NO RESPONDIO en %.0f s. Se continua el cierre; "
                    "puede haber quedado sin cerrar del todo." % (rol, techo_s)
                )
            elif "e" in fallo:
                errores.append((rol, repr(fallo["e"])))
                self._log("[shutdown] %s: %s" % (rol, fallo["e"]))
            else:
                self._log("[shutdown] %s: cerrado OK" % rol)

        self._log("Salida segura...")

        # ── 0. ScanRunner — frenar antes de tocar ningún instrumento ────────
        if runner is not None:
            pasos.append("runner")
            try:
                runner.stop()
            except Exception as e:
                errores.append(("runner.stop", repr(e)))
            try:
                runner.join(timeout=ESPERA_SCANRUNNER_S)
                hilo_runner = getattr(runner, "_thread", None)
                if hilo_runner is not None and hilo_runner.is_alive():
                    colgados.append("runner")
                    self._log(
                        "[shutdown] ScanRunner no termino en %.0f s — continuando cierre."
                        % ESPERA_SCANRUNNER_S
                    )
            except Exception as e:
                errores.append(("runner.join", repr(e)))

        # ── 1-5. Los instrumentos, en el orden fijo del contrato ────────────
        _apagar("espectrometro", spectrometer, ESPERA_ESPECTROMETRO_S)
        _apagar("laser",         laser,        ESPERA_LASER_S)
        _apagar("platina",       stage,        ESPERA_PLATINA_S)
        _apagar("camara",        vision,       ESPERA_CAMARA_S)
        _apagar("arduino",       arduino,      ESPERA_ARDUINO_S)

        return {
            "ya_estaba": False,
            "pasos": pasos,
            "errores": errores,
            "colgados": colgados,
        }
