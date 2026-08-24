# Eneba Steam Wallet (HKD) Price Tracker

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
5. Manda dos tipos de push:
   - **Alerta**: cuando baja el precio de 100, 200 o 500 HKD.
   - **Resumen diario**: una vez cada ~24h, con mínimos y máximos de la
     ventana y la tarjeta de mejor ratio **de las 34**, no solo de las tres
     vigiladas. Se manda aunque no haya habido ninguna bajada.
6. Descarta del histórico las muestras de más de 24h para que el archivo no
   crezca sin límite.

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
