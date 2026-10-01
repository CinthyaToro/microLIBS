# Scan paso a paso — microLIBS

**Audiencia:** operador frente al equipo (no requiere conocimiento de programación)  
**Propósito:** definir los puntos del scan, ejecutar el barrido automático y verificar los resultados

---

## 1. Pre-requisito: disparo manual exitoso

**Antes de intentar un scan, verificar que:**

- [ ] El disparo manual funciona (ver `arranque_y_disparo_manual.md`)
- [ ] El log de un FIRE+ADQUIRIR manual muestra `4/4 Espectro OK — 3 canal(es).`
- [ ] El espectro guardado tiene picos visibles en el canal A (UV 294–390 nm)
- [ ] El archivo `config/default_experiment.yaml` tiene `spectrometer.driver: "ocean"` (no `"sim"`)

Si el disparo manual no funciona, el scan tampoco funcionará. No continuar hasta resolver el paso manual.

---

## 2. Cómo definir los puntos del scan

Los puntos se definen en la ventana de **Preview**, que se abre desde el panel de control.

### Abrir el Preview

En el panel "Scan plan (ScanRunner)", presionar el botón **"📷 Preview"**.

Se abre la ventana **"Preview microLIBS — [cámara] [STAGE]"** con:
- La imagen en vivo de la cámara a la izquierda.
- Un panel de control a la derecha.
- Una barra de calibración en la parte superior.

### Verificar la calibración

La barra superior indica el estado de la calibración:
- `✅ Calibrado | X mm/px X | Y mm/px Y | rot Z°` → hay calibración; los puntos tendrán coordenadas mm. **Recomendado.**
- `⚠ Sin calibración — los puntos no tendrán coordenadas mm` → [PENDIENTE VERIFICAR EN LAB] sin calibración, el scan necesita que en el panel principal se configure el modo "Pasos en mm" con las distancias reales.

Para cargar una calibración existente: presionar **"📂 Cargar cal."** y navegar hasta el archivo `.json` de calibración.

### Tres formas de definir los puntos

En el panel derecho hay pestañas:

#### Pestaña " Clicks "

La más simple. **Click izquierdo sobre la imagen** para agregar un punto. El número aparece en la imagen.

- **Click derecho** sobre un punto: lo elimina.
- Botón **"↩ Deshacer"**: elimina el último punto.
- Botón **"🗑 Limpiar todos"**: borra todos los puntos.

Los puntos se listan numerados en el panel con sus coordenadas (mm si hay calibración, píxeles si no).

#### Pestaña " Grilla "

Genera una grilla regular dentro de una zona rectangular.

**Requisitos:**
1. Tener una calibración activa (sin calibración, el botón genera error).
2. Dibujar el ROI: hacer **click y arrastrar sobre la imagen** para definir el área de scan. El rectángulo aparece superpuesto sobre la imagen.

**Parámetros de la grilla:**
- **Paso X (mm)** y **Paso Y (mm)**: distancia entre puntos. Por defecto 0.20 mm.
- **Serpentina**: si está marcado, el recorrido alterna dirección fila por fila (más eficiente).
- **Origen**: esquina de inicio del barrido.

Después de configurar los parámetros, presionar **"⟳ Generar grilla"**. El sistema mostrará cuántos puntos generó y los dibujará sobre la imagen.

#### Pestaña "  CSV  "

Para cargar una lista de coordenadas desde un archivo.

- Presionar **"📂 Abrir CSV..."** y seleccionar el archivo.
- El CSV debe tener columnas `x_mm,y_mm` o `px,py`. La primera fila puede ser encabezado.
- El log mostrará `✅ N puntos cargados desde [archivo]`.

#### Pestaña " Sesión ant. "

[PENDIENTE VERIFICAR EN LAB] Permite cargar el plan de una sesión anterior.

### Exportar el plan

Una vez definidos los puntos (por cualquier método), presionar el botón verde **"💾 Exportar plan"**.

El archivo `scan_plan.json` se guarda en la carpeta de la sesión actual. El log del panel principal confirmará el plan cargado.

> **Si no se exporta el plan, el scan no puede iniciarse.** El botón "▶ INICIAR SCAN" mostrará un error: *"No se encontró scan_plan.json."*

