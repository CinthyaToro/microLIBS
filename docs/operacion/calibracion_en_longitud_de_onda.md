# Calibración en longitud de onda del LIBS2500+

**Versión 1 · 1 de octubre de 2026**

Cómo verificar y corregir la escala de longitudes de onda de cada módulo, con las fuentes
que se consigan y, mientras tanto, con las muestras que ya hay en el laboratorio.

> **Por qué hace falta.** Al HR+C1912 se le reemplazó la EEPROM dos veces y se le
> reescribieron los coeficientes desde las hojas de fábrica; aun así el triplete azul de
> Zn I aparece corrido **3,9 nm**. El HR+C1915 también tiene la EEPROM intervenida y
> **nunca se verificó**. «Da espectros razonables» no alcanza: el 1912 también los daba.
> Detalle en [`docs/instrumentos/LIBS2500plus.md`](../instrumentos/LIBS2500plus.md).

> **Versión didáctica, para el equipo:** [`docs/medir_el_banco.html`](../medir_el_banco.html)
> cubre además la **caracterización óptica** —foco, tamaño del spot, inclinaciones— con
> glosario y enlaces. Este archivo es el procedimiento técnico del espectrómetro; aquél
> explica por qué unas cosas se calibran y otras se caracterizan.

---

## 1 · Qué se calibra

Cada módulo convierte un **número de píxel** en una **longitud de onda** con un polinomio
de tercer grado:

```
λ(p) = I + C1·p + C2·p² + C3·p³
```

Los cuatro coeficientes viven en la EEPROM. Calibrar es encontrarlos de nuevo midiendo
líneas de longitud de onda conocida y ajustando el polinomio a los pares *(píxel, λ)*.

**Lo que ya sabemos del 1912, y acota el problema.** Los tres corrimientos medidos son
3,81 · 4,02 · 3,95 nm sobre un tramo de 17 nm: **prácticamente constantes**. Si la
dispersión (`C1`) estuviera mal, el error crecería a lo largo del rango. No crece.

Eso apunta al **término independiente `I`** —la longitud de onda asignada al píxel 0— con
la dispersión correcta. Unos 3,9 nm a ~0,063 nm/px son **unos 62 píxeles de desplazamiento**.
Un dígito mal copiado, o una convención distinta sobre cuál es el píxel 0, producen
exactamente esto. Y explica por qué reescribir los coeficientes no lo arregló: si el error
está en la hoja o en la transcripción, reescribirlos lo reproduce.

⚠️ *Son tres líneas, leídas de una figura con unos 0,1 nm de precisión. Hay una componente
de escala chica que no se puede separar del ruido. Con una lámpara y diez líneas esto se
resuelve en una medición.*

---

## 2 · Decidir antes de medir: EEPROM o software

**Recomendación: corregir en software, no en la EEPROM.**

| | EEPROM | Software |
|---|---|---|
| Riesgo | El 1912 lleva **dos EEPROM muertas en tres meses**. Cada escritura es una oportunidad de perder el módulo | ninguno |
| Reversible | no | sí, es un archivo de configuración |
| Versionado | no | queda en git, con fecha y autor |
| Verificable | hay que volver a medir | hay una prueba automática que lo fija |
| Portátil | el módulo lleva su calibración a cualquier programa | solo vale dentro de microLIBS |

La corrección en software es una tabla por **número de serie** —no por letra de canal, por
la deuda técnica 10— que el controlador aplica al construir el eje de longitudes de onda.
La EEPROM queda como está, y si algún día hay que escribirla, los coeficientes ya están
medidos y probados.

**La EEPROM se toca solo si** el módulo tiene que funcionar bien fuera de microLIBS
—con Spectragryph, por ejemplo— y aun así, después de haber validado los coeficientes
por software.

---

## 3 · Fuentes de longitud de onda conocida

Los cuatro módulos y lo que cubre cada fuente:

