# Documentación de microLIBS

microLIBS es un sistema de mapeo elemental por LIBS construido integrando instrumentos
que ya estaban en el laboratorio, de distinta procedencia y varios sin soporte del
fabricante: un láser Nd:YAG pulsado, un espectrómetro de cuatro módulos, platinas y
cámaras. Recorre una región de interés, y en cada punto desplaza la platina, registra la
superficie antes y después del disparo, entrega una ráfaga de pulsos y adquiere el
espectro, dejando todo en un directorio autocontenido.

Esta carpeta documenta **los instrumentos y lo que sabemos de ellos**.

---

## Páginas para leer

Son archivos `.html`: se bajan y se abren con doble clic. Todas traen glosario y están
escritas para un equipo multidisciplinario — no hace falta saber óptica ni programación.

| | |
|---|---|
| [**Aprendizajes de LIBS-Spectra**](RedPLA_y_el_banco.html) | Lo que salió de preparar la nota técnica: por qué conviene no confundir el sistema de control con el banco de medición, y cuatro cosas del banco que estaban sin medir y se midieron sobre datos ya archivados. |
| [**Medir el banco**](medir_el_banco.html) | Qué se calibra y qué se caracteriza, y en qué estado está hoy el espectrómetro y la óptica. Si vas a leer una sola, es ésta. |
| [**Taller del spot**](taller_del_spot.html) | Calculadora interactiva del tamaño de spot con las lentes reales de la mesa, y el diagrama de Ishikawa 6M del sistema. |
| [**Globitos de microLIBS**](globitos_microLIBS.html) | El árbol de capacidades del sistema: qué hace cada parte y cómo se llama. |
| [**Cómo abrir estas páginas**](como_abrir_las_paginas.html) | Para quien recibe uno de estos archivos y no sabe qué hacer con él. |

## El instrumento

| | |
|---|---|
| [LIBS2500plus](instrumentos/LIBS2500plus.md) | Todo lo que sabemos del espectrómetro y **no está en los manuales**: la operación canal por canal, el banco de registros del FPGA, la ausencia efectiva del retardo de adquisición y la historia de las reparaciones a nivel de componente. |
| [Datos de placa y de manual](instrumentos/datos_de_manuales_2026-09-27.md) | Transcripción literal de los manuales de los cuatro instrumentos, cada tabla con su fuente. Incluye las discrepancias entre manual, chapa y medición de fábrica. |
| [Montaje óptico](instrumentos/montaje_optico.md) | Dónde viven las fotografías del banco y qué muestran. |

## Operación

| | |
|---|---|
| [Calibración en longitud de onda](operacion/calibracion_en_longitud_de_onda.md) | El procedimiento: qué fuente usar, qué líneas de referencia, cómo ajustar, y cómo saber si salió bien. |
| [Arranque y disparo](operacion/arranque_y_disparo_manual.md) | Lista de comprobación previa a la sesión, armado, disparo, guardado y salida segura. |
| [El scan paso a paso](operacion/scan_paso_a_paso.md) | Generación del plan de puntos, parámetros del barrido y dónde queda cada archivo. |

## Lo medido

| | |
|---|---|
| [Hallazgos de montaje](diagnosticos/2026-09-30_hallazgos_de_montaje.md) | Ocho cosas medibles a partir de lo que el sistema ya había registrado, cada una con su fuente y con qué haría falta para cerrarla. Es la agenda de laboratorio. |
| [Sesiones hito](sesiones/capturas_hito.md) | Qué sesión es cuál, dónde vive y qué se verificó de ella. Existe porque el identificador que citan los informes —fecha y hora— no alcanza para encontrarlas. |

---

## Por dónde empezar

**Si querés entender el instrumento:** *Medir el banco*, y después *LIBS2500plus*.

**Si vas a operarlo:** *Arranque y disparo*, y *El scan paso a paso*.

**Si venís a buscar un dato concreto:** *Datos de placa y de manual* tiene las tablas con
su fuente, y *Sesiones hito* dice de qué corrida salió cada número.

---

## Una advertencia que vale para todo lo que hay acá

Buena parte de lo que se documenta son **limitaciones medidas, no resueltas**. El spot es
varias veces mayor que el objetivo de diseño, un módulo espectral tiene la escala de
longitudes de onda corrida, y la energía del láser nunca se midió en el plano de la
muestra. Están escritas con sus números y con lo que haría falta para cerrarlas.

Es deliberado: el sistema registra cada sesión de forma autocontenida, y eso permitió
medir sobre datos de hace diez meses cosas que en su momento nadie se preguntó, **sin
repetir ningún experimento**. Un sistema que no encontrara nada no estaría funcionando.