---

## 3. Parámetros del scan

Todos los parámetros del scan se configuran en la sección **"Scan plan (ScanRunner)"** del panel principal.

### Modo de movimiento

| Opción | Cuándo usar |
|--------|-------------|
| **Pasos en mm** | Cuando los puntos del plan son posiciones en píxeles y se quiere mover el stage en distancias fijas. Requiere ingresar Paso X(mm), Paso Y(mm), Origen X y Origen Y. |
| **Escala px/mm del plan** | Cuando los puntos del plan ya tienen coordenadas mm (plan exportado con calibración activa). El stage se mueve a las posiciones exactas del plan. |

Para LIBS con calibración activa, usar **"Escala px/mm del plan"** (los mm vienen del plan).

### Parámetros en modo "Pasos en mm"

| Parámetro | Valor por defecto | Qué hace |
|-----------|------------------|----------|
| **Paso X(mm)** | 0.20 | Distancia entre columnas del barrido |
| **Paso Y(mm)** | 0.20 | Distancia entre filas del barrido |
| **Origen X** | 0.0 | Posición X del primer punto (mm desde la posición actual) |
| **Origen Y** | 0.0 | Posición Y del primer punto (mm desde la posición actual) |

### Otros parámetros del scan

| Parámetro | Valor por defecto | Qué hace |
|-----------|------------------|----------|
| **Settle(s)** | 0.20 | Tiempo de espera (segundos) después de mover el stage, antes de disparar. Dar más tiempo si el stage vibra. |
| **Max pts(0=todos)** | 0 | Límite de puntos a procesar. `0` = procesar todos los del plan. Útil para pruebas parciales. |
| **Stop on error** | Marcado | Si está marcado, el scan se detiene ante el primer error crítico. Si desmarcado, continúa aunque falle un punto. |

### Parámetros del espectrómetro (en el archivo YAML)

Estos se configuran en `config/default_experiment.yaml` antes de iniciar main.py:

| Parámetro | Valor para LIBS | Significado |
|-----------|-----------------|-------------|
| `trigger_mode` | `3` | Trigger por hardware (LAMP SYNC). No cambiar. |
| `integration_us` | `5000` (5 ms) | Tiempo de integración del espectrómetro. Ajustar si la señal es muy débil o muy fuerte. |
| `averages` | `1` | Promedios por adquisición. Para LIBS pulsado siempre 1 (cada pulso es único). |

### Parámetros del láser (en el archivo YAML)

| Parámetro | Valor para LIBS | Significado |
|-----------|-----------------|-------------|
| `n_pulsos` | `1` | Pulsos por punto de scan. Empezar con 1. |

### Umbral de señal (signal_threshold)

El scan rechaza un espectro si la variación pico a pico del canal A es menor a **300 cuentas** (valor fijo en el código). Si la señal es válida pero menor a 300, el scan reintentará hasta 3 veces antes de marcar el punto como fallido.

[PENDIENTE VERIFICAR EN LAB] Si el plasma real produce señales consistentemente por encima de 300 cuentas en canal A, este umbral es correcto. Si la señal real es más baja, se necesita ajustar el código.

---

## 4. Cómo ejecutar el scan

1. Verificar que el plan está cargado: la barra de estado debe decir "Plan cargado: N puntos." después de exportar desde el Preview.
2. Si no hay plan actual: usar el botón **"📋 Plan anterior…"** para cargar un `scan_plan.json` de una sesión anterior.
3. El láser debe estar armado (**ARM** presionado, log muestra "✅ Láser ARMADO.").
4. Presionar el botón verde **"▶ INICIAR SCAN"**.

El botón "▶ INICIAR SCAN" queda gris (deshabilitado) y se habilita el botón rojo **"⏹ DETENER"**.

El log del panel mostrará:
```
▶ SCAN N pts | laser=LaserProxy | inv_y=True | .../scan_plan.json
```

---

## 5. Qué muestra el log durante el scan

### Por cada punto procesado

```
[HH:MM:SS] ✅ Punto 1 ok=True
[HH:MM:SS] ✅ Punto 2 ok=True
```

O en caso de fallo:
```
[HH:MM:SS] ⚠️ Punto 3 ok=False
```

### Detalle de adquisición de espectro por punto

