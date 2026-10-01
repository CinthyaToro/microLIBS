# Hallazgos de montaje que aparecieron al revisar los registros

**30-09-2026 · C. Toro · para N. Boggio y C. Rinaldi**

Preparando el manuscrito para LIBS-Spectra revisé los directorios de sesión archivados
(~234 sesiones entre el Drive y el portátil del laboratorio). Aparecieron **ocho cosas que
se pueden medir a partir de lo que el sistema ya registró**, y que hasta ahora
discutíamos a ojo.

Esta nota no es una conclusión sobre ninguna medición previa: es la lista de lo que los
registros permiten afirmar hoy, de dónde sale cada número, y qué haría falta para
cerrarlo. Sirve como agenda de laboratorio de acá al **15 de octubre**.

Conviene separar dos cosas que se mezclan al decir «el sistema no está listo». La capa que
**ejecuta y registra** el procedimiento anda: mueve, fotografía, dispara, adquiere y deja
el conjunto en un directorio autocontenido. Lo que no está resuelto es la **técnica sobre
este banco** —spot, foco, energía, número de pulsos—, que no son parámetros del software
sino del montaje y de la física. Los ocho puntos de abajo son de la segunda clase. Que
hayan salido a la luz es, justamente, para lo que se construyó la primera.

---

## Los ocho

| # | Hallazgo | Qué dice el dato | De dónde sale | Qué lo cierra |
|---|---|---|---|---|
| 1 | **La cámara mira en oblicuo, y es cuantificable** | La pastilla, circular de 10,0 mm, se proyecta como elipse de razón de ejes **≈1,25**. La escala difiere ~25 % entre direcciones: 7,4–7,7 µm/px sobre un eje, 9,2–9,7 sobre el otro | Micrografía de `muestra1/session_20251223_141130`, ajuste de elipse al borde de la pastilla | Calibración con tablero, midiendo cuánto varía la escala a lo largo del campo |
| 2 | **El cráter es ~3 veces mayor de lo que veníamos diciendo** | **≈0,7 mm** (83 × 84 px a media profundidad), no 200 µm. Contra el objetivo de 50 µm del Ishikawa, ~14× | Misma micrografía, con la pastilla de 10 mm como referencia. Coincide con la estimación visual original de «al menos 500 µm» | Campaña con N variable y medición por **método D²** con iluminación controlada |
| 3 | **Un pulso no deja marca resoluble** | La diferencia pre/post está dentro del ruido en los 5 puntos, con 1 pulso por punto en modo alineación | Los 5 pares pre/post de esa sesión | Repetir con N = 1, 5, 10, 20, 50 en posiciones separadas |
| 4 | **Los puntos de los barridos de zinc están más juntos que el cráter** | Separaciones reales: 08-09 → **0,19–0,33 mm**; 04-09 → 0,18–0,52 mm; 29-06 → 0,63–1,69 mm. Con un cráter de 0,7 mm no son puntos independientes | `scan_plan.json` de las tres sesiones, coordenadas en mm | Un barrido con paso mayor que el cráter, aunque sean 4 puntos |
| 5 | **La calibración que se usa es de dos puntos** | `n_points: 2`, matriz de escala isótropa + rotación: una **semejanza** (4 DOF), no la afín de 6 que el código admite. No puede representar el escorzo del punto 1 | `muestra_01/calibrations/calibration_thorlabs__chameleon_…json` | Ajustar con **≥3 puntos** (gratis, mueve de 4 a 6 DOF) y después decidir si hace falta homografía |
| 6 | **La energía del láser no se programa ni se registra** | Todas las corridas usaron el nivel de alineación, fijado con el control remoto. **Ningún directorio guarda con qué energía se disparó**, ni hay dato de repetibilidad | Ausente en todos los descriptores | Medirla en el plano de la muestra, y agregarla al descriptor de sesión |
| 7 | **La identificación de los canales es ambigua** | Tres numeraciones distintas: el catálogo Ocean (por rango), el programa de adquisición (posicional desde A) y la posición efectiva de junio con 3 módulos. «Canal B» designa tres módulos distintos | Manual LIBS2500plus §A y los CSV de las dos campañas | Usar **siempre el número de serie**. El controlador ya selecciona por serial |
| 8 | **La trazabilidad tiene dos agujeros concretos** | (a) Con la capa genérica el registro guarda el índice, no el modelo: en ~234 sesiones la palabra «Celestron» sólo aparece donde alguien la tipeó a mano. (b) Las sesiones de zinc tienen `calibration.json` en ceros aunque el plan trae coordenadas en mm, y `timing_calibration: not_run`, `focus_z: placeholder` | Descriptores de sesión | Dos arreglos chicos en el controlador y guardar la calibración efectivamente aplicada |

---

## Agenda de laboratorio, por rendimiento

1. **Cráter contra número de pulsos, por D².** Es el único ítem que convierte la
   limitación más grande del manuscrito en un resultado. Requiere iluminación controlada y
   una calibración decente, o sea que arrastra al punto 5.
2. **Energía en el plano de la muestra, y su repetibilidad.** Cierra una laguna de
   reproducibilidad que hoy el manuscrito declara como tal.
3. **Calibración con ≥3 puntos y barrido del tablero.** Fija la escala de la figura del
   cráter, que hoy es prestada de otra fecha, y decide si hace falta la homografía.
4. **Un barrido con paso mayor que el diámetro del cráter.** Es lo que da derecho a usar
   la palabra «mapeo».
5. **Inclinación real de la lente.** Hoy va como «del orden de diez grados, observada
   visualmente». Medirla separa su contribución de la del escorzo de la cámara.

## Lo que se puede cerrar sin laboratorio

- Las corridas de intercambiabilidad que **no necesitan platina real** — la sustitución de
  cámara y de platina funciona desde el año pasado, pero no hay corridas archivadas que lo
  registren. Rehacerlas **registrando** convierte una declaración de los autores en
  evidencia citable.
- Los dos arreglos del punto 8: fijar ancho y alto de cuadro y guardar el nombre del
  dispositivo enumerado; y volcar al directorio de sesión la calibración efectivamente
  aplicada.
- Pasar todo el manuscrito de letras de canal a números de serie.

---

**Los datos están en** `G:/Mi unidad/MicroLIBS/Micrografias/` (micrografías, dic-2025 a
mar-2026) y en el portátil, `microLIBS_datos/` (campañas de zinc). Las sesiones que
sostienen cada número están indexadas en `docs/sesiones/capturas_hito.md`, con lo que se
verificó de cada una y cuándo.
