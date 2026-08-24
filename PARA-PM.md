# PARA-PM — Eneba Steam Wallet (HKD) Price Tracker

Registro de salidas de Claude Code para el chat de Claude que hace de
**project manager**. Entrada más reciente arriba. Cada entrada dice qué se
hizo, qué está verificado, qué NO está verificado y qué bloquea el avance.

Proyecto: `C:\Users\pepo1\Documents\Eneba Checker`
Repo: https://github.com/CharlesAriza/eneba-tracker (privado)

---

## Entrada 010 — 2026-08-24 — Las 6 mejoras implementadas y verificadas en CI

**Estado:** las 6 implementadas, probadas y en `main`. Commits `2cb8cda` y
`1ed0ce9`. **Dos cosas requieren decisión del usuario** (Pages y el peso del
PNG). El punto 6 está construido y probado pero **no publicado**.

### Resumen

| # | Mejora | Estado |
|---|---|---|
| 1 | Umbral de alerta | ✅ probado |
| 2 | Gráfico PNG | ✅ probado, ⚠️ ver peso |
| 3 | Botón en el push | ✅ probado |
| 4 | Multi-producto | ✅ probado, con migración |
| 5 | Mínimo histórico | ✅ probado |
| 6 | Panel GitHub Pages | ✅ construido y probado, ⏸️ **sin publicar** |

### 🔴 Bug encontrado en CI (y por qué mereció la pena ejecutarlo)

El primer despliegue **falló**:

```
UMBRAL_BAJADA_PCT = float(os.environ.get("UMBRAL_BAJADA_PCT", "1.5"))
ValueError: could not convert string to float: ''
```

GitHub Actions **inyecta las variables no definidas como cadena vacía**, no
las omite. Un `${{ vars.UMBRAL_BAJADA_PCT }}` inexistente llega como `""`, y
el valor por defecto de `os.environ.get` nunca entra en juego porque la
variable sí existe: existe vacía.

Corregido con `env_num()`, que centraliza las 5 lecturas numéricas: vacío →
valor por defecto, y un valor mal escrito avisa y continúa en vez de tumbar
la comprobación de precios. Verificado con las variables vacías y con
`UMBRAL_BAJADA_PCT="dos coma cinco"`.

Esto no se habría visto en local: allí las variables sencillamente no existen.

### 1. Umbral de alerta

La bajada debe superar `max(1,5 % del precio anterior, 0,10 €)`.

**Por qué las dos condiciones y no solo euros:** las denominaciones van de
0,60 € a 124 €. Un umbral fijo de 0,20 € es el 2 % en la tarjeta de 100 HKD
(relevante) pero el 0,4 % en la de 500 (ruido). El porcentaje escala solo. El
suelo en euros evita avisar por redondeos en las baratas, donde un 1,5 % son
dos céntimos. El 1,5 % sale de lo observado el 24-08: los movimientos entre
ejecuciones consecutivas rondaban el 0,8 %.

Prueba unitaria (5 casos, todos correctos):

```
OK    100: 11.13 -> 11.08 | baja 0.05 (0.45%) | umbral 0.17 | alerta=False
OK    100: 11.13 -> 10.90 | baja 0.23 (2.07%) | umbral 0.17 | alerta=True
OK    500: 55.23 -> 54.90 | baja 0.33 (0.60%) | umbral 0.83 | alerta=False
OK    500: 55.23 -> 54.20 | baja 1.03 (1.86%) | umbral 0.83 | alerta=True
OK      5:  0.60 ->  0.57 | baja 0.03 (5.00%) | umbral 0.10 | alerta=False
```

El tercer caso es el interesante: 0,33 € de bajada **no** avisa en la tarjeta
de 500, aunque supere los 0,20 € que se proponían como umbral fijo.

Prueba de punta a punta con el script real y la web de verdad:
- Bajada del 0,5 % → `baja 0.05 desde 10.63 (bajo umbral 0.16)` + *"Sin
  bajadas por encima del umbral. No envio alerta."*
- Bajada del 5 % → `BAJA 0.53 desde 11.11` + push enviado.

### 2. Gráfico (`grafico.py` → `historial-<id>.png`)

Script aparte y paso con `continue-on-error`: si matplotlib falla, la
vigilancia de precios (que ya notificó) no se cae con él.

**Primer intento salió ilegible** y se corrigió: pintaba las 34
denominaciones porque las muestras anteriores a la reestructuración las
guardaban todas, y la leyenda de 34 entradas reventaba la figura. Ahora usa
solo las vigiladas. Revisado el PNG resultante: dos paneles (ratio y precio),
leyenda legible, mínimo anotado por serie y el aviso de precio orientativo al
pie. El título dice "ultimas 1 h" cuando no hay días suficientes, en vez de
"ultimos 0 dias".

### ⚠️ Decisión pendiente: el PNG pesa

El PNG ocupa **~116 KB** y se commitea en cada ejecución. Con el cron horario:

| cadencia | por día | por mes | por año |
|---|---|---|---|
| cada hora (ahora) | 2,8 MB | 84 MB | 1 GB |
| cada 2 h | 1,4 MB | 42 MB | 500 MB |
| solo con el resumen diario | 116 KB | 3,5 MB | 42 MB |

Git no comprime PNG (ya viene comprimido) y **cada commit guarda una copia
entera**: el historial no se puede podar sin reescribir el repo.

Se implementó como pedía el encargo (commit en cada ejecución), pero
**recomiendo commitear el PNG solo cuando se manda el resumen diario**: la
imagen es para verla de vez en cuando en el repo, y quien quiera el dato al
minuto tiene el panel web, que se dibuja en vivo. Es un cambio de tres líneas.

### 3. Botón en el push

Cabecera `Actions` de ntfy. Verificado consultando lo que **guardó el
servidor**, no solo que el POST no fallara:

