# Arranque y disparo manual — microLIBS

**Audiencia:** operador frente al equipo (no requiere conocimiento de programación)  
**Propósito:** iniciar la sesión, armar el láser, obtener y guardar un espectro de forma manual

---

## 1. Lista de verificación pre-sesión

Antes de encender cualquier cosa, verificar en orden:

| # | Ítem | Qué verificar |
|---|------|---------------|
| 1 | **Anteojos láser** | Puestos antes de entrar al área del láser. Clase 4. |
| 2 | **Interlock activo** | El interlock de la sala (o gabinete) está cerrado. |
| 3 | **Muestra posicionada** | La muestra está en el stage y la fibra del espectrómetro apunta a la zona de interés. |
| 4 | **Cable SYNC OUT** | Conectado desde la salida SYNC OUT del NL230 al puerto LAMP SYNC del rack LIBS2500plus. |
| 5 | **USB espectrómetro** | Cable USB del rack LIBS2500plus conectado al PC y reconocido (verificar en Administrador de dispositivos). |
| 6 | **USB stage** | Cable USB del Thorlabs (o puerto COM del MoVi) conectado al PC. |
| 7 | **Cámara(s)** | Conectadas por USB al PC. Si es Chameleon: verificar que el LED de la cámara está encendido. |
| 8 | **NL230 encendido** | El panel frontal del EKSPLA NL230 muestra estado operativo. |
| 9 | **laser_server.py corriendo** | En la PC con las DLLs de REMOTECONTROL ejecutar (Python 32-bit): `python32 laser_server.py --conn usb` |

> **Nota sobre laser_server.py:** debe estar ejecutándose ANTES de iniciar main.py. Si main.py no puede conectar al servidor, el panel del láser mostrará "ninguno configurado".

---

## 2. Cómo iniciar main.py

1. Abrir una terminal en la carpeta del proyecto (`microlibs_v2-Cal_v5`).
2. Ejecutar:
   ```
   python main.py
   ```
3. Aparecerá primero la ventana **"microLIBS — Preparar sesión"** (Wizard-Sesión).

---

## 3. Cómo configurar la sesión en el Wizard-Sesión

La ventana "microLIBS — Preparar sesión" tiene los siguientes campos:

### Sección principal

| Campo | Qué poner |
|-------|-----------|
| **Muestra** | Nombre de la muestra (ej. `PET_01`). Evitar espacios; usar guiones o guiones bajos. |
| **Operador** | Tu nombre. |
| **Carpeta base** | Carpeta donde se guardarán las sesiones. Usar el botón **"Elegir…"** para navegar. Por defecto: `~/microLIBS_captures`. |
| **Cámara** | Presionar **"Cámara…"** para abrir el selector. El selector tiene dos roles: MUESTRA (obligatorio) y STAGE (opcional). Asignar la cámara correspondiente a cada rol. |

### Sección Stage

| Campo | Qué poner |
|-------|-----------|
| **Stage** | Seleccionar el driver: `movi`, `thorlabs`, `thorlabs_sim`, o `sim`. Para labo real con Thorlabs: `thorlabs`. |
| **Puerto** | Puerto COM del stage (ej. `COM4`). Para MoVi: usar el botón azul **"Detectar"** para encontrarlo automáticamente. Click derecho sobre el campo "Puerto" para ver los puertos disponibles. |
| **⚠ Invertir eje Y stage** | Mantener marcado para Thorlabs (es el default). Desmarcar para MoVi. |

### Sección Trigger

| Opción | Cuándo usarla |
|--------|---------------|
| `soft_delay` | Modo por defecto. Sin hardware de trigger externo. |
| `ttl_arduino` | Solo si hay Arduino conectado. |
| `none` | Sin trigger. |

### Sección Láser

| Campo | Qué poner |
|-------|-----------|
| **Driver** | `ekspla` para el EKSPLA NL230 real. `sim_laser` para simulación sin hardware. `none` si no se usa el láser. |
| **Conexión HW** | `usb` (el más común). |
| **Host / Puerto** | Dejar los valores por defecto (`127.0.0.1` / `27182`) si laser_server.py corre en la misma PC. |

> **Aviso importante:** si el driver es `ekspla`, el programa muestra: *"Para 'ekspla': antes de iniciar ejecutá python32 laser_server.py en el PC con las DLLs de REMOTECONTROL."* Verificar que esté corriendo antes de presionar "Iniciar sesión".

### Iniciar

