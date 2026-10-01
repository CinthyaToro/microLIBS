# Datos de placa y de manual — transcripción literal (27-Sep-2026)

Transcripción de las tablas de los manuales de los instrumentos, hecha para cerrar los
huecos `[PENDIENTE]` de `docs/paper/manuscrito.md`.

**Todo lo que sigue está transcrito de una fuente concreta, y cada tabla dice cuál.** Las
fuentes son fotografías que viven en Google Drive, fuera del repo:

| Sigla | Dónde | Qué es |
|---|---|---|
| `[DOC/aaaammdd_hhmmss]` | `G:\Mi unidad\MicroLIBS\Documentacion\` | foto de la página o de la chapa |
| `[PDF-LIBS]` | `G:\Mi unidad\MicroLIBS\soft ocean optics\LIBS2500plusInstall.pdf` | manual Ocean Optics, doc. `166-00000-000-02-0108` |

Valor **manuscrito** sobre el formulario impreso se marca con *(m)*. Es el dato de fábrica
de esta unidad, no la especificación de la serie.

---

## 1. Láser — EKSPLA **NL231-100** (serie NL230)

> ⚠️ **El modelo es NL231-100, no "NL230".** NL230 es la serie; el manual y la etiqueta
> del lomo dicen NL230 porque cubren toda la familia. La unidad de este laboratorio es
> **NL231-100, S/N DNL022**. Donde el repo y el manuscrito dicen "EKSPLA NL230", debería
> decir "EKSPLA NL231-100 (serie NL230)".

### 1.1. Identificación — §3.1 y §11.1 `[DOC/20251021_155213]` `[DOC/20251021_155629]`

| Campo | Valor |
|---|---|
| Modelo | NL231-100 |
| Número de serie | DNL022 |
| Fabricante | EKSPLA |
| Campos de uso previstos | OPO, bombeo de Ti:zafiro y de láser de colorante, reparación de TFT-LCD, espectrometría de masas, sensado remoto, LIDAR, LIF, PIV, **LIBS**, ESPI, médico, imagen fotoacústica |

El manual **nombra LIBS explícitamente** entre los usos previstos. Sirve para el manuscrito.

### 1.2. §3.2 Beam Output Characteristics `[DOC/20251021_155223]`

| Parámetro | Especificación |
|---|---|
| Wavelength, nm | **1064** |
| Pulse energy, mJ | **>150** |
| Pulse energy stability, StdDev | <1 % |
| Repetition rate, Hz | **100** |
| Pulse duration, ns @ FWHM | **3…7** |
| Beam profile | Hat-top en campo cercano; próximo a gaussiano en campo lejano |
| Beam divergence, mrad (ángulo completo @ 1/e²) | <3 |
| Polarization | Lineal, >95 % |
| Beam diameter, mm | ~5 |
| Jitter relativo al pulso SYNC interno, ns | <0,4 (StDev) |

### 1.3. §3.3 Power Supply Requirements `[DOC/20251021_155223]`

| Parámetro | Especificación |
|---|---|
| Supply voltage | 100…240 VAC |
| Frequency | 50/60 Hz |
| Phase | 1 |
| Amps | 16 A |
| Power consumption | <1000 W |

### 1.4. §3.4–3.5 Entorno y refrigeración `[DOC/20251021_155223]` `[DOC/20251021_155227]`

| Parámetro | Especificación |
|---|---|
| Fluido | Agua destilada (solo sistemas refrigerados por agua). No peligroso |
| Ambient operation temperature | 18…27 °C |
| Relative humidity | 20…80 % (sin condensación); hasta 80 % por debajo de 31 °C |
| Uso | Interior, altitud hasta 3000 m |
| Fluctuación de red admisible | ±10 % del nominal |
| Contaminación del aire | ISO 9 (aire de sala) o mejor |
| Agua de refrigeración externa | T ≤ 20 °C, caudal ≥ 8 l/min, presión 1…8 bar |
| Norma de seguridad citada | IEC 1.4.1.31010-1 |

### 1.5. §3.6 Dimensiones mecánicas `[DOC/20251021_155227]`

Cabezal láser ≈ **325 × 165 × 250 mm** (cotas del plano: 325/305 largo, 165/128 ancho,
250/200 alto), tolerancia ±3 mm. Peso ~15 kg.

### 1.6. Capítulo 11 — Datasheet of Components `[DOC/20251021_155629]`

**11.2 Componentes eléctricos**

| Componente | Tipo | Nº de serie |
|---|---|---|
| Power supply | **PS8001DR-48** | 17-776 |
| Cooling unit | HYDAC RKHIW-00400-L-R22-MI-17-DI | 2300015559 |
| Laser diodes | QD-Q1903-L3-EKS | CM47005, CM47006 |

> Esto **cierra la hipótesis abierta en CLAUDE.md** sobre el nombre de la fuente de poder.
> Es `PS8001DR-48`, confirmado por dos vías independientes: esta tabla y la serigrafía del
> frente del equipo `[DOC/20251021_150828]`.

**11.3 Componentes ópticos** (serie NL230)

| Componente | Tipo | Código |
|---|---|---|
| Cavity mirror 0° | OC | P5BK7-BK7MO75V664X8301-DP5 |
| Pockels cell | PC | P5BBO-BBOXS06C20Z1-AA0 |
| Laser rod | R | P5YAG-G11N5-50W0/0A1 |
| Cavity mirrors 0° | RM | P5BK7-BK7SO73V30001-0H0 |
| Thin-film polarizers | POL1, POL2 | P5UVS-UVSAR56D1-PA5 |

### 1.7. Capítulo 12 — Factory Settings `[DOC/20251021_155638]`

Todos los valores son manuscritos sobre el formulario impreso: son **los de esta unidad**.

| Parámetro | Valor *(m)* |
|---|---|
| I<sub>PUMP SET</sub> | 271 A |
| I<sub>PUMP DISPLAYED</sub> | 271,7 A |
| LD Pulse Width | 150 µs |
| LD Pulse Width for Off/Adj | 140 µs |
| T<sub>WATER</sub> | 25 °C |
| MAX Q-SW delay | 155 µs |
| ADJ Q-SW delay | 300 µs |
| **U<sub>HV</sub>** | **3550 V** |
| Sync In → QSW IN delay para disparo externo | 320 µs |

> ⚠️ **U<sub>HV</sub> de fábrica es 3550 V.** CLAUDE.md dice "verificar que esté en ~3542 V".
> No coinciden. 3550 V es el valor de fábrica escrito por EKSPLA; de dónde salió el 3542
> hay que rastrearlo antes de citar cualquiera de los dos en el manuscrito.

**Nota manuscrita al margen de la misma página** — cableado hacia el espectrómetro:

```
PARA EL LIBS 2500+ :
   LIBS2500+        LÁSER
   Q-SWITCH    —    QSW-IN
   TRIG        —    SYNC IN
   SYNC        —    SYNC OUT