| | HR+C1911<br>293–390 | HR+C1912<br>389–518 | HR+C1914<br>520–630 | HR+C1915<br>625–735 |
|---|:-:|:-:|:-:|:-:|
| **Lámpara Hg-Ar** (pen lamp) | ✓✓ | ✓✓ | ✓✓ | ✓✓ |
| Lámpara de Hg sola | ✓✓ | ✓ | ✓✓ | — |
| Lámpara de Ne | — | — | ✓✓ | ✓✓ |
| Lámpara de Ar | — | — | — | ✓✓ |
| **Tubo fluorescente / bajo consumo** | ✓ débil | ✓ | ✓✓ | ✓ una línea |
| **Cu + Zn por LIBS** *(lo que ya hay)* | ✓✓ | ✓✓ | ✓ | ✓ una línea |

### La opción que conviene comprar

**Una lámpara de calibración Hg-Ar de pluma** (*pen-ray*, Hg + Ar en el mismo tubo). Es la
fuente estándar para esto, cubre los cuatro módulos de una sola vez, no necesita
alineación fina —basta acercarla a la fibra— y sirve para siempre. Es el instrumento que
convierte esta pregunta en una medición de rutina.

Si solo aparece **Hg**, queda el 1915 sin cubrir. Si solo aparece **Ne**, quedan el 1911 y
el 1912 sin cubrir. Hg-Ar resuelve todo.

### La opción gratuita, para hoy

**Un tubo fluorescente o una lámpara de bajo consumo.** Tienen mercurio adentro y emiten
sus líneas, más unas bandas de los fósforos. Sirven para **detectar un corrimiento** en el
1912 y el 1914 sin comprar nada, que es la pregunta urgente. El vidrio absorbe el UV, así
que el 1911 queda flojo, y arriba de 630 nm casi no hay nada.

**No sirve para un ajuste fino**: las bandas de fósforo son anchas y su centro no es una
línea atómica. Para verificar, sí.

---

## 4 · Líneas de referencia

⚠️ **Verificar cada valor contra NIST ASD antes de usarlo en un ajuste.** Esta tabla es un
punto de partida, no una fuente primaria. Un valor de referencia equivocado produce una
calibración equivocada que parece correcta, que es el peor resultado posible.

**Mercurio (Hg I)** — en lámpara de Hg, Hg-Ar, y en cualquier fluorescente

| λ (nm) | Módulo | Nota |
|---|---|---|
| 296,73 · 302,15 · 312,57 · 313,16 | 1911 | solo con lámpara de cuarzo; el vidrio las absorbe |
| 334,15 · 365,01 | 1911 | la de 365 es intensa y pasa incluso por vidrio |
| 404,66 · 435,83 | 1912 | **las dos más fáciles de ver en un fluorescente** |
| 546,07 | 1914 | la verde, muy intensa |
| 576,96 · 579,07 | 1914 | par amarillo, útil para comprobar la dispersión |

**Neón (Ne I)** — muchas líneas entre 585 y 750 nm. Para el 1915: 626,65 · 640,23 · 650,65 ·
659,90 · 692,95 · 703,24 · 724,52.

**Argón (Ar I)** — para el extremo del 1915: 696,54 · 706,72 · 727,29 · 738,40 · 750,39.

### Patrones propios, sin lámpara

Las líneas del plasma LIBS de un material puro también son referencia conocida.

**Cinc** — la pastilla que ya está en el banco

| λ (nm) | Módulo |
|---|---|
| 328,23 · 330,26 · 334,50 | 1911 |
| 468,01 · 472,22 · 481,05 | 1912 — *es el triplete donde se detectó el corrimiento* |
| 636,23 | 1914 o 1915, según dónde caiga el borde |

**Cobre puro** — si hay muestra disponible

| λ (nm) | Módulo |
|---|---|
| 324,75 · 327,40 | 1911 — resonantes, ojo con la autoabsorción |
| 510,55 · 515,32 | 1912, cerca del borde superior |
| 521,82 | 1912 o 1914, según el borde |
| 578,21 | 1914 |

