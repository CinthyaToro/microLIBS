# Sesiones de captura — hitos

Índice de los directorios de sesión que sostienen afirmaciones del manuscrito o
marcan un hito del desarrollo. **Qué sesión es cuál, dónde vive y qué contiene.**

Existe porque localizar estas sesiones se hizo dos veces a mano. Al trabajar en
más de una máquina los directorios quedaron repartidos y el identificador que
cita el manuscrito —fecha y hora— no alcanza para encontrarlos.

- Las **bitácoras** (`docs/bitacora/`) dicen *cuándo* pasó cada cosa.
- Este archivo dice *dónde está el dato y qué se verificó de él*.
- Los **datos crudos no viven en el repo** (regla: mover, no borrar; el crudo se
  archiva afuera). Acá van las rutas.

Para regenerar la tabla: `python tools/inventario_sesiones.py`

---

## Dónde viven los datos

| Máquina | Raíz | Respaldo |
|---|---|---|
| Portátil del laboratorio (usuario `Cin`) | `C:/Users/Cin/microLIBS_datos/` | `G:/Otros ordenadores/Mi portátil (1)/microLIBS_datos/` (Drive) |
| Dell (desarrollo) | `~/microLIBS_datos/`, `~/microLIBS_captures/` | — |
| **Drive, micrografías** | `G:/Mi unidad/MicroLIBS/Micrografias/` | es el propio Drive |

> La tercera raíz es la de las campañas de **micrografía** (dic-2025 a mar-2026),
> anteriores a las campañas de zinc. Los descriptores de esas sesiones guardan
> rutas absolutas que empiezan con `G:/Mi unidad/μLIBS/…`: la carpeta se
> renombró después a `MicroLIBS`, así que las rutas internas ya no resuelven.
> El directorio sigue siendo autocontenido, pero sus rutas absolutas no.

> **Las corridas de laboratorio buenas están en el portátil.** Lo que hay en la
> Dell con esas mismas fechas son sesiones de desarrollo, en varios casos con
> platina simulada y sin imágenes. No confundirlas: tienen fechas vecinas.
>
> **Pendiente (post 30-09-2026):** consolidar todo bajo una raíz única en G:,
> que sincroniza con Drive, y correr el inventario sobre ella.

---

## Hitos

### `session_20260629_121811` — campaña de junio

| | |
|---|---|
| **Ruta** | portátil → `microLIBS_datos/test/session_20260629_121811` |
| **Corrida** | 2026-06-29, 12:27:57 → 12:29:57 |
| **Configuración** | platina `thorlabs` · cámara `opencv` · láser `ekspla` · espectrómetro `ocean` · `trigger_mode: soft_delay` |
| **Etiqueta de cámara** | `Webcam [index 0]` — genérica, **sin identificar el instrumento** (ver más abajo) |
| **Resultado** | 5 puntos · 0 correctos · **5 con advertencia** · 0 errores |
| **Contenido** | 5 espectros CSV (12:28:22 → 12:29:57) · 10 imágenes de 640 × 480 px · 5 eventos `*_WARN.json` |
| **Sostiene** | Manuscrito, Tabla 2 (columna de junio) y Figura 3(a) |
| **Verificado** | 27-09-2026, contra `events/scan_summary.json` y `scan_plan.json` |

Es la campaña donde los cinco puntos agotaron el techo de espera de 15 s sin
recibir la señal de sincronismo, y los espectros quedaron escritos igual por el
controlador del espectrómetro, fuera del paso que los había pedido.

⚠️ En la Dell hay sesiones del mismo 29-06 (`121811` no está entre ellas) con
`stage_driver: thorlabs_sim` y sin imágenes. **No son esta.**

---

### `session_20260908_095420` — campaña de septiembre

| | |
|---|---|
| **Ruta** | portátil → `microLIBS_datos/zinc/session_20260908_095420` |
| **Corrida** | 2026-09-08, 09:55:21 → 09:55:47 |
| **Configuración** | platina `thorlabs` · cámara `chameleon` · láser `ekspla` · espectrómetro `ocean` |
| **Etiqueta de cámara** | `Chameleon/FLIR serial 11470397 (USB2)` — identificada por número de serie |
| **Resultado** | 3 puntos · **3 correctos** · 0 advertencias · 0 errores |
| **Contenido** | 6 imágenes de 1280 × 960 px (+1 compuesta de 1430 × 1248) |
| **Sostiene** | Manuscrito, Tabla 2 (columna de septiembre) y Figura 3(b) |
| **Verificado** | 27-09-2026, contra `events/scan_summary.json` y `scan_plan.json` |

Es el barrido completo sin ninguna advertencia, con los cuatro módulos activos,
tras reducir a una sola lectura por punto.

---

### `session_20260904_135700` — arranque en frío, 1 de 5