```json
{"action": "view", "label": "Comprar en Eneba", "clear": true,
 "url": "https://www.eneba.com/steam-gift-card-steam-wallet-gift-card-100-hkd-steam-key-hong-kong"}
```

Y esa URL responde **HTTP 200**, no es un enlace roto. El botón apunta a la
ficha de la denominación que bajó (o a la de mejor ratio en el resumen), no
al listado.

**Hallazgo:** Eneba usa **dos slugs distintos** para el mismo tipo de tarjeta
(`…steam-wallet-gift-card-25-hkd…` y `…steam-gift-card-25-hkd…`). El primer
patrón, calcado del que se veía en la página 1, capturaba **22 de 34**
enlaces. Con el patrón laxo se capturan **34 de 34**, confirmado también en CI.

### 4. Multi-producto

Los productos se declaran en `productos.json`; el estado y el histórico van
*namespaced* por `id`. Añadir uno no requiere tocar código.

Incluye **migración del formato antiguo**: sin ella, activar multi-producto
habría tirado el histórico ya acumulado. Verificada — el log dijo
`Migrando historial.json al formato multi-producto (id 'steam-hk')` y las
muestras previas se conservaron.

### 5. Mínimo histórico

Compara contra el mínimo de la retención disponible y **dice la cobertura
real**: `📉 Precio mas bajo visto en 1 hora`, no "en 30 días". El caso de
menos de 30 días de datos —el actual— es el que se ha probado; funciona.

**La retención pasó de 24 h a 30 días.** Era incompatible: el encargo previo
podaba a 24 h, y el mínimo de 30 días, el gráfico y el panel necesitan más.
Para que el archivo no se dispare, **el histórico guarda solo las 3
denominaciones vigiladas**, no las 34: se commitea cada hora y las otras 31
solo se usan en la lectura actual (que sí se guarda entera en `state.json`).

### 🟠 Interacción entre las mejoras 1 y 5 que conviene decidir

El mínimo histórico **es una línea dentro del push, no un disparador**, tal
como se pidió. Pero ahora que existe el umbral, puede darse esto: el precio
toca su mínimo de 30 días con una bajada del 0,5 % → no se supera el umbral →
no se manda push → **la línea del mínimo histórico no se ve nunca**.

Implementado literalmente como se pidió. Si se quiere que un mínimo de 30
días dispare push por sí solo (que es cuando más interesa saberlo), es un
`if` de una línea. Queda a decisión del PM.

### 6. Panel web — construido y probado, SIN publicar

`index.html`: HTML+JS sin frameworks ni dependencias, gráficos SVG dibujados
a mano, tema claro/oscuro automático, selector de rango (24 h / 7 d / 30 d).
Lee `historial.json`, `state.json` y `productos.json` del propio repo.

Probado sirviéndolo por HTTP en local (`python -m http.server`), que es
exactamente como funcionará en Pages. Carga **datos reales**, sin errores de
consola:

- Tarjetas con precio, ratio, min/max del rango y enlace a Eneba.
- "Mejor ratio del catálogo: 50 HKD — 9,58 HKD/€, 34 comparadas".
- Dos gráficos SVG con ejes y etiquetas.
- Tabla de las 34 denominaciones ordenada por ratio, cada una enlazada.

**No se ha publicado, y hace falta una decisión del usuario.** Dos razones:

1. **Pages en repositorio privado requiere plan de pago** (Pro o superior).
   No se pudo confirmar el plan: el token de `gh` no tiene el scope
   `read:user` que expone ese dato.
2. Si el plan no lo permite, la única vía gratuita es **hacer público el
   repositorio**, y eso expondría todo su contenido. Publicar es
   prácticamente irreversible (queda cacheado e indexado), así que no se hace
   sin permiso expreso.

Contenido que quedaría expuesto si se hiciera público: el código, los
precios de Eneba y este registro. **El topic de ntfy NO**: vive en un secreto
de Actions y en el log sale enmascarado. Aun así, la decisión es del usuario.

Mientras tanto el panel se ve en local con `python -m http.server 8000`.

### Verificación final en CI (run 32778592046, éxito)

```
Navegador: chromium de Playwright
Total denominaciones: 34
Enlaces directos capturados: 34
100 HKD -> 11.13 EUR (8.98/€) [sube desde 10.58]
Sin bajadas por encima del umbral. No envio alerta.
Historial: 6 muestras (retencion 30 dias).
steam-hk -> historial-steam-hk.png (6 muestras, 1.3 h)
[main 8f3c4a6] Actualizar estado, historial y grafico [skip ci]
 3 files changed
```

Los 34 enlaces también se capturan desde el runner, y el commit ya incluye
los **tres** archivos (estado, histórico y PNG).

### Pendientes

- **Devolver el cron a `0 */2 * * *`** cuando el usuario dé por terminada la
  fase de prueba. Sigue marcado como TEMPORAL.
- Decisión sobre el peso del PNG (recomendación: commitear solo con el
  resumen diario).
- Decisión sobre GitHub Pages (plan de pago vs. repo público).
- Decisión sobre si el mínimo histórico debe disparar push por sí solo.
- Confirmar que el botón "Comprar en Eneba" se ve y funciona en el móvil: se
  mandó un push real al topic; lo del servidor está verificado, lo de la app
  solo puede confirmarlo el usuario.

### Concepto enseñado

Una variable de entorno vacía no es lo mismo que una variable ausente, y
`os.environ.get(x, defecto)` solo cubre el segundo caso. GitHub Actions
produce el primero, así que el fallo únicamente aparecía en producción. Es el
argumento de siempre: ejecutar en el entorno real, no solo en el propio.

---

## Entrada 009 — 2026-08-24 — Resumen 24h, histórico y catálogo completo

**Estado:** los 7 puntos implementados, probados y subidos. Commit `4ae23cc`
en `main`.

