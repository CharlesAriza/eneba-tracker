"""
Vigila el precio en euros de las tarjetas Steam Wallet de Hong Kong en Eneba
y avisa por push (ntfy.sh) cuando baja respecto a la ultima vez.

Como funciona, en corto:
  1. Abre la pagina con un navegador de verdad (Playwright), porque Eneba
     pinta los precios con JavaScript: el HTML crudo viene vacio.
  2. Lee el texto visible y saca "X HKD -> N,NN EUR" con una expresion regular.
  3. Compara con state.json (lo que vio la vez anterior).
  4. Si algo bajo, manda una notificacion a ntfy.sh y guarda el nuevo estado.
"""

import json
import os
import re
import sys
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

# --- Configuracion -------------------------------------------------------

# Denominaciones que nos interesan (en HKD).
DENOMINACIONES = [100, 200, 500]

URL = os.environ.get(
    "ENEBA_URL",
    "https://www.eneba.com/store/all?text=steam%20wallet%20hong%20kong&page=1",
)

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

# Opcional: avisa tambien si el ratio (HKD por euro) llega a este valor.
# Ej.: RATIO_OBJETIVO=9.8  -> avisa cuando 100 HKD cuesten <= 10,20 EUR.
RATIO_OBJETIVO = float(os.environ.get("RATIO_OBJETIVO", "0") or 0)

# Bajadas menores a esto se ignoran (ruido de redondeo).
EPSILON = 0.005

STATE_FILE = Path(__file__).with_name("state.json")

# Texto real de la ficha en Eneba, comprobado el 2026-08-24:
#   "Steam Wallet Gift Card 100 HKD Steam Key HONG KONG"
#   "HONG KONG"
#   "From"
#   "10.58"  (precedido del simbolo del euro)
# El .{0,80}? permite que entre el titulo y el precio haya saltos de linea y
# palabras sueltas, sin tener que acertar el formato exacto.
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


def leer_estado():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("Aviso: state.json corrupto, empiezo de cero.")
    return {}


def guardar_estado(estado):
    STATE_FILE.write_text(
        json.dumps(estado, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def notificar(titulo, cuerpo, prioridad="default", tags="moneybag"):
    """Manda un push a ntfy.sh. El titulo viaja en una cabecera HTTP, asi que
    solo puede llevar ASCII; el cuerpo si admite acentos."""
    if not NTFY_TOPIC:
        print("NTFY_TOPIC no configurado: no envio push.")
        return
    try:
        r = requests.post(
            NTFY_SERVER + "/" + NTFY_TOPIC,
            data=cuerpo.encode("utf-8"),
            headers={
                "Title": titulo.encode("ascii", "ignore").decode("ascii"),
                "Priority": prioridad,
                "Tags": tags,
                "Click": URL,
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


def obtener_ofertas():
    """Devuelve {'100': 10.58, '200': 21.06, ...} con el precio 'From' en EUR."""
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
        contexto.add_cookies([
            {"name": "exchange", "value": "EUR", "domain": ".eneba.com", "path": "/"},
            {"name": "lng", "value": "en", "domain": ".eneba.com", "path": "/"},
            {"name": "region", "value": "spain", "domain": ".eneba.com", "path": "/"},
        ])

        pagina = contexto.new_page()
        pagina.goto(URL, wait_until="domcontentloaded", timeout=90_000)

        # Esperamos a que aparezca el primer producto pintado por JS.
        try:
            pagina.wait_for_selector("text=Steam Wallet Gift Card", timeout=60_000)
        except Exception:
            print("Aviso: no aparecio ningun producto tras 60s.")

        pagina.wait_for_timeout(3000)  # margen para que carguen los precios
        texto = pagina.inner_text("body")
        navegador.close()

    # Diagnostico util: si la pagina cargo pero en otra moneda, decirlo claro
    # en vez de soltar un generico "no se encontro nada".
    if "€" not in texto and re.search(r"[$£]\s?\d", texto):
        print("AVISO: la pagina cargo en otra moneda (no hay simbolo de euro). "
              "La cookie 'exchange' no se aplico.")

    ofertas = {}
    for hkd, eur in PATRON_TARJETA.findall(texto):
        if int(hkd) in DENOMINACIONES:
            precio = a_float(eur)
            clave = str(int(hkd))
            # Nos quedamos con el mas barato si el producto sale repetido.
            if clave not in ofertas or precio < ofertas[clave]:
                ofertas[clave] = precio
    return ofertas


# --- Programa principal --------------------------------------------------

def main():
    print("Consultando: " + URL)
    ofertas = obtener_ofertas()

    if not ofertas:
        print("No se ha podido extraer ninguna oferta. "
              "Probablemente Eneba cambio el HTML: revisa PATRON_TARJETA.")
        estado = leer_estado()
        # Solo avisamos del fallo la primera vez, para no dar la lata cada 2h.
        if not estado.get("fallo_previo"):
            notificar("Eneba tracker roto",
                      "No se pudo leer ningun precio. Revisa el patron de "
                      "extraccion en check_price.py.",
                      prioridad="high", tags="warning")
        estado["fallo_previo"] = True
        guardar_estado(estado)
        return 1

    estado = leer_estado()
    anteriores = estado.get("precios", {})
    lineas = []
    hay_bajada = False

    for hkd in DENOMINACIONES:
        clave = str(hkd)
        if clave not in ofertas:
            print("%d HKD: no encontrado en la pagina." % hkd)
            continue

        precio = ofertas[clave]
        ratio = hkd / precio  # HKD que compras por cada euro; mas alto = mejor
        antes = anteriores.get(clave)

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
        lineas.append("%d HKD: %.2f EUR (%.2f HKD/€) [%s]" % (hkd, precio, ratio, marca))

    # Cual sale mas a cuenta ahora mismo.
    mejor_clave, mejor_precio = max(ofertas.items(), key=lambda kv: int(kv[0]) / kv[1])
    mejor_ratio = int(mejor_clave) / mejor_precio
    lineas.append("Mejor ratio: %s HKD (%.2f HKD/€)" % (mejor_clave, mejor_ratio))

    primera_vez = not anteriores
    if primera_vez:
        print("Primera ejecucion: guardo el estado, sin comparar.")
    elif hay_bajada:
        notificar("Eneba: baja el Steam Wallet HKD", "\n".join(lineas),
                  prioridad="high", tags="chart_with_downwards_trend")
    else:
        print("Sin bajadas. No envio push.")

    estado["precios"] = ofertas
    estado["fallo_previo"] = False
    guardar_estado(estado)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