| | |
|---|---|
| **Ruta** | portátil → `microLIBS_datos/zinc/session_20260904_135700` |
| **Corrida** | 2026-09-04, 13:57:49 → 13:58:46 |
| **Configuración** | platina `thorlabs` · cámara `chameleon` · láser `ekspla` · espectrómetro `ocean` |
| **Resultado** | 5 puntos · 4 correctos · **1 con advertencia (el punto 1)** · 0 errores |
| **Contenido** | 10 imágenes de 1280 × 960 px |
| **Sostiene** | Manuscrito, Sección 3.1: *«en una segunda sesión de esa campaña, de cinco puntos, solo el primero agotó la espera»* |
| **Verificado** | 27-09-2026; los eventos confirman `point_0001_*_WARN.json` y los puntos 2 a 5 sin marca |

---

### `validacionCelestron/session_20260831_133122` y `_133809` — límite de la capa genérica

| | |
|---|---|
| **Ruta** | portátil → `microLIBS_datos/validacionCelestron/` |
| **Corrida** | 2026-08-31 |
| **Configuración** | cámara `opencv` · platina `thorlabs_sim` |
| **Contenido** | 2 imágenes de **640 × 480 px** cada una |
| **Sostiene** | Manuscrito, Sección 4: la capa genérica captura con la resolución por omisión del subsistema de video, no con la nativa del dispositivo (2592 × 1944 px en el Celestron) |
| **Verificado** | 27-09-2026 |

---

### `muestra1/session_20251223_141130` — la micrografía del cráter (Figura 4)

| | |
|---|---|
| **Ruta** | Drive → `Mi unidad/MicroLIBS/Micrografias/muestra1/session_20251223_141130` |
| **Corrida** | 2025-12-23, 14:13:07 → 14:13:59 |
| **Configuración** | cámara `chameleon` · disparo por **Arduino** (`M14 P200 D0 S1 A0`) · sin espectrómetro · sin platina motorizada |
| **Etiqueta de cámara** | `Chameleon/FLIR serial 11470397 (USB2)` — identificada por número de serie |
| **Operador** | `Marcelo` |
| **Plan** | 5 puntos **en píxeles**, paso 200 px, serpentina, ROI (457, 62, 562 × 468) |
| **Resultado** | 5 eventos, **1 pulso por punto**, sin errores |
| **Contenido** | pares pre/post por punto (1280 × 960) + recortes ROI + `scan_plan.json` |
| **Sostiene** | Manuscrito, **Figura 4** y §3.4 (*Tamaño del spot*, *Geometría del montaje*) |
| **Verificado** | 30-09-2026, contra `session.json`, `scan_plan.json` y los cinco `events/event_000N_*.json` |

**Es además un hito de control, no sólo de imagen: es la primera vez que el láser
se dispara desde otro sistema y no desde su control remoto.** El disparo sale por
Arduino (`M14`), con la iluminación comandada por `M15`. Eso es lo que hace que la
sesión tenga pares pre/post reales y no fotos sueltas.

Lo que se midió sobre ella, con la pastilla de 10,0 mm como referencia de escala:

- **Escala:** 7,4–7,7 µm/px sobre el eje mayor de la pastilla y 9,2–9,7 sobre el
  menor, por ajuste de elipse al borde. Una calibración de regla independiente de
  la misma cámara (`muestra_01/calibrations/calibration_thorlabs__chameleon_…json`,
  10-03-2026, *«Ruler v3 | dist=2.00mm | 246.1px»*) da **8,13 µm/px**, que cae
  entre las dos. La razón de ejes ≈1,25 es el escorzo de la cámara oblicua.
- **Cráter:** 83 × 84 px a media profundidad → **≈0,7 mm**, circular dentro de la
  precisión de la imagen. Es **3 a 4 veces** el valor de 200 µm que el manuscrito
  declaraba como estimación, y ~14 veces el objetivo de 50 µm del Ishikawa.
- **Un pulso no deja marca resoluble:** la diferencia pre/post está dentro del
  ruido en los cinco puntos. El cráter visible **no coincide con ningún punto del
  plan** (está fuera del ROI): viene de disparos repetidos que no quedaron
  registrados.

⚠️ La sesión **no tiene calibración píxel→mm propia** (el plan está en píxeles).
La escala de la Figura 4 es externa a ella y hay que declararlo en el epígrafe.