### 🟠 Corrección de alcance en el punto 5: la web tiene 2 páginas

El encargo decía "todas las denominaciones que muestra la página". **La
página 1 solo muestra 20 de las 34** que hay. La página 2 tiene otras 14
(25, 35, 45, 80, 120, 175, 240, 250, 400, 550, 650, 850, 900, 950).

Se comprobó abriendo la página 2 antes de tocar código. Sin paginar, el
punto 6 ("mejor tarjeta de todas") habría dado una respuesta falsa: se
compararía contra 20 tarjetas afirmando que son todas. Por eso la extracción
**recorre las páginas** hasta que una no aporta denominaciones nuevas (tope
configurable, `ENEBA_MAX_PAGINAS=5` por defecto, por si Eneba añade más).

### Lo implementado

| Punto | Estado |
|---|---|
| 1. Cron a cada hora | ✅ `0 * * * *`, marcado como TEMPORAL en el YAML y en el README |
| 2. Histórico 24h | ✅ `historial.json`, cada muestra con epoch + ISO UTC + las 34 denominaciones |
| 3. Resumen diario | ✅ push aparte, se manda haya o no bajadas |
| 4. Limpieza >24h | ✅ verificada (ver pruebas) |
| 5. Todas las denominaciones | ✅ 34, con paginación |
| 6. Mejor tarjeta global | ✅ en el resumen, sobre las 34 |
| 7. Alertas puntuales sin cambios | ✅ siguen solo en 100/200/500 |

También se actualizó el workflow para commitear `historial.json` además de
`state.json`.

### Prueba 1 — extracción completa

```
Pagina 1: 20 denominaciones (20 nuevas)
Pagina 2: 14 denominaciones (14 nuevas)
Pagina 3: no aparecio ningun producto, dejo de paginar.
Total denominaciones encontradas: 34 -> [5, 10, 15, 20, 25, 35, 40, 45, 50,
60, 70, 80, 100, 110, 120, 125, 150, 160, 175, 200, 240, 250, 300, 400, 500,
550, 600, 650, 750, 800, 850, 900, 950, 1000]
```

Contrastado con la web, que declara **"Results found: 34"**. Coinciden las 34,
una a una. La página 3 corta sola, sin necesidad de saber cuántas hay.

Comprobación cruzada de un caso: la mejor tarteja sale **50 HKD a 9,58 HKD/€**,
lo que implica 50 ÷ 9,58 = **5,22 €**; en la web, la ficha de 50 HKD marca
"From €5.22". Cuadra. Y no es ninguna de las tres vigiladas: exactamente el
caso que el punto 6 quería cubrir.

### Prueba 2 — rama de resumen forzada

Se puso `ultimo_resumen` a hace 25h y se inyectaron 12 muestras sintéticas
repartidas en 24h. Resultado:

```
Toca resumen (25.0 h desde el ultimo). Enviando.
```

Mensaje generado (así es como llega al móvil):

```
Ventana: 22.0 h, 12 muestras

100 HKD: ahora 10.58 € | min 10.29 | max 10.78 | sube 0.27
200 HKD: ahora 21.23 € | min 20.67 | max 21.69 | baja 0.05
500 HKD: ahora 52.80 € | min 51.33 | max 54.31 | sube 0.43

Mejor tarjeta ahora mismo: 50 HKD — 9.58 HKD/€ (5.22 €)
(34 denominaciones comparadas)

⚠️ Precio orientativo (servidor en EE.UU.), verificar en Eneba antes de comprar.
```

### Prueba 3 — limpieza del histórico (verificada de rebote)

12 muestras sintéticas + 1 nueva = 13. Quedaron **12**: la más antigua
superaba las 24h y se descartó. El punto 4 no se comprobó "por inspección
del código" sino porque la poda ocurrió de verdad.

### Decisiones que conviene que el PM conozca

**1. El resumen declara la ventana real, no "24h" a secas.** Dice
`Ventana: 22.0 h, 12 muestras`. El primer día el histórico no cubre 24h, y
poner "24h" sería afirmar algo falso. La comparación "hace 24h" se hace contra
la muestra más antigua disponible.

**2. El primer resumen no se manda de inmediato.** Si no hay `ultimo_resumen`,
se inicializa el contador y el primero sale ~24h después. Un "resumen de 24h"
con una sola muestra no informa de nada.

**3. Umbral de 23,5h en vez de 24h.** Con cron horario, exigir 24h clavadas
haría que la hora del resumen se corriese un poco cada día hasta dar la vuelta
al reloj. Con 23,5h se queda estable.

**4. `RATIO_OBJETIVO` sigue necesitando calibrarse** con los valores del
runner (~9,0 HKD/€), no con los de España (~9,45). Documentado en el README y
en el propio código.

### Datos sintéticos: eliminados

Tras las pruebas se borraron `state.json` e `historial.json` y se regeneraron
con una ejecución real limpia. Lo commiteado es 1 muestra genuina con las 34
denominaciones. **No hay ni un dato inventado en el repo.**

### Verificación en CI — ✅ todo confirmado

Run manual https://github.com/CharlesAriza/eneba-tracker/actions/runs/32771341641
(éxito). Extractos del log:

```
Navegador: chromium de Playwright
Pagina 1: 20 denominaciones (20 nuevas)
Pagina 2: 14 denominaciones (14 nuevas)
Pagina 3: no aparecio ningun producto, dejo de paginar.
Total denominaciones encontradas: 34 -> [5, 10, ..., 950, 1000]
100 HKD -> 11.13 EUR (8.98 HKD/EUR) [sube desde 10.58]
200 HKD -> 22.34 EUR (8.95 HKD/EUR) [sube desde 21.23]
500 HKD -> 55.23 EUR (9.05 HKD/EUR) [sube desde 52.80]
Resumen no toca todavia (faltan 23.5 h).
Historial: 2 muestras (ventana de 24 h).
```
```
[main 44505c4] Actualizar estado e historial [skip ci]
 2 files changed, 77 insertions(+), 37 deletions(-)
```

