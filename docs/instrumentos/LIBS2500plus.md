# LIBS2500plus — lo que sabemos del instrumento

*Documento vivo. Última actualización: 25-Sep-2026.*

> **Para qué existe este archivo.** El fabricante discontinuó el soporte y la documentación
> no se actualiza, pero el equipo sigue acá y se lo puede interrogar. Todo lo que sigue se
> obtuvo construyendo el control propio, y **no está en los manuales**. Si vive solo en la
> cabeza de quien lo descubrió, no es transferible — que es exactamente el problema que el
> proyecto dice resolver.
>
> Las bitácoras registran *cuándo* se descubrió cada cosa y con qué método. Este documento
> registra *qué sabemos hoy*, consolidado. Si los dos se contradicen, gana la bitácora más
> reciente y hay que actualizar esto.

---

## 0 · El equipo

Rack **LIBS2500plus** (Ocean Optics) con cuatro módulos **HR2000+**, 2048 píxeles cada uno,
detector lineal CCD. Entrada de disparo externo **LAMP SYNC** en el rack, alimentada por
cable BNC desde el SYNC OUT del láser.

| Serial | Canal | Rango aproximado |
|---|---|---|
| `HR+C1911` | A | UV, 293,8 – 390 nm |
| `HR+C1912` | B | 388,8 – 518,3 nm |
| `HR+C1914` | C | VIS, 519,6 – 630 nm |
| `HR+C1915` | D | NIR, 624 – 729 nm |

Los cuatro están operativos desde sep-2026. Durante el congreso se trabajó con tres
(ver §5).

---

## 1 · Los módulos se pueden operar de a uno — **no documentado**

### Qué dice el manual

Que el rack distribuye la señal de sincronismo a los cuatro módulos, de modo que **los
cuatro adquieren en simultáneo sobre un mismo disparo**, con el retardo que el propio manual
declara. Eso es el comportamiento nominal del instrumento y **no es un hallazgo**.

### Qué no dice el manual

Que **cada módulo puede seleccionarse y operarse por separado**, adquiriendo con
independencia del resto. No aparece en la documentación del fabricante.

### Cómo se verificó

Por **dos vías independientes**, que es lo que le da peso:

| Vía | Quién | Cómo |
|---|---|---|
| Software de terceros (Spectragryph) | Norberto Boggio | operando un módulo por vez y también los cuatro en conjunto |
| microLIBS | este repositorio, por su lado | `spectrometer.modulos_activos` en el YAML, selección **por número de serie** |

En microLIBS se comprueba con:

```bash
python tools/evidencia_canales.py
```

que corre el mismo barrido con 4, 3, 1 y ningún módulo declarado. El log del driver muestra
explícitamente qué módulo entra y cuál se saltea:

```
[spec] Módulo HR+C1911: OK (2048 pts)
[spec] Módulo HR+C1912: SKIP (excluido por config)
[spec] Módulo HR+C1914: SKIP (excluido por config)
[spec] Módulo HR+C1915: SKIP (excluido por config)
[spec] resultado: 1/4 OK
```

### Por qué importa

1. **Se puede trabajar solo con los módulos que cubren las líneas de interés** de un
   material dado, en vez de arrastrar los cuatro siempre.
2. **Se puede diagnosticar un módulo sin desmontar el resto** — que es lo que permitió
   aislar las fallas de abril de 2026 (§5).
3. Es lo que hace que la **independencia del número de canales** sea una propiedad real del
   sistema y no una degradación ante avería.

### ⚠️ Lo que falta antes de publicarlo

**Abrir el manual del LIBS2500plus y confirmar que efectivamente no está documentado.** Hoy
va escrito como afirmación en el manuscrito (§3.5), y es de las pocas cosas que un revisor
con el manual a mano refuta en un minuto. Si no se llega a verificar, hay que suavizarlo a
*«no encontramos documentación de esta posibilidad»*.

---

## 2 · ⚠️ Seleccionar por identidad, nunca por posición

`hal/drivers/ocean_spectrometer.py:613` hace `ranges_to_use[:n]`. Es decir: **si se declara
`n_channels` sin `modulos_activos`, el driver toma los *primeros n* de la lista.**