```

### 1.8. Capítulo 13 — Test Data (medición de fábrica) `[DOC/20251021_155644]`

**13.2 Energías de salida y estabilidad**

| λ, nm | Energía de salida medida, mJ *(m)* | Estabilidad, % StdDev *(m)* |
|---|---|---|
| 1064 | **155,8** | **0,2** |

**13.3 Otros parámetros del haz**

| Parámetro | Valor *(m)* |
|---|---|
| Pulse duration (FWHM) @1064 nm, ns | **4,3** |
| Optical pulse jitter (StDev), ns | **0,2** |

Oficial de ensayo: K. Masolskas (firma). **Fecha de aprobación: 2017-03-18.**

Descargo impreso en la misma página: *"Actual values after final installation may be
different from indicated values above, caused by factors such as different environmental
conditions and measurement errors within a specified error allowance of measurement tools."*

> Esto es **energía medida, con fecha y firma**, no valor de catálogo. Para el manuscrito
> es la diferencia entre "el fabricante declara >150 mJ" y "esta unidad entregó 155,8 mJ el
> 18-03-2017 a la salida del cabezal". Sigue sin ser la energía **en el plano de la
> muestra**, que es lo que el manuscrito necesita y que nunca se midió.

### 1.9. Chapa física del equipo `[DOC/20251021_152433]`

```
CLASS 4 LASER PRODUCT
IEC 60825-1: 2014
MAX OUTPUT:      200 mJ
PULSE DURATION:  3-6 ns
WAVELENGHT:      1064 nm     [sic, así está impreso]
LASER MEDIUM:    Nd:YAG
```

### 1.10. Discrepancias entre las tres fuentes del láser

| Parámetro | Manual §3.2 | Chapa | Test Data |
|---|---|---|---|
| Energía | >150 mJ | 200 mJ (máx.) | 155,8 mJ (medido) |
| Duración de pulso | 3…7 ns | 3–6 ns | 4,3 ns (medido) |
| λ | 1064 nm | 1064 nm | 1064 nm |

No se contradicen —son cota inferior, cota superior y medición— pero **el manuscrito debe
decir cuál cita y por qué**. Lo defendible: duración 4,3 ns y energía 155,8 mJ medidas en
fábrica (2017), con la aclaración de que no se remidieron en el plano de la muestra.

---

## 2. Espectrómetro — Ocean Optics **LIBS2500plus**

### 2.1. Appendix A — Specifications `[PDF-LIBS, p. 39]`

| Especificación | Valor |
|---|---|
| Dimensiones (versión 7 canales) | 33,4 × 15 × 14 cm |
| Peso (versión 7 canales) | 6,36 kg |
| Rango espectral | 200–980 nm |
| Resolución | **0,1 nm (FWHM)** |
| Detección | CCDs con **14.336 píxeles** combinados (7 × 2048) |
| Frame rate | 10 Hz, controlado por computadora |
| **Tiempo de integración** | **2,1 ms**; variable en modo free-run |
| **Trigger delay** | **−121 µs a +135 µs en pasos de 500 ns**, controlado por computadora |
| **Trigger jitter** | **±250 ns** |
| Trigger level | TTL, no exceder 5,5 V |
| Conexión | USB 1.1 |
| Software | OOILIBSplus |
| Alimentación | 5 V, <1 A |
| Fibra de entrada | 2 m, multimodo, SMA + lente colimadora |
| Bastidor 7 canales | 84HP × 3U (130 × 483 × 350 mm) |
| Certificación | CE |

> **Éste es el "retardo declarado" que faltaba en el manuscrito.**

### 2.2. Canales A–G del catálogo `[PDF-LIBS, p. 15]`

| Canal | Rango |
|---|---|
| LIBS-CH-A | 200–305 nm |
| LIBS-CH-B | 295–400 nm |
| LIBS-CH-C | 390–525 nm |
| LIBS-CH-D | 520–635 nm |
| LIBS-CH-E | 625–735 nm |
| LIBS-CH-F | 725–820 nm |
| LIBS-CH-G | 800–980 nm |

El manual aclara: *"Channels do NOT have to be consecutive"*.

**Correspondencia con los 4 módulos de este equipo** (rangos según CLAUDE.md y los CSV de
scan; la asignación es mía, por superposición de rangos, y conviene confirmarla contra las
etiquetas ópticas de cada módulo):

| Módulo | Rango observado | Canal de catálogo probable |
|---|---|---|
| HR+C1911 | 293–390 nm | B (295–400) |
| HR+C1912 | 388,8–518,3 nm | C (390–525) |
| HR+C1914 | 520–630 nm | D (520–635) |
| HR+C1915 | 625+ nm | E (625–735) |

> **Consecuencia para el manuscrito: este sistema no tiene canal A.** No cubre 200–295 nm.
> El rango real es ≈295–735 nm, no los 200–980 nm del sistema completo de 7 canales. Si el
> manuscrito cita "200–980 nm" como rango del instrumento, está citando el catálogo, no el
> equipo.

### 2.3. Lo que el manual dice sobre el retardo `[PDF-LIBS, cap. 3, pp. 19-21]`

La cadena de conceptos de OOILIBSplus:

- **Laser 1 Delay / Laser 2 Delay** — µs que se le dan al láser para cargar las lámparas
  antes de disparar.
- **"Q-Switch Zero"** — punto cero calculado a partir de los dos anteriores.
- **Integration Start Delay** — tiempo desde Q-Switch Zero hasta que el espectrómetro
  empieza a adquirir.
- **Cumulative Q-Switch Delay** — el retardo total.

Cita textual sobre la cuantización: *"The spectrometer's internal clock operates on .41667
µs pulses and all time-based events occur at a multiple of that value."* Y la barra
deslizante mueve el Integration Start Delay *"in .41667 µs intervals"*.

> ⚠️ **El manual se contradice consigo mismo.** El Apéndice A declara pasos de **500 ns**;
> el capítulo 3 declara el reloj interno en **0,41667 µs** (416,67 ns = 1/2,4 MHz) y dice
> que *todos* los eventos temporales son múltiplos de ese valor. No son el mismo número.
> Si el manuscrito cita la resolución del retardo, tiene que decir cuál de los dos y que
> el manual no es consistente.

### 2.4. Operación canal por canal — qué dice el manual

El manuscrito afirma que **la operación canal por canal no está documentada**. Revisado el
manual completo (64 páginas), esa afirmación **se sostiene**, con este matiz:

- El manual describe el sistema como un conjunto: *"All spectrometers are triggered to
  acquire and read out data simultaneously"* (p. 2).
- El procedimiento de puesta en marcha es asignar cada módulo a un canal (Unit A…G) dentro
  de OOILIBSplus, por número de serie, y operarlos juntos desde ahí `[PDF-LIBS, pp. 16-17]`.
- **No hay ninguna sección sobre operar un módulo HR2000+ de forma independiente fuera de
  OOILIBSplus.** Lo más cercano es la nota de que para convertir un HR2000+ suelto en un
  LIBS2500-1PLUS hay que **devolverlo a fábrica para una actualización de firmware**
  `[PDF-LIBS, p. 3]` — lo que confirma que los módulos no son intercambiables sin más.

Redacción defendible para el manuscrito: *"el manual de instalación y operación describe
únicamente la operación simultánea de los canales a través del software del fabricante; no
documenta el direccionamiento individual de los módulos, que es el modo en que este
trabajo los opera."*

### 2.5. Láser recomendado por el fabricante `[PDF-LIBS, p. 2]`

Ocean recomienda el **ULTRA CFR Nd:YAG de Big Sky Laser Technologies**, 1–20 Hz, con
estabilidad de pulso ±3 % a 1,06 µm. Requisitos declarados: haz de baja divergencia,
Q-switch electro-óptico activo, y disparo y sincronización externos para lámpara y
Q-switch.

> El EKSPLA NL231-100 no es ese láser. Eso es exactamente lo que hace interesante la
> sección de intercambiabilidad del manuscrito, y conviene decirlo: el acople
> láser↔espectrómetro de este trabajo está fuera de la combinación prevista por el
> fabricante.

### 2.6. Módulo 4 — etiquetas internas `[DOC/HR2000Plus-Modulo4/20260429_113228, _113231]`

Serigrafía de la placa interna, leída en la sesión de reparación:

```
Ocean Optics Inc.  HR4000  2008
ASSEMBLY 210-22000-001 Rev D   (también se lee 210-22000-000)
```

Etiqueta de configuración óptica pegada al chasis: `H10 | <390> | WG305 | 010 | B S 1 S`

> **Esto hay que resolverlo antes de publicar.** La placa dice **HR4000**, y todo el
> proyecto llama a estos módulos **HR2000+**. Puede ser que compartan placa madre, o que
> el módulo 4 no sea lo que creemos. No lo doy por resuelto.
>
> La etiqueta óptica, en la nomenclatura de Ocean, se lee: rejilla **H10**, arranque en
> **390 nm**, filtro clasificador de orden **WG305**, rendija de **10 µm**. Eso encaja con
> el canal C (390–525 nm), es decir con el módulo 1912.

---

## 3. Platina — Thorlabs

### 3.0. Datos de la tesis doctoral de C. Toro `[TESIS]`

Fuente: tesis doctoral de C. Toro (2015), 204 páginas. El sistema descrito
es **MiMeXAL** (micromecanizado por ablación láser), cuyo posicionador es un conjunto
Thorlabs controlado por LabVIEW/APT. **La tesis no nombra el modelo**; da las cifras.

**Descripción del conjunto** (Cap. 2, ítem c, p. 2-50):

> *"un micro-nanoposicionador de 3 ejes cartesianos (XYZ) al que se fija rígidamente la
> pieza. El movimiento se imprime por medio de 5 motores paso a paso y 3 motores
> piezoeléctricos, controlables por una computadora y que alcanzan **precisión nanométrica
> (20 nm)** y tiene un **recorrido de hasta 104 mm**"*

**Desglose** (Apéndice B, p. XIX–XX):

| Subsistema | Ejes | Recorrido | Resolución | Velocidad | Aceleración |
|---|---|---|---|---|---|
| Paso a paso, plataforma de 3 ejes | X, Y, Z | hasta **4 mm** | **20 µm** (por el acoplamiento magnético) | 20 µm/s … 2,5 mm/s | 4 mm/s² |
| Piezoeléctricos | X, Y, Z | rango **20 µm** | **1 µm** sin realimentación | señal hasta 200 Hz | — |
| Paso a paso, 2 platinas XY de largo recorrido | X, Y | hasta **100 mm** c/u | **15 µm** | máx. 10 mm/s | 12 mm/s² |

Los 104 mm del texto principal = 4 mm (plataforma de 3 ejes) + 100 mm (platina de largo
recorrido). Los 8 motores = 5 paso a paso + 3 piezoeléctricos.

**Resolución del mecanizado alcanzada** (§2.3, p. 2-71): *"A partir de la información
obtenida de las micrografías y perfilometrías de las cavidades se obtuvo una resolución
menor a 10 µm."*

> ⚠️ **Dos cifras de precisión que no son la misma cosa.** El cuerpo de la tesis dice
> "precisión nanométrica (20 nm)" —que es la especificación del fabricante para el piezo en
> lazo cerrado— y el Apéndice B dice **20 µm** de resolución para los motores paso a paso
> *"por el acoplamiento magnético"* y **1 µm** para el piezo *sin realimentación*. Son tres
> números distintos para tres cosas distintas. Si el manuscrito cita uno, tiene que decir
> cuál y en qué condición.
>
> Lo honesto para el manuscrito, si se confirma que es la misma platina: **resolución de
> 20 µm en el eje motorizado**, que es la que efectivamente se usa en un scan de microLIBS
> (el piezo no interviene), y no la nanométrica de catálogo.

> ✅ **Confirmado por la autora (27-Sep-2026): es la misma platina.** La plataforma de 3
> ejes de la tesis es la MAX342/M que hoy usa microLIBS. Las cifras del Apéndice B sirven
> como fuente propia y citable.
>
> **Cifra que va al manuscrito: 20 µm.** Es la resolución del modo paso a paso, el único
> que interviene en el barrido. Se menciona que los piezos de la misma platina llegan a
> 1 µm, para que quede claro que la platina tiene más resolución disponible de la que el
> mapeo usa. Ya está aplicado en `docs/paper/manuscrito_v2.md` y `seccion2_v2.md`, con la
> tesis como referencia 7.

**Lo que la tesis NO tiene:** el valor de **repetibilidad** de la platina (ni
bidireccional ni unidireccional), el modelo Thorlabs, y cualquier dato de la cámara
Chameleon o del microscopio Celestron. Revisadas las 204 páginas por búsqueda de texto.

### 3.1. Manual fotografiado en Drive

El material fotografiado es el manual del **controlador**, no de la platina:
*"One-, Two-, and Three-Channel Stepper Motor Controller"* (familia BSC10x, software APT),
26 fotos en `[DOC/20260220_*]`.

Contenido fotografiado: índice, capítulos 1–5 (instalación eléctrica, puesta en marcha,
tutorial de operación, referencia de software) y el **Apéndice D** (Motor Control Method
Summary, listado de métodos ActiveX).

**El Apéndice C — "Specifications and Associated Parts" — NO está fotografiado.** Las 4
primeras fotos del lote empiezan ya dentro del Apéndice D (p. 58).

Por lo tanto, **la repetibilidad y la resolución de la MAX342/M siguen sin fuente.** Y aun
con el Apéndice C, sería un manual de controlador: las especificaciones de la platina
están en su propia hoja de datos, que no está en Drive.

---

## 4. Estado de los `[PENDIENTE]` de instrumento del manuscrito

| Dato que pedía el manuscrito | Estado | Fuente |
|---|---|---|
| EKSPLA — longitud de onda | ✅ 1064 nm | §3.2 + chapa |
| EKSPLA — energía | ✅ >150 mJ nominal / 155,8 mJ medido | §3.2 + Cap. 13 |
| EKSPLA — duración de pulso | ✅ 3…7 ns nominal / 4,3 ns medido | §3.2 + Cap. 13 |
| EKSPLA — tasa de repetición | ✅ 100 Hz | §3.2 |
| LIBS2500plus — retardo declarado | ✅ −121…+135 µs, pasos de 500 ns | Apéndice A |
| LIBS2500plus — operación canal por canal no documentada | ✅ confirmado leyendo el manual completo | §2.4 de este doc |
| Thorlabs — resolución | ✅ **20 µm** (paso a paso) / 1 µm (piezo sin realim.) | Tesis C. Toro 2015, Ap. B |
| Thorlabs — recorrido, velocidad, aceleración | ✅ 4 mm · 20 µm/s–2,5 mm/s · 4 mm/s² | Tesis C. Toro 2015, Ap. B |
| Thorlabs MAX342/M — **repetibilidad** | ⚪ **no se declara** — decisión del 27-Sep: el manuscrito reporta resolución, no repetibilidad | — |
| **Chameleon — modelo** | ✅ **CMLN-13S2M**, s/n 11470397, mono, 1280×960, USB 2.0 | `calibration/chameleon_11470397_defectmap.json` |
| Microscopio Celestron — modelo | ❌ **sigue faltando** | — |

## 5. Backlash, repetibilidad y el orden del barrido

Pregunta que surgió el 27-Sep: *¿el backlash del que habla Thorlabs es lo mismo que la
repetibilidad?* No, pero está causalmente ligado, y la distinción tiene consecuencia
directa sobre el código del scan.

- **Backlash** (juego mecánico) es el movimiento perdido **al invertir el sentido**. Es
  **sistemático y direccional**, no aleatorio. Por eso APT/Kinesis expone un parámetro de
  *backlash distance*: el controlador sobrepasa el destino y se aproxima siempre desde el
  mismo lado.
- **Repetibilidad unidireccional** es la dispersión al volver al mismo punto **llegando
  siempre desde la misma dirección**. El backlash no contribuye.
- **Repetibilidad bidireccional** es la dispersión llegando desde cualquiera de los dos
  lados. Ahí el backlash domina, y no se manifiesta como dispersión sino como **dos modos
  separados** por la distancia del juego.

**Consecuencia concreta para microLIBS.** La grilla se genera en serpentina
(`preview_panel.py:1187`), **y la serpentina está activada por omisión**
(`preview_panel.py:625`, `v_serp = tk.IntVar(value=1)`); la documentación de operación la
describe como *"más eficiente"*. En serpentina, **las filas pares e impares recorren X en
sentidos opuestos**: si hay backlash no compensado, aparece como un **corrimiento
sistemático en X, fila por fila**, es decir un patrón de peine en el mapa. No es ruido: es
un sesgo con estructura, y se confunde fácilmente con estructura de la muestra.

Dos salidas, ninguna verificada todavía:

1. Comprobar que el driver aplique la compensación de backlash de Kinesis/APT. Si la
   aplica, la serpentina es segura y no hay nada que hacer.
2. Si no la aplica, ofrecer barrido unidireccional (rastreo con retorno en vacío). Cuesta
   tiempo de barrido y lo gana en validez espacial.

**Es medible sin espectrómetro y sin láser**: basta mover la platina en serpentina sobre
un patrón y mirar las micrografías. Entra en la lista de laboratorio.

### Lo que apareció y el manuscrito todavía no contempla

1. El modelo real del láser es **NL231-100**, no NL230.
2. El sistema **no tiene canal A**: el rango real es ≈295–735 nm, no 200–980 nm.
3. El manual del espectrómetro **se contradice** sobre la resolución del retardo
   (500 ns vs 0,41667 µs).
4. El fabricante recomienda otro láser (Big Sky ULTRA CFR); esta combinación está fuera de
   lo previsto — es material para la sección de intercambiabilidad.
5. U<sub>HV</sub> de fábrica es **3550 V**, no 3542 V.
6. La placa del módulo 4 dice **HR4000**.