Confirmado punto por punto:
- **Paginación en el runner:** 20 + 14 = 34, igual que en local.
- **Chromium empaquetado**, sin fallback.
- **Precios en EUR** (los de EE.UU.: 11,13 / 22,34 / 55,23).
- **Rama del resumen:** entra por el `else` y dice cuánto falta. El contador
  arrancó en el run anterior, así que 23,5 h es lo esperado.
- **Histórico:** 2 muestras (la genuina local + esta del runner).
- **Commit de los DOS archivos:** `2 files changed`. El paso modificado
  funciona.

El "sube desde" es lo previsto y **no** es una falsa alarma: la línea base
commiteada venía de una ejecución local (precios de España, más bajos) y el
runner ve los de EE.UU. Al ser subida, no dispara alerta. A partir de ahora
compara runner contra runner.

### Pendiente

- **Devolver el cron a `0 */2 * * *`** cuando termine la fase de prueba. Está
  marcado como TEMPORAL en el YAML y en el README, pero requiere confirmación
  expresa según el encargo.
- El primer resumen real llegará ~24h después del primer run con este código.

### Concepto enseñado

"Todas las denominaciones que muestra la página" parecía una instrucción
clara, pero la página mostraba 20 de 34. Cuando un encargo dice "todo", vale
la pena comprobar contra el propio dato de la fuente — aquí, el "Results
found: 34" que la web declara — en vez de fiarse de lo que se ve en la
primera pantalla.

---

## Entrada 008 — 2026-08-24 — Aviso de precio orientativo añadido y subido

**Estado:** hecho. Commit `645e208` en `main` del repo remoto.

### Cambio

La notificación de bajada termina ahora con:

```
⚠️ Precio orientativo (servidor en EE.UU.), verificar en Eneba antes de comprar.
```

Ejemplo de cómo queda el cuerpo del push:

```
100 HKD: 11.13 EUR (8.98 HKD/€) [BAJA desde 12.58]
200 HKD: 22.16 EUR (9.03 HKD/€) [BAJA desde 23.06]
500 HKD: 55.23 EUR (9.05 HKD/€) [igual]
Mejor ratio: 500 HKD (9.05 HKD/€)
⚠️ Precio orientativo (servidor en EE.UU.), verificar en Eneba antes de comprar.
```

Con esto queda **implícitamente adoptada la opción (a)** de la entrada 007:
la alerta se trata como señal relativa y el aviso lo deja explícito en el
propio mensaje, en vez de cambiar la arquitectura o inventar un factor de
corrección.

### Detalle técnico

El aviso va en el **cuerpo** del mensaje, no en la cabecera `Title`. Es
necesario: las cabeceras HTTP solo admiten ASCII y el emoji ⚠️ las rompería.
El cuerpo viaja como UTF-8 (84 bytes esa línea) y ya está comprobado en
ejecuciones anteriores que ntfy lo muestra bien — el símbolo € llegaba
correcto al móvil.

Solo afecta a la notificación de bajada de precio. La notificación de
"tracker roto" no la lleva, porque ahí no hay ningún precio del que avisar.

### Verificación

Cambio menor, sin ejecución completa (criterio del PM). Se comprobó:
- La sintaxis del archivo (`ast.parse`).
- Que la línea está en el código y codifica bien en UTF-8.
- Que el push a `main` subió: `645e208`, 1 archivo, 7 inserciones.

La primera confirmación en vivo llegará con la próxima bajada real que
detecte el cron.

### Bloqueos

- Ninguno.

---

## Entrada 007 — 2026-08-24 — Desplegado y funcionando. Hallazgo: el precio depende de la IP

**Estado:** los 8 puntos del PM ejecutados y verificados. El sistema está vivo
en GitHub Actions. **Pero el despliegue ha destapado un problema de fondo que
requiere una decisión del usuario** (detalle al final).

**Repo:** https://github.com/CharlesAriza/eneba-tracker (privado)
**Run:** https://github.com/CharlesAriza/eneba-tracker/actions/runs/32757200120
(✅ éxito, 44 s)

### Pasos ejecutados

| Paso | Resultado |
|---|---|
| `gh auth status` | ✅ `CharlesAriza`, scopes `gist, read:org, repo, workflow` |
| `gh repo create` privado | ✅ verificado `isPrivate=true`, rama `main` |
| `git push -u origin main` | ✅ commit `58bcc1b` subido |
| `gh secret set NTFY_TOPIC` | ✅ aparece en `gh secret list` |
| `gh workflow run check.yml` | ✅ run 32757200120 |
| Espera + lectura del log | ✅ todos los pasos en verde |

### Los 4 puntos de confirmación del PM

**1. Chromium empaquetado, sin fallback — ✅ CONFIRMADO**
```
Navegador: chromium de Playwright
```
Es la rama de `CI` detectado. No aparece ningún "No se pudo abrir chromium".

**2. Precios en EUR, no USD — ✅ CONFIRMADO**
```
100 HKD -> 11.13 EUR (8.98 HKD/EUR) [BAJA desde 12.58]
200 HKD -> 22.16 EUR (9.03 HKD/EUR) [BAJA desde 23.06]
500 HKD -> 55.23 EUR (9.05 HKD/EUR) [sube desde 54.82]
```
La cookie `exchange=EUR` hace su trabajo desde una IP de EE.UU. Sin ella,
esto habría salido en dólares y el run habría fallado. La corrección de la
entrada 003 queda validada en producción.

