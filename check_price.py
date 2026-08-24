"""
Vigila el precio en euros de las tarjetas Steam Wallet de Hong Kong en Eneba.

Manda dos tipos de aviso por push (ntfy.sh):
  - ALERTA: cuando baja el precio de 100, 200 o 500 HKD respecto a la
    comprobacion anterior.
  - RESUMEN: una vez al dia, con minimos y maximos de las ultimas 24h y la
    tarjeta con mejor ratio de todo el catalogo.

Como funciona, en corto:
  1. Abre la pagina con un navegador de verdad (Playwright), porque Eneba
     pinta los precios con JavaScript: el HTML crudo viene vacio.
  2. Recorre todas las paginas de resultados y saca TODAS las denominaciones.
  3. Compara con state.json y acumula el historico en historial.json.
  4. Manda los avisos que toquen y limpia el historico de mas de 24h.
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

# --- Configuracion -------------------------------------------------------

# Denominaciones con alerta puntual de bajada. El resumen diario y la "mejor
# tarjeta" miran TODAS las que publique Eneba, no solo estas.
DENOMINACIONES = [100, 200, 500]

URL_BASE = os.environ.get(
    "ENEBA_URL",
    "https://www.eneba.com/store/all?text=steam%20wallet%20hong%20kong",
)

# Tope de paginas a recorrer. Hoy hay 2 (34 resultados); el margen evita
# quedarse corto si Eneba anade denominaciones.
MAX_PAGINAS = int(os.environ.get("ENEBA_MAX_PAGINAS", "5"))

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

# Opcional: avisa tambien si el ratio (HKD por euro) llega a este valor.
# OJO: calibralo con los valores que ve el runner de GitHub, no con los que
# ves tu desde Espana (ver el aviso de "precio orientativo" mas abajo).
RATIO_OBJETIVO = float(os.environ.get("RATIO_OBJETIVO", "0") or 0)

# Bajadas menores a esto se ignoran (ruido de redondeo).
EPSILON = 0.005

VENTANA_HORAS = 24  # cuanto historico se conserva
# Se manda el resumen a partir de 23.5h en vez de 24h clavadas: con el cron
# horario, exigir 24h haria que la hora del resumen se fuese corriendo un poco
# cada dia hasta dar la vuelta al reloj.
HORAS_ENTRE_RESUMENES = 23.5

AVISO_ORIENTATIVO = ("⚠️ Precio orientativo (servidor en EE.UU.), "
                     "verificar en Eneba antes de comprar.")

STATE_FILE = Path(__file__).with_name("state.json")
HISTORIAL_FILE = Path(__file__).with_name("historial.json")

# Texto real de la ficha en Eneba, comprobado el 2026-08-24:
#   "Steam Wallet Gift Card 100 HKD Steam Key HONG KONG"
#   "HONG KONG"
#   "From"
#   "10.58"  (precedido del simbolo del euro)
# El .{0,80}? permite que entre el titulo y el precio haya saltos de linea y
# palabras sueltas, sin tener que acertar el formato exacto. Al ser perezoso,
# se queda con el primer euro que aparece: el precio, no el "Cashback: €1.27"
# que va detras en algunas fichas.
PATRON_TARJETA = re.compile(
    r"Steam Wallet Gift Card\s+(\d+)\s+HKD.{0,80}?€\s*([\d.,]+)",
    re.DOTALL,
)


# --- Utilidades ----------------------------------------------------------

def a_float(texto_precio):
    """Convierte '10.58' o '1.234,56' a float. Eneba usa punto, pero
    soportamos los dos formatos por si cambia."""
    t = texto_precio.strip()
    if "," in t and "." in t:
        # El separador decimal es el que aparece mas a la derecha.
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    return float(t)


def leer_json(ruta, por_defecto):
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("Aviso: %s corrupto, empiezo de cero." % ruta.name)
    return por_defecto


def guardar_json(ruta, datos):
    ruta.write_text(
        json.dumps(datos, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def hora_utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def notificar(titulo, cuerpo, prioridad="default", tags="moneybag"):
    """Manda un push a ntfy.sh. El titulo viaja en una cabecera HTTP, asi que
    solo puede llevar ASCII; el cuerpo si admite acentos y emojis."""
    if not NTFY_TOPIC:
        print("NTFY_TOPIC no configurado: no envio push.")
        print("--- cuerpo que se habria enviado ---")
        print(cuerpo)
        print("------------------------------------")
        return
    try:
        r = requests.post(
            NTFY_SERVER + "/" + NTFY_TOPIC,
            data=cuerpo.encode("utf-8"),
            headers={
                "Title": titulo.encode("ascii", "ignore").decode("ascii"),
                "Priority": prioridad,
                "Tags": tags,
                "Click": URL_BASE,
            },
            timeout=20,
        )
        r.raise_for_status()
        print("Push enviado a " + NTFY_SERVER + "/" + NTFY_TOPIC)
    except requests.RequestException as e:
        print("Error enviando el push: " + str(e))


# --- Scraping ------------------------------------------------------------

def abrir_navegador(p):
    """Intenta el Chromium que trae Playwright y, si falla, cae al Chrome o
    Edge ya instalados en el sistema.

    Por que: en GitHub Actions el Chromium empaquetado funciona siempre, pero
    en un Windows sin el runtime de Visual C++ no arranca ('spawn UNKNOWN').
    """
    canal_forzado = os.environ.get("PLAYWRIGHT_CHANNEL", "").strip()
    if canal_forzado:
        intentos = [canal_forzado]
    elif os.environ.get("CI"):
        # En GitHub Actions el Chromium empaquetado SIEMPRE esta disponible
        # (lo instala el propio workflow). Alli no hay Chrome ni Edge, asi que
        # el fallback no puede funcionar: mejor fallar ruidosamente que
        # disimular un problema de instalacion.
        intentos = [None]
    else:
        intentos = [None, "chrome", "msedge"]

    ultimo_error = None
    for i, canal in enumerate(intentos):
        queda_otro = i < len(intentos) - 1
        try:
            if canal:
                nav = p.chromium.launch(headless=True, channel=canal)
                print("Navegador: " + canal)
            else:
                nav = p.chromium.launch(headless=True)
                print("Navegador: chromium de Playwright")
            return nav
        except Exception as e:
            ultimo_error = e
            cola = "pruebo el siguiente." if queda_otro else "y no queda alternativa."
            print("No se pudo abrir %s, %s" % (canal or "chromium", cola))
    raise ultimo_error


def url_pagina(n):
    """Anade (o sustituye) el parametro page= de la URL base."""
    if re.search(r"[?&]page=\d+", URL_BASE):
        return re.sub(r"([?&]page=)\d+", r"\g<1>%d" % n, URL_BASE)
    separador = "&" if "?" in URL_BASE else "?"
    return "%s%spage=%d" % (URL_BASE, separador, n)


def obtener_ofertas():
    """Devuelve {100: 10.58, 200: 21.06, ...} con el precio 'From' en EUR de
    TODAS las denominaciones publicadas, recorriendo las paginas de resultados.
    """
    ofertas = {}

    with sync_playwright() as p:
        navegador = abrir_navegador(p)
        contexto = navegador.new_context(
            locale="en-GB",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        )

        # Eneba decide moneda, idioma y region con cookies, que fija por
        # geolocalizacion en la primera visita. Las fijamos nosotros para que
        # el resultado no dependa de desde donde se ejecute.
        # Comprobado el 2026-08-24: con exchange=USD la misma tarjeta de
        # 100 HKD sale como "$12.35" en vez de "€10.58". Sin esto, cada
        # ejecucion desde un runner de GitHub (IP de EE.UU.) daria precios en
        # dolares y el patron, que exige el simbolo del euro, no encontraria
        # nada: falsa alarma de "tracker roto" cada 2 horas.
        # OJO: la cookie 'region' NO cambia el precio (probado con spain,
        # united-states y germany: identico). El precio lo decide la IP.
        contexto.add_cookies([
            {"name": "exchange", "value": "EUR", "domain": ".eneba.com", "path": "/"},
            {"name": "lng", "value": "en", "domain": ".eneba.com", "path": "/"},
            {"name": "region", "value": "spain", "domain": ".eneba.com", "path": "/"},
        ])

        pagina = contexto.new_page()
        texto_total = ""

        for n in range(1, MAX_PAGINAS + 1):
            url = url_pagina(n)
            pagina.goto(url, wait_until="domcontentloaded", timeout=90_000)
            try:
                pagina.wait_for_selector("text=Steam Wallet Gift Card", timeout=45_000)
            except Exception:
                print("Pagina %d: no aparecio ningun producto, dejo de paginar." % n)
                break

            pagina.wait_for_timeout(3000)  # margen para que carguen los precios
            texto = pagina.inner_text("body")
            texto_total += texto

            encontradas = {}
            for hkd, eur in PATRON_TARJETA.findall(texto):
                precio = a_float(eur)
                clave = int(hkd)
                # Nos quedamos con el mas barato si el producto sale repetido.
                if clave not in encontradas or precio < encontradas[clave]:
                    encontradas[clave] = precio

            nuevas = [k for k in encontradas if k not in ofertas]
            print("Pagina %d: %d denominaciones (%d nuevas)"
                  % (n, len(encontradas), len(nuevas)))

            if not encontradas:
                break
            for k, v in encontradas.items():
                if k not in ofertas or v < ofertas[k]:
                    ofertas[k] = v
            if not nuevas:
                # Una pagina que no aporta nada nuevo suele ser la ultima
                # repetida; paramos para no dar vueltas de mas.
                break

        navegador.close()

    # Diagnostico util: si la pagina cargo pero en otra moneda, decirlo claro
    # en vez de soltar un generico "no se encontro nada".
    if "€" not in texto_total and re.search(r"[$£]\s?\d", texto_total):
        print("AVISO: la pagina cargo en otra moneda (no hay simbolo de euro). "
              "La cookie 'exchange' no se aplico.")

    return ofertas


# --- Historico -----------------------------------------------------------

def limpiar_historial(muestras, ahora):
    """Tira las muestras de mas de VENTANA_HORAS para que el archivo no crezca
    sin limite."""
    limite = ahora - VENTANA_HORAS * 3600
    return [m for m in muestras if m.get("t", 0) >= limite]


def rango_24h(muestras, hkd):
    """Devuelve (minimo, maximo) de una denominacion en las muestras dadas."""
    valores = [m["precios"][str(hkd)] for m in muestras if str(hkd) in m["precios"]]
    if not valores:
        return None, None
    return min(valores), max(valores)


def construir_resumen(muestras, ofertas, ahora):
    """Arma el cuerpo del push de resumen diario."""
    lineas = []

    if muestras:
        antigua = muestras[0]
        horas = (ahora - antigua["t"]) / 3600.0
    else:
        antigua, horas = None, 0.0

    # Honestidad: el primer dia el historico no cubre 24h enteras, y el
    # mensaje debe decir lo que cubre de verdad, no "24h" a secas.
    lineas.append("Ventana: %.1f h, %d muestras" % (horas, len(muestras)))
    lineas.append("")

    for hkd in DENOMINACIONES:
        actual = ofertas.get(hkd)
        if actual is None:
            lineas.append("%d HKD: no encontrado ahora mismo" % hkd)
            continue

        minimo, maximo = rango_24h(muestras, hkd)
        antes = antigua["precios"].get(str(hkd)) if antigua else None

        if antes is None:
            cambio = "sin referencia previa"
        elif actual < antes - EPSILON:
            cambio = "baja %.2f" % (antes - actual)
        elif actual > antes + EPSILON:
            cambio = "sube %.2f" % (actual - antes)
        else:
            cambio = "igual"

        if minimo is None:
            lineas.append("%d HKD: ahora %.2f € (%s)" % (hkd, actual, cambio))
        else:
            lineas.append("%d HKD: ahora %.2f € | min %.2f | max %.2f | %s"
                          % (hkd, actual, minimo, maximo, cambio))

    # Mejor tarjeta de TODO el catalogo, no solo de las tres vigiladas.
    if ofertas:
        mejor = max(ofertas.items(), key=lambda kv: kv[0] / kv[1])
        lineas.append("")
        lineas.append("Mejor tarjeta ahora mismo: %d HKD — %.2f HKD/€ (%.2f €)"
                      % (mejor[0], mejor[0] / mejor[1], mejor[1]))
        lineas.append("(%d denominaciones comparadas)" % len(ofertas))

    lineas.append("")
    lineas.append(AVISO_ORIENTATIVO)
    return "\n".join(lineas)


# --- Programa principal --------------------------------------------------

def main():
    ahora = time.time()
    print("Consultando: %s (hasta %d paginas)" % (URL_BASE, MAX_PAGINAS))
    ofertas = obtener_ofertas()

    estado = leer_json(STATE_FILE, {})

    if not ofertas:
        print("No se ha podido extraer ninguna oferta. "
              "Probablemente Eneba cambio el HTML: revisa PATRON_TARJETA.")
        # Solo avisamos del fallo la primera vez, para no dar la lata cada hora.
        if not estado.get("fallo_previo"):
            notificar("Eneba tracker roto",
                      "No se pudo leer ningun precio. Revisa el patron de "
                      "extraccion en check_price.py.",
                      prioridad="high", tags="warning")
        estado["fallo_previo"] = True
        guardar_json(STATE_FILE, estado)
        return 1

    print("Total denominaciones encontradas: %d -> %s"
          % (len(ofertas), sorted(ofertas)))

    # --- 1. Alerta puntual de bajada (solo 100/200/500) ------------------
    anteriores = estado.get("precios", {})
    lineas_alerta = []
    hay_bajada = False

    for hkd in DENOMINACIONES:
        if hkd not in ofertas:
            print("%d HKD: no encontrado en la pagina." % hkd)
            continue

        precio = ofertas[hkd]
        ratio = hkd / precio  # HKD que compras por cada euro; mas alto = mejor
        antes = anteriores.get(str(hkd))

        if antes is None:
            marca = "nuevo"
        elif precio < antes - EPSILON:
            marca = "BAJA desde %.2f" % antes
            hay_bajada = True
        elif precio > antes + EPSILON:
            marca = "sube desde %.2f" % antes
        else:
            marca = "igual"

        if RATIO_OBJETIVO and ratio >= RATIO_OBJETIVO:
            marca += " | objetivo %.2f alcanzado" % RATIO_OBJETIVO
            hay_bajada = True

        print("%d HKD -> %.2f EUR (%.2f HKD/EUR) [%s]" % (hkd, precio, ratio, marca))
        lineas_alerta.append("%d HKD: %.2f EUR (%.2f HKD/€) [%s]"
                             % (hkd, precio, ratio, marca))

    mejor_clave, mejor_precio = max(ofertas.items(), key=lambda kv: kv[0] / kv[1])
    lineas_alerta.append("Mejor ratio: %d HKD (%.2f HKD/€)"
                         % (mejor_clave, mejor_clave / mejor_precio))
    lineas_alerta.append(AVISO_ORIENTATIVO)

    primera_vez = not anteriores
    if primera_vez:
        print("Primera ejecucion: guardo el estado, sin comparar.")
    elif hay_bajada:
        notificar("Eneba: baja el Steam Wallet HKD", "\n".join(lineas_alerta),
                  prioridad="high", tags="chart_with_downwards_trend")
    else:
        print("Sin bajadas. No envio alerta.")

    # --- 2. Historico ----------------------------------------------------
    historial = leer_json(HISTORIAL_FILE, {"muestras": []})
    muestras = limpiar_historial(historial.get("muestras", []), ahora)
    muestras.append({
        "t": int(ahora),
        "iso": hora_utc(ahora),
        "precios": {str(k): v for k, v in sorted(ofertas.items())},
    })
    muestras.sort(key=lambda m: m["t"])

    # --- 3. Resumen diario -----------------------------------------------
    ultimo = estado.get("ultimo_resumen")
    if ultimo is None:
        # Primera vez: no tiene sentido resumir 24h con una sola muestra.
        # Arrancamos el contador y el primer resumen saldra manana.
        print("Sin resumen previo: arranco el contador, el primero sale en ~24h.")
        estado["ultimo_resumen"] = int(ahora)
    elif (ahora - ultimo) >= HORAS_ENTRE_RESUMENES * 3600:
        horas_desde = (ahora - ultimo) / 3600.0
        print("Toca resumen (%.1f h desde el ultimo). Enviando." % horas_desde)
        notificar("Eneba: resumen 24h",
                  construir_resumen(muestras, ofertas, ahora),
                  prioridad="default", tags="bar_chart")
        estado["ultimo_resumen"] = int(ahora)
    else:
        faltan = HORAS_ENTRE_RESUMENES - (ahora - ultimo) / 3600.0
        print("Resumen no toca todavia (faltan %.1f h)." % faltan)

    # --- 4. Guardar ------------------------------------------------------
    estado["precios"] = {str(k): ofertas[k] for k in DENOMINACIONES if k in ofertas}
    estado["todas"] = {str(k): v for k, v in sorted(ofertas.items())}
    estado["fallo_previo"] = False
    guardar_json(STATE_FILE, estado)

    historial["muestras"] = muestras
    guardar_json(HISTORIAL_FILE, historial)
    print("Historial: %d muestras (ventana de %d h)." % (len(muestras), VENTANA_HORAS))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