Una vez configurado todo, presionar el botón verde **"▶ Iniciar sesión"** en la esquina inferior derecha. Esto abre el panel principal de control.

Si la combinación de drivers es incoherente (por ejemplo, láser real + espectrómetro simulado), el programa mostrará un aviso emergente de advertencia al abrir el panel. Leerlo y confirmar si es intencional.

---

## 4. Cómo hacer ARM del láser

El Panel de control ("microLIBS — Control") tiene una sección llamada **"Láser — LaserProxy"** (o el nombre del driver).

**Antes de ARM:**
1. Verificar que el banner superior muestra "Espectrómetro: ocean OK" en verde. Si muestra error, revisar el cable USB y relanzar.
2. Verificar que la sección del láser no muestra "Sin láser" — si lo muestra, volver a la sesión con el driver correcto.

**Procedimiento ARM:**
1. En la fila de botones del panel Láser: presionar el botón azul **"ARM"**.
2. El log mostrará `✅ Láser ARMADO.` si fue exitoso.
3. Esperar al menos **15 segundos** de warmup del flashlamp antes del primer disparo.
4. Para verificar el estado del láser después del ARM: presionar **"🔄 Leer estado"**. El log mostrará `Power=ON Output=OFF` cuando está armado y listo.

> Si ARM falla (`❌ arm: ...` en el log), verificar que laser_server.py está corriendo y que el NL230 tiene alimentación. Nunca intentar disparar con ARM fallido.

**DISARM:**
Presionar el botón naranja **"DISARM"** para apagar el Output Enable y dejar el láser en estado seguro. Hacer DISARM antes de cualquier cambio físico en el setup.

---

## 5. Cómo ejecutar FIRE+ADQUIRIR y qué esperar en el log

**Configurar antes de disparar:**

| Control | Valor para LIBS | Dónde está |
|---------|-----------------|------------|
| **N pulsos** | `1` (default) | Campo de texto junto a ARM/DISARM |
| **Integ (ms)** | `5.0` (default, 5 ms) | Campo de texto junto a N pulsos |

**Procedimiento:**

1. (Opcional pero recomendado) Capturar el fondo ANTES del disparo: ver sección siguiente si querés guardar espectro neto.
2. Presionar el botón rojo **"🔥 FIRE + ADQUIRIR"**.
3. El LED del panel parpadeará en amarillo durante el disparo.

**Secuencia que verás en el log:**

```
[HH:MM:SS] 1/4 Integracion: 5.0 ms | 1 pulsos
[HH:MM:SS] 2/4 Espectrómetro armado — esperando trigger TTL...
[HH:MM:SS] 3/4 Disparando 1 pulso(s)...
[HH:MM:SS] [diag] OE_rb=ON  BM_post=Trigger
[HH:MM:SS] 4/4 Espectro OK — 3 canal(es).
[HH:MM:SS] 🔥 FIRE OK | 1 pulsos | XXXX ms
```

La línea clave para saber si el disparo fue correcto es:
- `[diag] OE_rb=ON  BM_post=Trigger` → secuencia correcta, el láser disparó.
- `[diag] OE_rb=OFF BM_post=...` → Output enable rechazado, el NL230 no armó.
- `[diag] OE_rb=ON  BM_post=Burst` → el cambio a Trigger no se aplicó, el láser no disparó.

**Si el espectro llega:**
- El log muestra `4/4 Espectro OK — 3 canal(es).`
- La barra de estado dice `Espectro listo. Guardá con el botón abajo.`
- El LED queda en verde.

**Si el espectro no llega (timeout):**
- El log muestra `4/4 Timeout (35 s) — trigger no llegó.`
- Ver sección 7 para diagnóstico.

---

## 6. Cómo guardar el espectro

### Primero: capturar el fondo (dark) — recomendado

El fondo elimina el ruido de fondo (electrónica, luz ambiente) del espectro de plasma.

1. Asegurarse de que el láser NO dispara (o apagar la luz ambiente durante la captura).
2. Presionar el botón oscuro **"🌑 Capturar fondo"**.
3. El log mostrará:
   ```
   Capturando fondo (modo free-running, 5.0 ms)...
   Fondo capturado — 3 canal(es).
   Fondo guardado: .../spectra/fondo_YYYYMMDD_HHMMSS.csv
   ```
4. El indicador junto al botón cambiará a `Fondo activo: fondo_YYYYMMDD_HHMMSS.csv (3 ch)`.

### Guardar el espectro