**3. Push usando el secreto — ✅ CONFIRMADO**
```
NTFY_TOPIC: ***
Push enviado a https://ntfy.sh/***
```
GitHub enmascara el valor en el log, como debe ser.

**4. Commit automático de `state.json` — ✅ CONFIRMADO**
```
[main ed86295] Actualizar state.json [skip ci]
 1 file changed, 3 insertions(+), 3 deletions(-)
```
Autor: `github-actions[bot]`. El truco del estado falseado funcionó: se
ejercitó el camino real del commit en vez de imprimir "sin cambios".

### 🟠 Hallazgo: el precio depende de la IP desde la que se consulta

Los precios del runner no coinciden con los de España:

| | desde España | desde el runner (EE.UU.) | dif. |
|---|---|---|---|
| 100 HKD | 10,58 € | 11,13 € | +5,2 % |
| 200 HKD | 21,06 € | 22,16 € | +5,2 % |
| 500 HKD | 52,80 € | 55,23 € | +4,6 % |
| ratio | ~9,47 HKD/€ | ~9,02 HKD/€ | |

No es movimiento de mercado: es un desfase uniforme (~5 %) y se reproduce.

**Se investigó si era corregible con cookies. No lo es.** Prueba ejecutada
desde España mandando `region=spain`, `region=united-states` y
`region=germany`: los tres devuelven **10,58 €**. La cookie se conserva
(el servidor no la sobrescribe) pero **no influye en el precio**. Lo decide
la geolocalización por IP en el servidor, seguramente porque el conjunto de
ofertas disponibles varía por país de compra.

**Qué implica:**
- La **detección de bajadas sigue siendo válida**: el workflow compara
  precios de runner contra precios de runner, siempre la misma referencia.
  `state.json` en el repo ya guarda la serie de EE.UU., coherente consigo misma.
- Las **cifras absolutas del push son ~5 % más altas** de lo que el usuario
  pagaría de verdad.
- **`RATIO_OBJETIVO` queda inutilizable tal cual**: un objetivo de 9,60
  calibrado con lo que se ve en España no saltaría nunca desde Actions, donde
  el ratio ronda 9,02. Si se usa, hay que calibrarlo con los valores del
  runner, no con los de casa.

**Opciones (pendiente de decisión del usuario):**
- **a)** Dejarlo así y tratar la alerta como señal relativa ("algo se movió,
  entra a mirar el precio real"). Cero trabajo extra. Recomendada.
- **b)** Ejecutarlo en el PC del usuario con el Programador de tareas de
  Windows en vez de Actions: precios correctos de España, pero solo corre con
  el ordenador encendido.
- **c)** Proxy con salida en España dentro del workflow. Resuelve el fondo
  pero añade dependencia externa, coste y fragilidad. No recomendada.

Se descarta explícitamente aplicar un factor de corrección del 5 %: sería
inventarse un precio que nadie ha visto.

### Estado de verificación

**Verificado en producción:** todo el circuito, de Eneba a ntfy, ejecutándose
solo en GitHub Actions cada 2 horas.

**Pendiente de confirmar por el usuario:** que el push del run 32757200120 le
llegó al móvil en el topic nuevo (`eneba-hkd-1e22f7yall`).

### Bloqueos

- Ninguno técnico. Solo la decisión a/b/c sobre el desfase por IP.

### Concepto enseñado

Desplegar no es el final de las pruebas, es una prueba en sí misma. El mismo
código, en otra máquina y otra red, dio precios distintos — y eso solo se ve
comparando la ejecución real contra la local. Si se hubiera dado el despliegue
por bueno al ver el run en verde, el desfase habría pasado desapercibido.

---

## Entrada 006 — 2026-08-24 — Secuencia de GitHub NO ejecutada: sigue sin login

**Estado:** ningún paso de la lista del PM se ha ejecutado. La secuencia se
detuvo en su primer punto, que es precisamente el que existe para eso.

### Punto 1 — `gh auth status`: FALLA

```
You are not logged into any GitHub hosts. To log in, run: gh auth login
```

Sin cambios respecto a la entrada 005. También se comprobó que no hay
variables `GH_TOKEN` ni `GITHUB_TOKEN` en el entorno que pudieran servir de
alternativa: no hay ninguna.

### Puntos 2 al 7: no ejecutados

`gh repo create`, push, `gh secret set`, `gh workflow run` y la lectura del
log **no se han intentado**. Todos requieren autenticación; lanzarlos habría
producido una cadena de errores sin información útil.

No hay URL de repo que reportar porque no se ha creado ningún repo.

### Qué se necesita

Que el usuario ejecute `gh auth login` en su terminal y complete el flujo en
el navegador. Es interactivo y con credenciales suyas: no procede que lo haga
Claude Code ni manejar un token en su nombre.

### Lo que sigue listo y sin tocar

- Commit local `58bcc1b` en `main`, con los 7 archivos.
- `state.json` commiteado con los precios +2 € a propósito, para que la
  primera ejecución del workflow valide push y commit automático (ver
  entrada 005).
- Topic `eneba-hkd-1e22f7yall` operativo y confirmado.

En cuanto haya login, los 6 pasos restantes se encadenan sin más decisiones
pendientes.

### Bloqueos

- `gh auth login`. Único bloqueo, sin alternativa por parte de Claude Code.

---

## Entrada 005 — 2026-08-24 — Push confirmado en el móvil. GitHub bloqueado por login

**Estado:** el usuario **confirma que le llegó el push al móvil**. Sistema
validado de punta a punta en local. Topic cambiado por uno no adivinable.
Repo local creado y commiteado. **La subida a GitHub está bloqueada: `gh` no
está autenticado y el login es interactivo, lo tiene que hacer el usuario.**

### Paso 2 — confirmado por el usuario: SÍ llegó

Con esto queda validada la cadena completa en local:
Eneba → extracción → comparación → ntfy → móvil.

