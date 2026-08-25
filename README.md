# Eneba Steam Wallet (HKD) Price Tracker

**📊 Panel en vivo: https://charlesariza.github.io/eneba-tracker/**

Vigila el precio en euros de las tarjetas Steam Wallet de Hong Kong de
100, 200 y 500 HKD en Eneba, y te avisa por push (ntfy.sh) cuando el
precio baja respecto a la última comprobación.

## Cómo funciona

1. `check_price.py` abre la página de resultados de Eneba con un navegador
   real (Playwright). Hace falta un navegador porque Eneba pinta los precios
   con JavaScript: el HTML crudo llega vacío (comprobado).
2. **Fija las cookies `exchange=EUR`, `lng=en` y `region=spain`** antes de
   cargar. Eneba decide moneda e idioma por geolocalización, así que sin esto
   un runner de GitHub (IP de EE.UU.) vería los precios en dólares y la
   extracción fallaría. Comprobado: con `exchange=USD`, la tarjeta de 100 HKD
   pasa de `€10.58` a `$12.35`.
3. **Recorre todas las páginas de resultados** (hoy son 2, con 34
   denominaciones) y extrae el precio "From" de cada una con una expresión
   regular (`PATRON_TARJETA`).
4. Compara con `state.json`, que guarda lo que se vio la vez anterior, y
   acumula cada lectura en `historial.json`.
5. Manda tres tipos de push, **todos con botón "Comprar en Eneba"** que abre
   la ficha exacta del producto, y **todos sujetos al silencio nocturno**:
   - **Alerta**: cuando baja el precio de 100, 200 o 500 HKD **por encima del
     umbral** (ver abajo). Si el precio iguala el mínimo de los últimos 30
     días, añade una línea "📉 Precio más bajo visto en N días".
   - **Resumen diario**: una vez cada ~24h, con mínimos y máximos de la
     ventana y la tarjeta de mejor ratio **de las 34**, no solo de las tres
     vigiladas. Se manda aunque no haya habido ninguna bajada.
   - **Resumen semanal**: lo mismo agregando 7 días.
6. Descarta del histórico las muestras de más de **30 días**.

## Umbral de alerta

Para no avisar por dos céntimos, la bajada tiene que superar el mayor de:

- un **porcentaje** del precio anterior (`UMBRAL_BAJADA_PCT`, por defecto
  **1,5 %**), y
- un **suelo en euros** (`UMBRAL_BAJADA_EUR`, por defecto **0,10 €**).

Por qué las dos condiciones: las denominaciones van de 0,60 € a 124 €. Un
umbral fijo de 0,20 € sería el 2 % en la tarjeta de 100 HKD (relevante) pero
el 0,4 % en la de 500 (ruido) — el porcentaje escala solo. Y el suelo en euros
evita avisar por redondeos en las tarjetas baratas, donde un 1,5 % son dos
céntimos. El 1,5 % sale de lo observado el 24-08-2026 entre ejecuciones
consecutivas: los movimientos normales rondaban el 0,8 %.

## Silencio nocturno

Entre las **00:00 y las 08:00 hora de España** no se envía ningún push. El
workflow **sigue corriendo con normalidad** en esa franja: lee precios y
actualiza `state.json` e `historial.json`. Lo único que se aparta es el envío.

Si durante la noche se hubiera disparado un aviso (bajada por encima del
umbral, mínimo histórico, o un resumen), **no se pierde**: se guarda en la
cola `pendientes` de `state.json` y se manda en la primera ejecución tras el
fin del silencio, en **un solo push agrupado** con la hora a la que ocurrió
cada uno. Se agrupan a propósito: ocho ejecuciones nocturnas podrían dejar
varios avisos, y despertarte con una ráfaga de notificaciones a las 8 sería
peor que el problema que resuelve el silencio.

La hora es la de España, no la del runner. El runner corre en UTC y España
cambia de huso dos veces al año, así que restar un número fijo de horas
fallaría medio año. Se convierte con `zoneinfo` (de ahí `tzdata` en
`requirements.txt`: Windows no trae la base de datos IANA).

**Para cambiar la franja**, crea las variables en el repo — Settings →
Secrets and variables → Actions → pestaña **Variables**:

| Variable | Ejemplo | Qué hace |
|---|---|---|
| `SILENCIO_INICIO` | `23:30` | Hora local a la que empieza el silencio |
| `SILENCIO_FIN` | `07:00` | Hora local a la que termina |
| `ZONA_HORARIA` | `Europe/Madrid` | Zona IANA de referencia |