**Historia del número del cráter, para que no se pierda otra vez** (informado por
la autora, 30-09-2026). El foco del láser nunca se puso a punto: se ajustó a ojo,
y de ahí viene la necesidad de ráfagas de varios pulsos. En esa sesión se estimó
visualmente que el spot era «de por lo menos 500 µm». En algún momento posterior
el manuscrito pasó a declarar 200 µm, sin que quede registro de por qué. La
medición de esta sesión —≈0,7 mm— **concuerda con la estimación visual original**,
no con los 200 µm. Según el taller del spot, con la óptica actual debería
alcanzarse algo cercano a 50 µm, o ~100 µm con ráfaga. Y en todas las corridas se
usó la energía de alineación del láser, **pendiente de medir y de caracterizar su
repetibilidad**.

Sesión hermana, misma configuración y también 5 puntos de 1 pulso:
`muestra1/session_20251223_140311`.

Figura regenerable con `python tools/figura_micrografia.py`.

---

## Lo que el registro NO distingue

**Las cámaras genéricas no quedan identificadas por instrumento.** El descriptor
guarda el backend (`camera_source: opencv`) y una etiqueta genérica
(`Webcam [index 0]`), no el dispositivo. Y como
[`hal/drivers/opencv_camera.py`](../../hal/drivers/opencv_camera.py) nunca fija
el tamaño de cuadro —no hay un solo `set(cv2.CAP_PROP_FRAME_WIDTH, ...)` en el
repo—, todas capturan con el valor por omisión de DirectShow, 640 × 480. Ni la
etiqueta ni la resolución permiten separarlas.

Consecuencia concreta: **de la campaña de junio no se puede determinar, desde el
registro, si la cámara fue el microscopio Celestron o la cámara web.** El
manuscrito la nombra como «cámara genérica USB», que es lo que la evidencia
sostiene.

La Chameleon y los módulos espectrales sí se identifican por número de serie.

### Inventario del Drive (30-09-2026): 115 sesiones, tres backends

Leyendo el campo `camera` de cada `session.json` bajo
`G:/Mi unidad/MicroLIBS/Micrografias/`:

| Backend | Etiqueta registrada | Período |
|---|---|---|
| `chameleon` | `Chameleon/FLIR serial 11470397 (USB2)` | dic-2025 (49 sesiones) y varias de 2026 |
| `opencv` | `Webcam/OpenCV index N` · `Webcam [index N]` · `Webcam [1] Integrated Webcam` | desde 25-02-2026 |
| `folder_sequence` | `Carpeta: imagenesMainL` / `imagenesCalib` | feb-2026, 3 sesiones |

**Todo diciembre de 2025 es Chameleon.** No hay una sola sesión `opencv` en 2025,
de modo que **no existen micrografías del Celestron anteriores a 2026**. Esto
corrige lo que el manuscrito decía en §3.4 («registradas con el Celestron»): la
micrografía del cráter es de la Chameleon, y el descriptor lo prueba por serial.

**Matiz sobre la capa genérica.** No es uniformemente ciega: en algunas sesiones
el rótulo trae el nombre enumerado del dispositivo (`Webcam [1] Integrated
Webcam`, la cámara del portátil) y en otras sólo el índice. Donde trae nombre, sí
identifica; donde cae al índice, no.

**Regla operativa de la autora, para leer los índices** (conocimiento de
laboratorio, no del registro): la cámara web genérica sin aumento recién se
empezó a usar en **junio de 2026**. Por tanto una sesión `opencv` **anterior** a
junio-2026 rotulada sólo con índice es el **microscopio Celestron**. Con ese
criterio son del Celestron 7 sesiones, todas de feb–mar 2026 y todas de 640×480.
Ninguna es de la pastilla: las del 17-03 son imágenes en color de papel
cuadriculado, de calibración.

⚠️ Esa regla **no desambigua la campaña de junio de 2026**, que cae justo en el
mes del cambio. El manuscrito sigue diciendo «cámara genérica USB», que es lo que
la evidencia sostiene.

### La prueba más corta de todo esto (30-09-2026)

Búsqueda de la cadena `celestron`, sin distinguir mayúsculas, en **todos** los
JSON de los dos archivos (~234 sesiones entre el Drive y el portátil). Aparece en
**seis archivos, todos de las dos sesiones `validacionCelestron` del 31-08-2026**,
y en ninguno proviene del dispositivo:

```json
"sample_name": "validacionCelestron",
"camera":      {"kind": "opencv", "id": 0, "label": "Webcam [index 0]"}
```

**En ~234 sesiones, la única vez que el nombre del microscopio quedó escrito fue
porque alguien lo tipeó en el campo de muestra.** El registro nunca lo tomó del
dispositivo: guardó `Webcam [index 0]`.

Es la formulación más compacta de la limitación que el manuscrito declara en §3.4
—la trazabilidad del dispositivo dependió de la memoria del operador y no del
registro— y conviene usarla así, porque se verifica con un solo `grep`.

**Arreglo pendiente** (dos líneas en el controlador, después del 30-09):
fijar explícitamente ancho y alto, y registrar el nombre del dispositivo
enumerado además del índice.