### Topic cambiado (decisión del usuario)

El usuario optó por sustituir `eneba-hkd-checker` por uno con sufijo
aleatorio. Nuevo topic:

```
eneba-hkd-1e22f7yall
```

Generado con `secrets.choice` (aleatorio criptográfico, no `random`). Se le
mandó un push de prueba y **está confirmado en el servidor de ntfy**:

```
title='Topic nuevo activo'
Si ves esto, el topic eneba-hkd-1e22f7yall funciona. [...]
```

Pendiente: que el usuario se suscriba al nuevo en la app y borre el antiguo.

### Repo local: creado y commiteado

`git init -b main` + commit inicial (`58bcc1b`) con los 7 archivos:
`check_price.py`, `requirements.txt`, `.github/workflows/check.yml`,
`README.md`, `.gitignore`, `PARA-PM.md`, `state.json`.

**Decisión deliberada sobre `state.json`:** se ha commiteado con los precios
**+2 € sobre los reales**. Motivo: el PM pidió confirmar que el paso de commit
automático funciona, pero si el estado subido ya fuera correcto, la primera
ejecución en Actions no encontraría bajada, no cambiaría el archivo, y el paso
imprimiría "sin cambios, no hay nada que commitear" — no se habría verificado
nada. Con el estado falseado, la primera ejecución:

1. detecta una bajada → **valida que el push sale desde Actions con el secreto**,
2. reescribe `state.json` → **valida el commit automático del bot**.

Después el archivo se corrige solo con los precios reales. Está explicado en
el mensaje del commit para que no despiste a nadie que lo lea luego.

### 🔴 Bloqueo: `gh` sin autenticar

```
gh auth status -> You are not logged into any GitHub hosts.
```

`gh auth login` es un flujo interactivo con credenciales. No procede
ejecutarlo por el usuario ni manejar un token suyo. **Lo tiene que hacer él.**

Todo lo demás (crear repo privado, push, secreto, `workflow_dispatch`,
comprobar el log del commit) queda listo para ejecutarse del tirón en cuanto
esté autenticado.

### Estado de verificación actualizado

**Verificado:**
- Extracción de precios reales.
- Detección de bajada.
- El locale no afecta; la cookie `exchange` sí controla la moneda.
- El modo CI no cae a Chrome/Edge.
- `state.json` no gitignorado.
- Push de ntfy: enviado, guardado en el servidor **y recibido en el móvil**.
- Topic nuevo operativo (confirmado en servidor).
- Commit local con los 7 archivos.

**Sin verificar (todo depende del login de GitHub):**
- Ejecución del workflow en Actions.
- Que el Chromium empaquetado funcione en el runner.
- Que el push salga desde Actions leyendo el secreto.
- El commit automático de `state.json` por el bot.

### Bloqueos

- `gh auth login` pendiente (solo el usuario).
- Suscripción al topic nuevo en la app del móvil.

### Siguiente paso

Usuario: suscribirse a `eneba-hkd-1e22f7yall` en ntfy y ejecutar
`gh auth login`. Después, Claude Code encadena: `gh repo create` privado +
push + `gh secret set NTFY_TOPIC` + `gh workflow run` + lectura del log.

### Concepto enseñado

Para probar de verdad un paso condicional ("commitea solo si algo cambió") hay
que provocar la condición. Un workflow que imprime "no había nada que hacer"
no ha demostrado que sepa hacerlo. Por eso el estado inicial va falseado a
propósito: es la única forma de que la primera ejecución ejercite el camino
que interesa comprobar.

---

## Entrada 004 — 2026-08-24 — Push de ntfy enviado y confirmado en el servidor

**Estado:** el push salió y **está confirmado en el servidor de ntfy**. Falta
que el usuario confirme que le llegó al móvil. **GitHub: NO ejecutado**, a la
espera de esa confirmación (instrucción explícita del PM: si no llegó, no
avanzar).

### Paso 1 — ejecución de la prueba: OK

Topic usado: `eneba-hkd-checker`.

Estado falseado (+2 € sobre los precios reales) y ejecución:

```
100 HKD -> 10.58 EUR (9.45 HKD/EUR) [BAJA desde 12.58]
200 HKD -> 21.06 EUR (9.50 HKD/EUR) [BAJA desde 23.06]
500 HKD -> 52.82 EUR (9.47 HKD/EUR) [BAJA desde 54.82]
Push enviado a https://ntfy.sh/eneba-hkd-checker
exit=0
```

### Verificación adicional (no pedida, pero decisiva)

"No hubo excepción" solo prueba que el POST no falló. Para saber si el
mensaje existe de verdad, se consultó la API de ntfy
(`/json?poll=1`) y el servidor **tiene el mensaje guardado**:

```
[19:15:59] title='Eneba: baja el Steam Wallet HKD' prio=4 tags=['chart_with_downwards_trend']
100 HKD: 10.58 EUR (9.45 HKD/€) [BAJA desde 12.58]
200 HKD: 21.06 EUR (9.50 HKD/€) [BAJA desde 23.06]
500 HKD: 52.82 EUR (9.47 HKD/€) [BAJA desde 54.82]
Mejor ratio: 200 HKD (9.50 HKD/€)
```

Esto confirma de una vez: el título ASCII, la prioridad alta (4), el tag, el
cuerpo con el símbolo € correcto (la codificación UTF-8 funciona) y la línea
de "mejor ratio".

**Lo que esto NO prueba:** que el móvil del usuario esté suscrito y haya
recibido la notificación. Eso solo lo puede confirmar él.

### `state.json` quedó correcto

Tras la prueba volvió a guardar los precios reales
(`100: 10.58, 200: 21.06, 500: 52.82`, `fallo_previo: false`). El estado no
quedó contaminado por el falseo.

### Paso 3 (GitHub) — NO ejecutado