La franja **puede cruzar la medianoche** (`23:00`–`08:00` funciona). El inicio
es inclusivo y el fin exclusivo: con `08:00`, a las 08:00 en punto ya se
envía. Para **desactivar** el silencio, pon el mismo valor en las dos
(`SILENCIO_INICIO=00:00` y `SILENCIO_FIN=00:00`).

En local, sin crear nada:

```bash
SILENCIO_INICIO=00:00 SILENCIO_FIN=00:00 python check_price.py
```

## Resúmenes

- **Diario**: cada ~24 h, con mínimos y máximos de la ventana.
- **Semanal**: cada ~7 días, lo mismo agregando la semana.

Cuando toca el semanal **se omite el diario de esa ejecución**: contiene lo
mismo con más recorrido, y mandar los dos seguidos sería repetirse. Los dos
declaran la ventana **real** que cubren (`Ventana: 13.0 h, 15 muestras`), no
"24 h" o "7 días" a secas: al principio el histórico todavía no llega.

## Vigilar más de un producto

Los productos se declaran en `productos.json`. Para añadir uno **no hay que
tocar el código**: se copia el bloque y se ajustan `id`, `nombre`, `url`,
`denominaciones_vigiladas` y los dos patrones. Cada producto guarda su propio
estado, su propio histórico y su propio gráfico.

## Panel web

`index.html` es una página estática sin frameworks que lee `historial.json`,
`state.json` y `productos.json` del propio repositorio y dibuja la evolución
de precios y ratios, más el catálogo completo ordenado por ratio.

Se puede **instalar en el móvil**: "Añadir a pantalla de inicio" desde el
navegador. Tiene icono propio y se abre en modo standalone, sin barra de
direcciones. Si ya tenías el atajo creado antes de esto, **bórralo y vuelve a
añadirlo**: el icono de un atajo ya creado no se refresca solo.

El icono lo genera `iconos.py` (se ejecuta a mano, no en el workflow). No
lleva service worker a propósito: para añadir a pantalla de inicio no hace
falta, y una capa de caché podría servir precios viejos, que es justo lo
contrario de lo que busca el panel.

Está publicada en GitHub Pages (rama `main`, carpeta raíz):
**https://charlesariza.github.io/eneba-tracker/** — se actualiza sola cada vez
que el workflow commitea un nuevo `historial.json`.

Para verla en local **hace falta servirla por HTTP** (abrir el archivo
directamente no funciona: el navegador bloquea el `fetch` en `file://`):

```bash
python -m http.server 8000
```

Y abrir http://127.0.0.1:8000

El `locale` del navegador (`en-GB` vs `es-ES`) **no** influye: comprobado que
ambos devuelven títulos en inglés y precios con punto decimal. Lo que manda es
la cookie `exchange`.

Sobre el **ratio HKD/€**: se calcula como `HKD ÷ precio en euros` (cuántos
HKD compras por euro; más alto = mejor). Para una misma denominación el
ratio y el precio son la misma señal — si el precio baja, el ratio sube —
así que la alerta se dispara por bajada de precio. El ratio sirve para
comparar denominaciones entre sí (el script te dice cuál sale más a cuenta)
y para el objetivo opcional de abajo.

## 1. Crear tu "topic" de ntfy

No hace falta cuenta:

1. Instala la app **ntfy** en tu móvil (Android/iOS) o usa https://ntfy.sh
2. Elige un nombre de topic único y difícil de adivinar, por ejemplo
   `eneba-alertas-a8f3k2`. Cualquiera que sepa el nombre puede suscribirse,
   así que evita algo obvio como "eneba".
3. Suscríbete a ese topic en la app.

## 2. Probar en local antes de subirlo

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

En Windows (PowerShell):

```powershell
$env:NTFY_TOPIC="eneba-alertas-a8f3k2"; python check_price.py
```

En Linux/macOS:

```bash
export NTFY_TOPIC="eneba-alertas-a8f3k2" && python check_price.py
```

La primera ejecución solo guarda el estado (no hay nada previo con qué
comparar). A partir de la segunda, si algo bajó, llega el push.