Eso ya mordió una vez. Al dar de alta el `HR+C1912` como canal B (commit `7b0b3df`), toda
corrida configurada con 3 canales **pasó a operar sobre un conjunto distinto de módulos, en
silencio**. Se detectó porque rompió el golden.

**Regla: declarar siempre `modulos_activos` por número de serie.** Es R6 —ningún parámetro
suelto—: un índice posicional no puede hacer de identidad de instrumento.

---

## 3 · Banco de registros del FPGA

Caracterizado por lectura diferencial —foto del banco, cambiar un parámetro conocido, foto
otra vez, sobre **el mismo módulo**— el 17 y el 24 de septiembre de 2026. Detalle completo y
método en `docs/bitacora/2026-09-24.md`. Los 42 mapas crudos están en `fpga_map_*.csv`.

### Protocolo, tal como se comporta

| | |
|---|---|
| Formato de respuesta | 3 octetos: `<eco de la dirección> <valor_lo> <valor_hi>`. El eco confirma que el FPGA entendió el pedido |
| Valor | u16 **little-endian**, los 2 octetos finales |
| Alineación | el firmware **ignora los 2 bits bajos** de la dirección: `0x00`–`0x03` devuelven lo mismo. El espacio real son los múltiplos de 4 |
| Espacio direccionable | `0x00`–`0xFF`, o sea **64 registros reales** |
| Registro no implementado | devuelve `0xDEAD` (fijo en `0x1C`, `0x20`, `0x24`, `0x34`) |
| Ruido | **ninguno.** Dos lecturas seguidas sin tocar nada dan cero diferencias: una sola lectura alcanza |

### Registros descifrados

**`0x18` — tiempo de integración, unidad mínima de 10 µs.** Confirmado en dos jornadas
distintas, con el valor por omisión del propio código como testigo.

| Integración | `0x18` |
|---|---:|
| 10000 µs (default de `ocean_control.py`) | 1000 |
| 2100 µs (mínimo del HR2000+) | 210 |

> **De yapa, y no es menor: el período base del temporizador del FPGA es de 10 µs.** Eso
> condiciona la resolución de cualquier parámetro temporal del instrumento.

**`0x2C` — configuración de disparo derivada.** Determinista por modo e idéntico en los
cuatro módulos. **Colapsa modos**, así que no es el registro del modo: es algo derivado.

| Modo | `0x2C` | Lectura |
|---|---:|---|
| 0 · Free-running | 0 | trigger interno |
| 1 · Software | 0 | trigger interno |
| 2 · HW Level | **1** | trigger externo por hardware |
| 3 · Ext. Sync | **2** | sincronismo externo |
| 4 · HW Edge | **1** | trigger externo por hardware |

---

## 4 · La capacidad de fijar el retardo de adquisición **no está en estas unidades**

Es un resultado negativo, y está acotado con precisión:

- **Los dos backends** de la biblioteca —`pyseabreeze` y `cseabreeze`— *declaran* la feature
  `SeaBreezeAcquisitionDelayFeature`, con sus métodos `get_delay_microseconds`,
  `set_delay_microseconds`, mínimo, máximo e incremento.
- Los **HR2000+ reales**, consultados bajo `cseabreeze` —el que opera sobre el driver nativo
  del fabricante— informan **`acquisition_delay (n=0)`**: cero instancias.

**O sea: no es que la biblioteca no la exponga; es que el dispositivo no la tiene.**

Evidencia cruda: `tools/Salida_probe_seabreeze_delay_CON-HARD.txt`. Se reproduce con:

```bash
python tools/probe_seabreeze_delay.py --device
```

El recorrido completo de las 64 direcciones del FPGA tampoco reveló ningún registro de
retardo. Quedan cuatro candidatos en cero sin verificar.

### Hipótesis abierta

En el protocolo OOI el modo de trigger parece fijarse con **un comando propio**, no
escribiendo un registro. Si el modo tiene su opcode dedicado, **el retardo podría tenerlo
también** — y entonces no está en ningún registro y el mapeo no lo va a encontrar por más
direcciones que se barran.

El único método que no puede dar resultado ambiguo es **capturar el tráfico USB** (USBPcap +
Wireshark) mientras un software que sí lo haga escriba el retardo: muestra el comando real
que sale, sea un `0x6A` a un registro o un opcode desconocido.

### Pista sin seguir