Instrucción del PM: solo si llegó el push. Falta la confirmación del usuario,
así que no se ha creado el repo, ni subido nada, ni configurado el secreto.

### Observación de seguridad

El topic `eneba-hkd-checker` es fácil de adivinar. En ntfy.sh cualquiera que
acierte el nombre puede suscribirse (vería solo precios públicos, poco daño)
y **también publicar en él**, es decir, mandarle notificaciones falsas al
usuario. No bloquea nada; el usuario decide si lo cambia por algo con sufijo
aleatorio antes de configurar el secreto en GitHub. Si lo cambia, hay que
cambiarlo en los dos sitios: la app del móvil y el secreto.

### Bloqueos

- **Confirmación del usuario de que le llegó el push al móvil.** Es el único
  bloqueo. Todo lo demás está listo para subir.

### Siguiente paso

Esperar el sí/no del usuario. Si es que sí, en el mismo turno: crear el repo
privado, subir, configurar el secreto `NTFY_TOPIC`, lanzar
`workflow_dispatch` y comprobar en el log el commit automático de
`state.json`.

### Concepto enseñado

Una petición HTTP que devuelve 200 solo dice que el servidor la aceptó, no
que el mensaje sirva. Cuando se puede consultar el otro extremo (aquí, la API
de ntfy), se comprueba: es la diferencia entre "no dio error" y "está ahí y
dice lo que debe".

---

## Entrada 003 — 2026-08-24 — Revisión del PM atendida + bug crítico encontrado

**Estado:** los 3 puntos de revisión, resueltos. **Encontrado y corregido un
fallo que habría roto el proyecto en producción.** Sigue pendiente el push de
ntfy (bloqueado por el usuario) y la subida a GitHub.

### 🔴 Bug crítico: la moneda depende de la IP, no del locale

El PM pidió revisar si el separador decimal dependía del `locale` de
Playwright. Se probó y **el locale no influye**: `en-GB` y `es-ES` devuelven
exactamente lo mismo (títulos en inglés, precios con punto). Pero la
investigación destapó algo peor.

Eneba decide moneda e idioma con **cookies**, fijadas por geolocalización en
la primera visita. Las cookies reales observadas:
`exchange=EUR; lng=en; region=spain`.

Prueba empírica ejecutada:

| cookie | precio de 100 HKD |
|---|---|
| `exchange=EUR` | `€10.58` |
| `exchange=USD` | `$12.35` |

**Consecuencia si no se corrige:** los runners de GitHub Actions tienen IP de
EE.UU. Cada ejecución habría cargado la página en dólares, el patrón (que
exige el símbolo del euro) no habría encontrado nada, y el sistema habría
mandado una falsa alarma de "tracker roto" **cada 2 horas**, indefinidamente.
Nunca habría llegado una alerta de precio real.

**Corrección aplicada:** el script fija explícitamente `exchange=EUR`,
`lng=en` y `region=spain` antes de cargar la página. El resultado ya no
depende de desde dónde se ejecute. Añadido además un diagnóstico: si la
página carga en otra moneda, lo dice con ese mensaje en vez de un genérico
"no se encontró nada".

Nota: el README original asumía coma decimal ("10,58 €") porque la captura
de pantalla se hizo con otra configuración. El texto real hoy usa punto. El
parseo (`a_float`) soporta los dos formatos de todas formas.

### ✅ Punto 1 del PM — Chromium empaquetado en Actions

Confirmado, y además **reforzado**. Antes el orden era: Chromium empaquetado →
Chrome → Edge. En Ubuntu el empaquetado funciona, así que nunca se llegaba al
fallback; pero era una garantía por omisión, no explícita.

Ahora, si existe la variable `CI` (GitHub la pone siempre), **el fallback se
desactiva por completo**: solo se intenta el Chromium empaquetado y, si
fallara, el workflow se rompe en rojo. Mejor fallar ruidosamente que
disimular un problema de instalación con un navegador que no toca.

Verificado ejecutando en este PC (donde el Chromium empaquetado está roto):

```
--- modo CI ---     No se pudo abrir chromium, y no queda alternativa.  (exit=1)
--- modo local ---  Navegador: chrome  ->  precios extraídos correctamente
```

### ✅ Punto 2 del PM — `state.json` no está gitignorado

`.gitignore` contiene solo: `__pycache__/`, `*.pyc`, `.venv/`, `venv/`, `.env`.
Ninguno de esos patrones casa con `state.json`. Comprobado con `fnmatch`
contra cada patrón, no a ojo. La persistencia entre ejecuciones está a salvo.

### ⏸️ Punto 3 del PM — prueba de ntfy: BLOQUEADA

No se puede ejecutar desde aquí: hace falta el topic real del usuario, y no
procede pedirle que lo pegue en el chat. **La tiene que lanzar él.** Comandos
al final de esta entrada.

### ⏸️ Subida a GitHub: NO ejecutada, a propósito

Crear el repo y hacer push es una acción hacia fuera e irreversible en la
práctica. Queda pendiente de que el usuario dé el visto bueno explícito, y en
cualquier caso después de validar el push de ntfy.

### Estado de verificación actualizado

**Verificado con pruebas reales:**
- Extracción de precios (10.58 / 21.06 / 52.82 €, coincide con lo que se ve
  en la web).
- Detección de bajada (estado falseado → las tres marcadas como BAJA).
- El locale no afecta al formato.
- La cookie `exchange` sí controla la moneda.
- El modo CI no cae a Chrome/Edge.
- `state.json` no está gitignorado.

**Sin verificar:**
- El push real de ntfy llegando al móvil.
- La ejecución completa en GitHub Actions.
- El commit automático de `state.json` por el bot.

### Bloqueos

- Topic de ntfy del usuario (solo él puede ejecutar la prueba).
- Visto bueno para crear el repo en GitHub.