> **Nota para este PC:** el Chromium que descarga Playwright no arranca aquí
> porque falta el runtime de Visual C++ (`spawn UNKNOWN` / "configuración en
> paralelo no es correcta"). El script lo detecta y usa automáticamente el
> Chrome o Edge que ya tienes instalado. En GitHub Actions no pasa esto.
> Si quieres forzar un navegador concreto: `PLAYWRIGHT_CHANNEL=chrome`.
>
> En GitHub Actions (donde existe la variable `CI`) el fallback se desactiva
> a propósito: allí solo se usa el Chromium empaquetado y, si fallara, el
> workflow se rompe en rojo en vez de disimularlo con otro navegador.

## 3. Subir el proyecto a GitHub

```bash
git init
git add .
git commit -m "Initial commit"
gh repo create eneba-tracker --private --source=. --push
```

## 4. Configurar el secreto NTFY_TOPIC

Repo → Settings → Secrets and variables → Actions → New repository secret

- Name: `NTFY_TOPIC`
- Value: tu topic (ej. `eneba-alertas-a8f3k2`)

Opcional, en la pestaña **Variables** del mismo sitio:

- Name: `RATIO_OBJETIVO`
- Value: por ejemplo `9.60` — te avisa cuando cualquiera de las tres
  denominaciones alcance ese ratio HKD/€, aunque no haya bajado respecto
  a la última comprobación.

## 5. Probarlo en Actions

Pestaña **Actions** → "Check Eneba price" → **Run workflow**.

Si el log dice "No se ha podido extraer ninguna oferta", Eneba habrá
cambiado el HTML y hay que ajustar `PATRON_TARJETA` en `check_price.py`.
En ese caso el script también te manda un push de aviso (solo una vez,
no cada 2 horas).

## 6. Frecuencia

**Ahora mismo corre cada hora (`cron: "0 * * * *"`), y es TEMPORAL**: se subió
así para validar el resumen diario acumulando muestras más rápido. Cuando esa
fase termine, volver a `0 */2 * * *`. No bajes de 30-60 minutos para no
saturar Eneba. Dos avisos de GitHub:

- Los cron de Actions no son puntuales; pueden retrasarse.
- Si el repo pasa 60 días sin actividad, GitHub desactiva los workflows
  programados y te manda un email para reactivarlos.

## Variables de entorno

| Variable | Obligatoria | Para qué |
|---|---|---|
| `NTFY_TOPIC` | Sí (para recibir push) | Topic de ntfy.sh |
| `NTFY_SERVER` | No | Servidor ntfy alternativo (por defecto `https://ntfy.sh`) |
| `RATIO_OBJETIVO` | No | Avisa al alcanzar ese ratio HKD/€ |
| `UMBRAL_BAJADA_PCT` | No | % mínimo de bajada para alertar (def. 1.5) |
| `UMBRAL_BAJADA_EUR` | No | Suelo en € para alertar (def. 0.10) |
| `RETENCION_DIAS` | No | Días de histórico que se conservan (def. 30) |
| `SILENCIO_INICIO` | No | Inicio del silencio, hora local (def. `00:00`) |
| `SILENCIO_FIN` | No | Fin del silencio, hora local (def. `08:00`) |
| `ZONA_HORARIA` | No | Zona IANA (def. `Europe/Madrid`) |
| `DIAS_ENTRE_RESUMENES_SEMANALES` | No | Días entre semanales (def. 6.9) |
| `ENEBA_URL` | No | Cambiar la página que se consulta (sin `page=`) |
| `ENEBA_MAX_PAGINAS` | No | Tope de páginas a recorrer (por defecto 5) |
| `PLAYWRIGHT_CHANNEL` | No | Forzar navegador: `chrome`, `msedge` |
| `CI` | La pone GitHub | Si existe, desactiva el fallback a Chrome/Edge |

## Notas

- El precio que se lee es el **"From"** de la ficha (la oferta más barata
  del listado), no incluye comisiones de pago ni Eneba Prime.
- `state.json` e `historial.json` los commitea el workflow automáticamente
  para recordar el estado entre ejecuciones.
- El `RATIO_OBJETIVO` hay que calibrarlo con los valores que ve el runner
  de GitHub (~9,0 HKD/€), no con los que ves tú desde España (~9,45). Ver
  el aviso de precio orientativo más abajo.
- **Los precios dependen de la IP.** El runner de GitHub está en EE.UU. y
  ve precios ~5 % por encima de los de España. No es corregible con
  cookies: probado con `region=spain`, `united-states` y `germany`, los
  tres dan el mismo precio. Por eso las notificaciones llevan el aviso
  "precio orientativo, verificar en Eneba antes de comprar". La detección
  de bajadas sigue siendo válida porque compara runner contra runner.

## Nota sobre el topic de ntfy

El topic en uso **no está escrito en ningún archivo de este repositorio**:
vive solo en el secreto `NTFY_TOPIC` de Actions, que GitHub no expone ni
siquiera a su propietario por API.

Los topics que aparecen en el historial de git de este repo fueron rotados el
2026-08-24, antes de hacerlo público, y ya no reciben nada. Se rotaron en vez
de borrarlos porque borrar un dato de un archivo no lo quita de los commits
donde se añadió.