**Sodio** — aparece como contaminación de la pastilla: 588,99 · 589,59 en el 1914.

**Qué alcanza con Cu + Zn:**

- **1911** — cuatro a seis líneas: alcanza para ajustar el polinomio.
- **1912** — tres líneas de Zn más dos de Cu: alcanza para ajustar.
- **1914** — Cu 578, Na 589: alcanza para verificar, justo para un ajuste lineal.
- **1915** — Zn 636 si cae adentro: **alcanza para detectar un corrimiento, no para ajustar.**

> Es decir: **con lo que ya hay se pueden verificar los cuatro módulos y corregir dos o
> tres.** El 1915 —el otro intervenido— es justamente el que peor se cubre, y es el
> argumento más fuerte para conseguir la lámpara.

⚠️ **Precaución con las líneas resonantes** (Cu 324,75 / 327,40; Zn 213,8). Se autoabsorben
en el plasma: el pico se achata y se ensancha, y el centro aparente se puede correr. Para
posición sirven, pero si hay alternativa, preferir líneas no resonantes.

---

## 5 · Procedimiento

1. **Modo libre, no disparo externo.** `trigger_mode = 0` (free-running). Con lámpara no
   hay TTL que esperar. Con LIBS, el procedimiento normal del banco.
2. **Tiempo de integración** tal que la línea más intensa llegue a la mitad o dos tercios
   de la escala. **Nunca saturada**: un pico recortado tiene el centro mal definido.
3. **Fondo primero.** Un espectro con la fuente apagada, para restar.
4. **Varias adquisiciones** del mismo espectro y promediarlas. Mejora el centro de cada
   pico sin tocar nada más.
5. **Centro de cada línea por centroide**, no por el píxel máximo. El máximo tiene la
   resolución de un píxel; el centroide, una fracción.
6. **Armar los pares (píxel, λ)** con la tabla de referencia, de a una línea identificada
   sin ambigüedad. Ante la duda, descartarla.
7. **Ajustar el polinomio.** Con 4 o más líneas, tercer grado. Con 3, segundo grado. Con 2,
   solo se puede corregir el desplazamiento, no la dispersión.
8. **Guardar los coeficientes por número de serie**, con la fecha, la fuente usada y los
   residuos del ajuste.

### Cómo saber si salió bien

- **Residuos** de cada línea por debajo de la resolución del módulo, 0,1 nm FWHM. Si alguno
  se va mucho, probablemente esté mal identificada.
- **Residuos sin estructura**: repartidos al azar alrededor de cero. Si crecen hacia un
  extremo, falta un grado en el polinomio o hay una línea mal asignada.
- **Verificación independiente**: medir una línea que **no** se usó en el ajuste y comprobar
  dónde cae. Es la única comprobación que vale.
- **Volver a medir el triplete de Zn**: si el corrimiento de 3,9 nm del 1912 desapareció,
  cerró el asunto.

---

## 6 · Qué registrar

El directorio de sesión debería quedar con:

- fuente usada, con su identificación
- las líneas empleadas, con su valor de referencia **y de dónde salió**
- el píxel medido de cada una y el método del centro
- los coeficientes ajustados y los residuos
- tiempo de integración, modo de disparo y número de promedios
- el espectro de fondo

Sin eso, dentro de un año esta calibración va a ser tan verificable como las hojas de
fábrica que ya nos fallaron.

---

## 7 · Primer paso, hoy

Si no hay lámpara todavía:

1. **Un fluorescente apuntando a la fibra**, en modo libre. Buscar 404,66 · 435,83 en el
   1912 y 546,07 en el 1914.
2. Si el 1912 las muestra corridas ~3,9 nm, **el corrimiento está confirmado con una
   segunda fuente independiente**, sin depender del plasma ni de la pastilla.
3. Si el 1914 las muestra en su lugar, **ese módulo queda descartado** y el problema se
   acota a los dos con EEPROM intervenida.

Son veinte minutos y no requiere ni láser ni platina.