Después de un FIRE+ADQUIRIR exitoso:

1. Presionar el botón verde oscuro **"💾 Guardar espectro"** (al final del panel Láser).
2. Si hay fondo activo, el programa guarda **dos archivos**:
   - `espectro_YYYYMMDD_HHMMSS.csv` — espectro crudo (raw)
   - `espectro_neto_YYYYMMDD_HHMMSS.csv` — espectro con fondo restado
3. Si no hay fondo activo, solo guarda el raw.
4. Se abre automáticamente un gráfico matplotlib con los canales A (azul), B (verde) y C (rojo).
5. El log confirmará:
   ```
   Raw guardado: .../spectra/espectro_YYYYMMDD_HHMMSS.csv
   Neto guardado: .../spectra/espectro_neto_YYYYMMDD_HHMMSS.csv
   ```

> Los archivos se guardan siempre en la subcarpeta `spectra/` dentro de la carpeta de sesión actual. La sesión se crea automáticamente en la carpeta base elegida en el Wizard.

---

## 7. Qué hacer si no hay señal (p2p bajo, timeout)

### Timeout: el espectro no llega

**Síntoma:** log muestra `4/4 Timeout (35 s) — trigger no llegó.`

**Causas y soluciones:**

| Causa probable | Qué verificar |
|----------------|---------------|
| Warmup insuficiente | Esperar al menos 15 s después del ARM antes de disparar |
| Cable SYNC OUT desconectado | Verificar el cable NL230 → LAMP SYNC del rack |
| Output enable rechazado | Ver línea `[diag] OE_rb=OFF` en el log — revisar el panel físico del NL230 |
| HV+ no alcanzó voltaje | Verificar en el panel NL230 que HV+ muestra ~3542 V |
| Espectrómetro en modo incorrecto | `config/default_experiment.yaml` debe tener `trigger_mode: 3` y `driver: "ocean"` |

### p2p bajo: el espectro llegó pero sin señal de plasma

**Síntoma:** espectro guardado pero los canales muestran solo ruido (sin picos angostos en el canal A UV 294–390 nm).

**Causas y soluciones:**

| Causa probable | Qué verificar |
|----------------|---------------|
| Fibra no apunta al plasma | Ajustar la posición de la fibra óptica sobre la muestra |
| Delay entre trigger y adquisición | [PENDIENTE VERIFICAR EN LAB] Ajustar el QSW delay desde el panel NL230 |
| Tiempo de integración muy corto | Aumentar "Integ (ms)" a 10 ms o más |
| Muestra transparente | La muestra debe absorber suficientemente a 1064 nm |

### Cómo verificar el estado del láser sin disparar

1. Presionar **"🔄 Leer todos los parámetros"** (al final del panel Láser).
2. El log mostrará el valor de cada registro del NL230. Los más importantes:
   - `Output enable = OFF` → correcto cuando no se dispara
   - `Power = ON` → láser armado
   - `Burst mode = Burst` → modo correcto para disparo individual
   - `Sync mode = Internal` → correcto en estado de reposo

---

## 8. Cómo cerrar con SALIR SEGURO

**Siempre usar este procedimiento al terminar la sesión.**

1. Presionar el botón rojo grande **"🛑  SALIR SEGURO"** en la parte inferior del panel de control.
2. El programa preguntará: *"¿Cerrar microLIBS?"* — presionar **Sí**.
3. El log mostrará la secuencia de cierre:
   ```
   Salida segura...
   [shutdown] Ocean HR2000+: cerrado OK
   [shutdown] EKSPLA NL230: OE=OFF, Burst=1, Sync=Internal, cerrado OK
   [shutdown] Thorlabs: home completado, cerrado OK
   [shutdown] Chameleon: adquisicion detenida, cerrada OK
   ```
4. La ventana se cerrará sola.

> **Alternativas al botón:** cerrar la ventana con la X del sistema operativo, o presionar **Escape**, tienen el mismo efecto que "SALIR SEGURO".

> **Qué hace SALIR SEGURO:** detiene el scan si está corriendo → espera 2 s → libera el espectrómetro del modo trigger → apaga Output Enable del NL230 → lleva el stage al home → libera la cámara. El láser queda en estado: `OE=OFF, Sync=Internal, Burst=1`.

> **NUNCA cerrar con Ctrl+C o matar el proceso.** El espectrómetro podría quedar en modo trigger 3 (modo LIBS) y bloquear el USB hasta que se desconecte físicamente.