Los opcodes `0x6B`/`0x6A` y `REG_FPGA_FIRMWARE = 0x04` ya estaban en `ocean_control.py`
antes de todo esto. **Alguien tuvo una tabla de registros delante.** Si aparece ese
documento, se acaban las adivinanzas.

---

## 5 · Reparación a nivel de componente

Sin soporte del fabricante, el mantenimiento del rack lo hace el propio laboratorio.
**Actualizado el 01-10-2026** contra los informes y el manual, que ya existen y están
fechados (ver *Fuentes* al final de esta sección).

**El rack siempre tuvo cuatro módulos y hoy sigue teniendo cuatro.** La numeración «Módulo
2 / Módulo 4» de los informes es informal y no agrega una quinta unidad.

| Unidad | Qué pasó | Método | Estado |
|---|---|---|---|
| **«Módulo 4»** | dejó de ser reconocido | regrabación del FX2 con el *Programmer* de Ocean y el archivo `hr2000v3300A-Chip.iic` | recuperado |
| **HR+C1915** | — | **reprogramado por C. Toro.** Se dio por reparado porque N. Boggio lo probó y lo reportó bien | operativo · **sin verificar en longitud de onda** |
| **HR+C1912** (el «Módulo 2» de los informes) | fallas de EEPROM recurrentes, hasta no enumerar ni como Cypress | C. Toro lo declaró fuera de servicio por no poder darle tiempo de laboratorio. **N. Boggio se propuso repararlo**, lo midió con guía de C. Toro y con IA, concluyó que era la EEPROM: **reemplazada el 13-07-2026**, reprogramada y **con los coeficientes de calibración reescritos** desde las hojas de fábrica. Volvió a fallar: misma EEPROM **cambiada otra vez el 23-09-2026** | operativo — verificado con Spectragryph, microLIBS y `ocean_control` · **corrido 3,9 nm** |

### Dos módulos con dudas, y por qué

De los cuatro, **dos tienen la EEPROM intervenida**: el 1912 y el 1915. Y la EEPROM es
donde viven los coeficientes de calibración. Ninguno de los dos fue verificado contra una
fuente de longitud de onda conocida.

- **HR+C1912** — sabemos que está corrido 3,9 nm, medido contra el triplete azul de Zn I.
- **HR+C1915** — no sabemos. Se dio por bueno porque funcionaba y daba espectros
  razonables, que es exactamente la clase de verificación que el corrimiento del 1912
  demuestra insuficiente: aquel también daba espectros razonables.

**Evidencia que existe y conviene recuperar:** N. Boggio tomó varios espectros con
Spectragryph de la **misma pastilla que hoy está en el banco**. Si en alguno aparecen líneas
identificables del 1915, se puede comprobar su escala sin volver a medir.

⚠️ **Esos archivos no están en Drive: quedan locales en la PC con Windows 7 del
laboratorio.** Es el mismo punto único de falla de siempre — evidencia que existe en una
sola máquina y que nadie más puede consultar. Copiarlos es una tarea de cinco minutos en la
próxima sesión, y habilita verificar el 1915 desde el escritorio.

### El informe de fin de vida útil quedó superado

El `Informe_FINAL_Modulo2_HR4000_FVU.docx` del 15-05-2026 declara el módulo **no
recuperable** por defecto de manufactura. **Ese diagnóstico fue revertido por los hechos:**
el módulo se reparó reemplazando la EEPROM y hoy está operativo. El informe conserva su
valor como registro del análisis y de lo que costó —el programador CH341A se quemó en el
intento in-circuit—, pero su conclusión no es la vigente.

**Lo que sí sigue valiendo de ese informe:** el patrón de fallas del 1912 es **crónico**,
con EEPROM rotas de forma recurrente a lo largo de años y dos reemplazos en tres meses. No
es un episodio aislado, y conviene tenerlo presente antes de volver a escribirle la EEPROM.

### Qué más corrigen los documentos

**· Al HR+C1912 sí se le reescribieron los coeficientes de calibración**, y el
corrimiento de 3,9 nm aparece igual. Cita del registro de reparación:

> *«Luego de la carga del archivo fue necesario reescribir […] los coeficientes de
> calibración obtenidos de las hojas de calibración provistas por el fabricante cuando se
> compró el espectrómetro.»*

