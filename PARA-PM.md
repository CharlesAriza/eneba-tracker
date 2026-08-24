# PARA-PM — Eneba Steam Wallet (HKD) Price Tracker

Registro de salidas de Claude Code para el chat de Claude que hace de
**project manager**. Entrada más reciente arriba. Cada entrada dice qué se
hizo, qué está verificado, qué NO está verificado y qué bloquea el avance.

Proyecto: `C:\Users\pepo1\Documents\Eneba Checker`

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