### Siguiente paso

Que el usuario ejecute, con su topic real:

```
cd "C:\Users\pepo1\Documents\Eneba Checker"
python -c "import json,pathlib; p=pathlib.Path('state.json'); d=json.loads(p.read_text()); d['precios']={k: v+2 for k,v in d['precios'].items()}; p.write_text(json.dumps(d))"
set NTFY_TOPIC=su-topic-aqui
python check_price.py
```

Si llega el push → subir a GitHub, secreto `NTFY_TOPIC`, lanzar
`workflow_dispatch` una vez y comprobar en el log que el paso "Guardar el
estado en el repo" hace el commit.

### Concepto enseñado

Un scraper puede dar resultados distintos según **desde dónde** se ejecute.
Antes de dar por buena una extracción, hay que preguntarse qué decide el
servidor por su cuenta (moneda, idioma, región) y fijarlo explícitamente,
en vez de confiar en que el entorno de desarrollo se parezca al de producción.

---

## Entrada 002 — 2026-08-24 — Se establece este registro

**Estado:** sin cambios en el código. Solo se crea este archivo.

**Qué se hizo:** a partir de ahora cada respuesta de Claude Code se vuelca
aquí en Markdown para que el PM pueda leer el estado y devolver los
siguientes pasos.

**Formato de cada entrada:** número, fecha, estado, qué se hizo, verificado,
NO verificado, bloqueos, siguiente paso propuesto.

**Bloqueos:** los mismos de la entrada 001 (ver abajo).

**Siguiente paso propuesto:** el de la entrada 001 — probar el push de ntfy.

---

## Entrada 001 — 2026-08-24 — Proyecto construido y probado con datos reales

**Estado:** funcional en local. Sin subir a GitHub. Push de ntfy sin probar.

### Punto de partida

En la carpeta solo existía el `README.md` que trajo el usuario desde
Downloads. Los archivos que ese README mencionaba (`check_price.py`,
`requirements.txt`, el workflow) **no existían**. Se construyeron desde cero.

### Archivos creados

| Archivo | Qué hace |
|---|---|
| `check_price.py` | Scraper con Playwright + comparación + aviso ntfy |
| `requirements.txt` | `playwright==1.48.0`, `requests==2.32.3` |
| `.github/workflows/check.yml` | Ejecuta cada 2h (`cron: 0 */2 * * *`) + `workflow_dispatch` |
| `README.md` | Reescrito según lo que realmente funciona |
| `.gitignore` | `__pycache__`, `.venv`, `.env` |
| `state.json` | Ya contiene la primera lectura real |

### Verificado con pruebas reales

1. **El HTML crudo de Eneba viene vacío.** Comprobado con `curl`: 82 KB de
   página, cero precios. Confirma que hace falta un navegador (Playwright).
2. **Formato real del texto de cada ficha**, obtenido abriendo la página, no
   de memoria: `Steam Wallet Gift Card 100 HKD Steam Key HONG KONG` → `From`
   → `€10.58`.
3. **La extracción funciona.** Salida real de la ejecución:
   ```
   100 HKD -> 10.58 EUR (9.45 HKD/EUR)
   200 HKD -> 21.06 EUR (9.50 HKD/EUR)
   500 HKD -> 52.82 EUR (9.47 HKD/EUR)
   ```
4. **La detección de bajada funciona.** Se falseó `state.json` subiendo los
   precios 1,50 €; el script marcó las tres como `BAJA desde ...` y entró en
   la rama de notificación.

### NO verificado

- **El push real de ntfy.** No se probó porque no hay topic configurado. Es
  la única pieza del sistema sin confirmar.
- **La ejecución en GitHub Actions.** El workflow está escrito pero nunca ha
  corrido; el repo no existe todavía.

### Hallazgos técnicos durante la construcción

**1. El Chromium de Playwright no arranca en el PC del usuario.**
Falla con `spawn UNKNOWN` / "la configuración en paralelo no es correcta":
falta el runtime de Visual C++. Solución aplicada: el script intenta el
Chromium empaquetado y, si falla, cae automáticamente a Chrome o Edge del
sistema. En GitHub Actions (Ubuntu) usará el empaquetado sin problema.
Variable `PLAYWRIGHT_CHANNEL` para forzar uno concreto.
No se pidió al usuario instalar nada en el sistema.

**2. El "ratio HKD/€" no aporta una alerta independiente.**
Para una misma denominación `ratio = HKD ÷ precio`, y los HKD son fijos: si
el precio baja, el ratio sube, siempre. Vigilar ambos sería vigilar lo
mismo. Decisión: la alerta salta por bajada de precio; el ratio se usa para
comparar denominaciones entre sí (ahora la de 200 HKD es la que mejor sale,
9,50 HKD/€) y para un objetivo opcional (`RATIO_OBJETIVO`).

### Bloqueos

- Falta que el usuario elija un topic de ntfy y se suscriba en la app. Sin
  eso no se puede cerrar la validación del sistema.

### Siguiente paso propuesto

Forzar una bajada falsa y ejecutar con el topic real para confirmar que el
push llega al móvil:

```
cd "C:\Users\pepo1\Documents\Eneba Checker"
python -c "import json,pathlib; p=pathlib.Path('state.json'); d=json.loads(p.read_text()); d['precios']={k: v+2 for k,v in d['precios'].items()}; p.write_text(json.dumps(d))"
set NTFY_TOPIC=tu-topic-aqui
python check_price.py
```

Si llega el push → subir a GitHub y configurar el secreto `NTFY_TOPIC`.

### Concepto enseñado en esta sesión

Antes de escribir un scraper se mira si los datos están en el HTML crudo
(`curl` + `grep`). Eso decide si hace falta un navegador entero o basta una
petición simple, y cambia por completo el coste y la fragilidad del proyecto.