O sea que **no es un paso que se olvidó.** O los coeficientes no quedaron bien escritos, o
las hojas de fábrica no describen el estado actual del módulo. El manuscrito dice «requiere
una recalibración que aún no se hizo»: **hay que corregirlo.**

Y abre la pregunta que no se puede deducir: **¿hay que verificar también los otros
módulos?** Si al 1912 se le escribieron los coeficientes de fábrica y falla igual, cualquier
módulo cuya EEPROM se haya tocado está bajo la misma sospecha. Se responde de una sola
manera: muestra de longitud de onda conocida, y mirar dónde cae cada línea, módulo por
módulo.

**· El HR+C1915 sí fue reprogramado**, por C. Toro (informado el 01-10-2026). El registro
del 1912 lo llama «módulo sano» y lo usa como referencia de comparación, pero eso describe
su estado en ese momento, no su historia: el 1915 tiene la EEPROM intervenida igual que el
1912. **Lo que dice hoy el manuscrito —que fue reprogramado y falta validarlo— es
correcto**, y el párrafo de arriba explica por qué «anda bien» no alcanza como validación.

### Lo que sigue sin resolverse

⚠️ **No está establecida la correspondencia entre «Módulo N» y el número de serie.** Los
informes de reparación numeran por posición en el rack (Módulo 2, Módulo 4) y el resto del
proyecto identifica por serial (HR+C1911/1912/1914/1915). Hoy el rack tiene cuatro módulos
operativos y uno declarado FVU, así que la cuenta no cierra sola. **Es una pregunta para
Norberto, y es barata.**

⚠️ **El mismo equipo aparece como HR2000+ y como HR4000.** El informe del 04-05-2026 lo
titula «Módulo 2 HR2000+»; el del 15-05-2026, «HR4000 Módulo 2». Se conecta con la
serigrafía `HR4000` de la placa del módulo 4 que registra
`datos_de_manuales_2026-09-27.md` §2.6. **No lo doy por resuelto.**

⚠️ **La tabla de verificación del manual tiene dos canales sin completar:**
`✓ Canal C: HR+XXXX [XXX–XXX nm]` y lo mismo para el D. Es la misma ambigüedad de letras
de la deuda técnica 10 de `CLAUDE.md`, llegando hasta la documentación de reparación.

### Causa probable de las fallas de firmware

El manual la atribuye al conflicto de drivers: **Spectragryph y OOILIBS usan controladores
distintos para el mismo hardware**, y alternar entre los dos deja al FX2 en un estado
vulnerable. Eso explica por qué OOILIBS se sacó definitivamente de la PC con Windows 7/XP.

### Fuentes

Documentos del laboratorio, **fuera del repo**, en poder de C. Toro:

| Documento | Fecha | Qué aporta |
|---|---|---|
| `Manual de Recuperación de Módulos HR2000plus v1.1.docx` | — | El procedimiento de regrabación paso a paso, el conflicto de drivers y el glosario. El archivo de firmware se baja de la página de *legacy spectrometers* de Ocean |
| `Informe_Modulo2_HR2000Plus_Diagnostico_Recuperacion_v1/v2.docx` | 04-05-2026 | Diagnóstico inicial del Módulo 2: «recuperable» |
| `Informe_FINAL_Modulo2_HR4000_FVU.docx` | 15-05-2026 | Reversión del diagnóstico: defecto de manufactura, FVU |
| `1912_postEEprom.docx` | — | La reparación del 1912, con las dos fechas y la reescritura de coeficientes |

Los informes están clasificados **«Interno — PiMoVi/CITEDEF/CNEA»**, con C. Toro como
responsable técnica por CITEDEF y N. Boggio por CNEA. Acá se citan sus hallazgos; los
documentos no se copian al repo.

> **Ya no falta el manual del reemplazo de EEPROM:** el procedimiento está escrito en
> `1912_postEEprom.docx`, con el archivo de firmware, el sistema operativo que hace falta
> (la reprogramación funciona en Windows XP y no en 7) y el origen de los coeficientes.

> Los datos lo confirman: las sesiones de **junio tienen 3 canales** y las de **septiembre
> 4**. La cronología de las reparaciones explica ese salto.

---

## 6 · Cosas sin resolver