Para cada punto, el scan interno genera mensajes que empiezan con `[ScanRunner]`:

**Intento exitoso al primer intento:**
```
[ScanRunner] [acq] intento 1/3
[ScanRunner] [acq] p2p chA=4250 (umbral=300)
```
Significa: canal A tiene variación pico a pico de 4250 cuentas, supera el umbral de 300. Espectro aceptado.

**Intento con señal débil, reintento:**
```
[ScanRunner] [acq] intento 1/3
[ScanRunner] [acq] p2p chA=85 (umbral=300)
[ScanRunner] [acq] senal insuficiente (p2p=85<300), reintentando...
[ScanRunner] [acq] intento 2/3
[ScanRunner] [acq] p2p chA=3100 (umbral=300)
```
El segundo intento fue exitoso.

**Timeout (trigger TTL no llegó):**
```
[ScanRunner] [acq] intento 1/3
[ScanRunner] [acq] timeout (35 s) — trigger no llego, intento 1
```
El espectrómetro esperó 35 segundos y no recibió el trigger del láser.

**Fallo de láser:**
```
[ScanRunner] [acq] intento 1/3
[ScanRunner] [acq] fallo laser intento 1: [descripción del error]
```

### Resumen al finalizar

Cuando el scan termina (todos los puntos procesados o se presionó DETENER):
```
[HH:MM:SS] Scan completo: N/M puntos OK en T.T s
```
Los botones vuelven al estado inicial: "▶ INICIAR SCAN" habilitado, "⏹ DETENER" gris.

---

## 6. Qué pasa cuando un punto falla

Si un punto no produce espectro en los 3 intentos:

- El log muestra `⚠️ Punto N ok=False`
- El espectro del punto queda marcado como `nan_placeholder = True` en el archivo de resultados
- **El scan continúa con el siguiente punto** (no se detiene)
- El archivo `scan_summary.json` incluye el punto con la indicación de fallo

Esto significa que los datos de ese punto no son válidos, pero el resto del scan sí lo es. Al analizar los datos, filtrar los puntos con `nan_placeholder = True`.

> **Excepción:** si "Stop on error" está marcado y el fallo es de tipo crítico (por ejemplo, el stage no pudo moverse), el scan se detiene en ese punto.

---

## 7. Dónde quedan guardados los espectros

Todos los archivos del scan se guardan dentro de la **carpeta de sesión** creada automáticamente al iniciar main.py.

La carpeta de sesión está dentro de la carpeta base elegida en el Wizard, con el formato:
```
~/microLIBS_captures/[Muestra]_[YYYYMMDD_HHMMSS]/
```

Dentro de esa carpeta:

| Archivo / Carpeta | Contenido |
|-------------------|-----------|
| `scan_plan.json` | Plan de puntos usado para el scan |
| `scan_summary.json` | Resumen de todos los puntos: ok/fallo, p2p, intentos usados |
| `spectra/` | Carpeta con todos los espectros adquiridos |
| `spectra/espectro_[punto]_[ts].csv` | Espectro crudo de cada punto (columnas: channel, wavelength_nm, intensity) |
| `images/` | Fotos tomadas en cada punto (pre y post disparo) |
| `events/` | Log JSON de cada evento |

> Los CSV de espectros tienen tres columnas: `channel` (A, B o C), `wavelength_nm` (longitud de onda), `intensity` (cuentas).

---

## 8. Cómo cerrar con SALIR SEGURO

**Al finalizar el scan, siempre cerrar con SALIR SEGURO:**

1. Si el scan todavía está corriendo: presionar **"⏹ DETENER"** y esperar a que el log confirme que terminó.
2. Presionar el botón rojo **"🛑  SALIR SEGURO"** en la parte inferior del panel.
3. Confirmar en el diálogo: **Sí**.

El log mostrará la secuencia de cierre (espectrómetro → láser → stage → cámara). Esperar a que aparezcan todos los mensajes `OK` antes de apagar el equipo físico.

> **El stage volverá al home automáticamente** durante el SALIR SEGURO. Este proceso puede tardar hasta 30 segundos. No apagar el stage durante el home.

> Ver `arranque_y_disparo_manual.md` sección 8 para más detalles sobre el proceso de cierre.