### 6.1 · ⚠️ El código no se pone de acuerdo sobre cuál es el modo HW Edge

| Fuente | modo 3 | modo 4 |
|---|---|---|
| `ocean_control.py` UI (`:450`) | Ext. Sync | **HW Edge (LIBS)** |
| `ocean_spectrometer.py` constantes (`:77`) | **HW Edge** | Single Strobe — *«NO usar para LIBS»* |
| `ocean_spectrometer.py` docstring (`:14`, `:43`) | — | **«HW Edge para LIBS»** |
| `CLAUDE.md` y los 4 YAML | **3 = HW Edge LAMP SYNC** | — |

`ocean_spectrometer.py` **se contradice a sí mismo**.

**La evidencia de registros apoya los labels de `ocean_control`:** `0x2C` agrupa los modos 2
y 4 con el mismo valor y deja al 3 solo. Si el 3 fuera HW Edge tendría que agrupar con el 2
—los dos son trigger externo por hardware, solo cambia flanco contra nivel— y no agrupa.

**Producción corre el modo 3.** Si los labels de `ocean_control` son los correctos, el scan
del 18-Jun y los cuatro YAML vienen corriendo en **Ext. Sync y no en HW Edge**.

No está cerrado: el modo 3 *funciona* y capturó espectros con el TTL del LAMP SYNC. Pero es
candidato razonable para el **timeout de 15 s del punto 1** que quedó sin explicar. Se
resuelve en el laboratorio: un scan con cada modo, comparando el arranque en frío.

**No tocar la constante hasta poder probarlo con hardware.** Cambiarla a ciegas rompería lo
único validado.

### 6.2 · Leer varios cuadros seguidos en disparo externo rompe el temporizado

`max_frames = 8` rompía el trigger y por eso no aparecía plasma. **Bajar a una sola
adquisición por punto es lo que hizo aparecer la señal** (corregido 23-Sep-2026; ver
`CLAUDE.md`, no revertir).

Consecuencia que queda abierta: el **keep-best está desactivado**, y los campos
`n_frames_read` / `best_frame_index` / `best_peak_value` del JSON salen de una lectura
única, así que **no significan lo que su nombre promete**. Conseguir keep-best exige repetir
el ciclo completo de adquisición, no leer N cuadros seguidos.

### 6.3 · Una adquisición bloqueada no se puede cancelar

El bloqueo ocurre dentro de `self.spec.intensities()`, en código C de seabreeze, esperando
el TTL. No se resuelve con una bandera de Python. Mitigado acotando la espera del cierre
para que el programa no se cuelgue; el costo es que el USB puede quedar tomado.

### 6.4 · Arranque en frío

En el scan del 18-Jun, el **punto 1 tardó más de 15 s** respondiendo al TTL, y los puntos 2
a 4 no. Sin caracterizar. Posible relación con §6.1.

---

## 7 · Operación: lo que hay que saber

- **`OceanSpectrometer._lock` protege `acquire()` y `disconnect()`**, que son mutuamente
  exclusivos. **No llamar a `close()` ni a `disconnect()` sin pasar por el lock** — riesgo de
  errno 10060 y congelamiento del USB.
- **El espectrómetro va primero en la secuencia de apagado**, para soltar el latch del USB.
  Es un invariante de seguridad, no configuración.
- **`seabreeze` y el software del fabricante son excluyentes por PC**, no por dispositivo:
  el binding de driver es de la máquina. Una PC puede tener el driver nativo y otra WinUSB
  al mismo tiempo, sin conflicto.
- Si el rack «no aparece conectado», **reenchufarlo**: USB zombi.

---

## 8 · Por verificar

1. **Que la operación canal por canal no esté en el manual** (§1) — bloquea una afirmación
   del manuscrito.
2. **El retardo declarado en el manual** del LIBS2500plus — hueco del manuscrito.
3. **Cuál módulo se reparó con cada método** (§5), y el manual del reemplazo de EEPROM.
4. **La contradicción del modo de trigger** (§6.1), con hardware.
5. **Un scan completo con los cuatro módulos** — los YAML ya los declaran.
6. **Barrer los cuatro registros candidatos en cero** que quedaron sin verificar (§4).
7. **Capturar el tráfico USB** mientras se escribe un retardo (§4).
