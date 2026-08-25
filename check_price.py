"""
Vigila precios de tarjetas regalo en Eneba y avisa por push (ntfy.sh).

Los productos a vigilar se declaran en productos.json, no aqui: para anadir
uno nuevo no hace falta tocar este archivo.

Manda tres tipos de aviso:
  - ALERTA: cuando baja el precio de una denominacion vigilada MAS QUE EL
    UMBRAL configurado (para no dar la lata por dos centimos), o cuando toca
    su minimo historico.
  - RESUMEN DIARIO: minimos y maximos de las ultimas 24h y la tarjeta con
    mejor ratio de todo el catalogo del producto.
  - RESUMEN SEMANAL: lo mismo agregando 7 dias. Cuando toca el semanal se
    omite el diario de esa ejecucion: seria repetir lo mismo dos veces.

Todos respetan el SILENCIO NOCTURNO: entre SILENCIO_INICIO y SILENCIO_FIN
(hora de Espana) no se envia nada. La ejecucion sigue haciendose completa y
lo que hubiera que avisar se encola para mandarlo de una vez al terminar la
franja, para no perder una bajada ocurrida de madrugada.

Como funciona, en corto:
  1. Abre la pagina con un navegador de verdad (Playwright), porque Eneba
     pinta los precios con JavaScript: el HTML crudo viene vacio.
  2. Recorre todas las paginas de resultados y saca TODAS las denominaciones,
     con su enlace directo al producto.
  3. Compara con state.json y acumula el historico en historial.json.
  4. Manda los avisos que toquen y poda el historico.
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

AQUI = Path(__file__).parent

# --- Configuracion -------------------------------------------------------

PRODUCTOS_FILE = AQUI / "productos.json"
STATE_FILE = AQUI / "state.json"
HISTORIAL_FILE = AQUI / "historial.json"


def env_num(nombre, defecto, tipo=float):
    """Lee una variable de entorno numerica tratando la cadena vacia como si
    no estuviera.

    Hace falta porque GitHub Actions inyecta las variables inexistentes como
    cadena vacia, no las omite: un `${{ vars.X }}` no definido llega como
    UMBRAL_BAJADA_PCT="" y float("") lanza ValueError. Tambien perdona un
    valor mal escrito en vez de tumbar la ejecucion entera.
    """
    bruto = (os.environ.get(nombre) or "").strip()
    if not bruto:
        return defecto
    try:
        return tipo(bruto)
    except ValueError:
        print("Aviso: %s='%s' no es un numero valido, uso %s."
              % (nombre, bruto, defecto))
        return defecto

# Tope de paginas a recorrer. Hoy hay 2 (34 resultados); el margen evita
# quedarse corto si Eneba anade denominaciones.
MAX_PAGINAS = env_num("ENEBA_MAX_PAGINAS", 5, int)

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "").strip()
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

# Umbral de la alerta puntual. Se exige que la bajada supere el mayor de:
#   - un porcentaje del precio anterior (UMBRAL_BAJADA_PCT), y
#   - un suelo en euros (UMBRAL_BAJADA_EUR).
#
# Por que un porcentaje y no solo euros: las denominaciones van de 0,60 EUR a
# 124 EUR. Un umbral fijo de 0,20 EUR seria el 2% en la tarjeta de 100 HKD
# (relevante) pero el 0,4% en la de 500 (ruido). El porcentaje escala solo.
# Por que ademas un suelo en euros: evita avisar por redondeos en las tarjetas
# baratas, donde un 1,5% son 2 centimos.
# El 1,5% por defecto sale de lo observado entre ejecuciones consecutivas del
# 24-08-2026: los movimientos normales rondaban el 0,8%. Ajustable.
UMBRAL_BAJADA_PCT = env_num("UMBRAL_BAJADA_PCT", 1.5)
UMBRAL_BAJADA_EUR = env_num("UMBRAL_BAJADA_EUR", 0.10)

# Opcional: avisa tambien si el ratio (unidades por euro) llega a este valor.
# OJO: calibralo con los valores que ve el runner de GitHub, no con los que
# ves tu desde Espana (ver el aviso de "precio orientativo").
RATIO_OBJETIVO = env_num("RATIO_OBJETIVO", 0.0)

# Diferencias menores a esto se consideran "igual" (ruido de redondeo).
EPSILON = 0.005

# Muestras minimas para que el "minimo historico" pueda disparar una alerta.
MIN_MUESTRAS_HISTORICO = env_num("MIN_MUESTRAS_HISTORICO", 6, int)

VENTANA_RESUMEN_HORAS = 24  # ventana que resume el push diario
# El historico se guarda 30 dias, no 24h: hace falta para el minimo historico
# (mejora 5), el grafico (mejora 2) y el panel web (mejora 6).
RETENCION_DIAS = env_num("RETENCION_DIAS", 30, int)

# Se manda el resumen a partir de 23.5h en vez de 24h clavadas: con el cron
# horario, exigir 24h haria que la hora del resumen se fuese corriendo un poco
# cada dia hasta dar la vuelta al reloj.
HORAS_ENTRE_RESUMENES = 23.5

# Resumen semanal: misma idea, 7 dias. El margen es mayor (6.9 dias) por lo
# mismo: que la hora no se vaya corriendo semana a semana.
VENTANA_SEMANAL_HORAS = 24 * 7
DIAS_ENTRE_RESUMENES_SEMANALES = env_num("DIAS_ENTRE_RESUMENES_SEMANALES", 6.9)

# --- Silencio nocturno ---------------------------------------------------
# Franja en la que NO se manda ningun push. El workflow sigue corriendo: lee
# precios y guarda estado e historial con normalidad; solo se aparta el envio.
#
# La hora es de Espana, no del runner. El runner corre en UTC y Espana cambia
# de offset dos veces al ano (+1 en invierno, +2 en verano), asi que restar un
# numero fijo de horas fallaria medio ano. Se usa zoneinfo con la base de
# datos IANA (paquete tzdata, en requirements.txt: Windows no la trae).
ZONA_USUARIO = os.environ.get("ZONA_HORARIA", "Europe/Madrid")
SILENCIO_INICIO = os.environ.get("SILENCIO_INICIO", "00:00").strip()
SILENCIO_FIN = os.environ.get("SILENCIO_FIN", "08:00").strip()

# Tope de avisos en cola. Si algo va mal y se acumulan, mejor perder los mas
# viejos que guardar un state.json que crece sin control.
MAX_PENDIENTES = 20

AVISO_ORIENTATIVO = ("⚠️ Precio orientativo (servidor en EE.UU.), "
                     "verificar en Eneba antes de comprar.")


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


def hora_local(epoch):
    """Convierte un epoch a la hora del usuario, respetando el cambio de
    horario. Si no hay base de datos de zonas, cae a UTC avisando: es
    preferible mandar un push a deshora que romper la ejecucion entera."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.fromtimestamp(epoch, ZoneInfo(ZONA_USUARIO))
    except Exception as e:
        print("Aviso: no se pudo usar la zona %s (%s). Uso UTC."
              % (ZONA_USUARIO, e))
        return datetime.fromtimestamp(epoch, timezone.utc)


def _a_minutos(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def en_silencio(epoch):
    """True si a esa hora local no se deben mandar push.

    El inicio es inclusivo y el fin exclusivo: con 00:00-08:00, a las 08:00 en
    punto ya se puede enviar. Se admite que la franja cruce la medianoche
    (por ejemplo 23:00-08:00), de ahi las dos ramas.
    """
    try:
        ini, fin = _a_minutos(SILENCIO_INICIO), _a_minutos(SILENCIO_FIN)
    except ValueError:
        print("Aviso: SILENCIO_INICIO/FIN mal formados ('%s', '%s'). "
              "Desactivo el silencio." % (SILENCIO_INICIO, SILENCIO_FIN))
        return False
    if ini == fin:
        return False  # franja vacia = silencio desactivado
    ahora_local = hora_local(epoch)
    minutos = ahora_local.hour * 60 + ahora_local.minute
    if ini < fin:
        return ini <= minutos < fin
    return minutos >= ini or minutos < fin  # la franja cruza la medianoche


def exportar_salida(clave, valor):
    """Publica un dato para los siguientes pasos del workflow.

    Se usa para que el paso del grafico y el del commit sepan si esta
    ejecucion mando el resumen diario: el PNG solo se commitea entonces.
    Fuera de GitHub Actions no existe GITHUB_OUTPUT y no hace nada.
    """
    destino = os.environ.get("GITHUB_OUTPUT")
    print("Salida para el workflow: %s=%s" % (clave, valor))
    if not destino:
        return
    with open(destino, "a", encoding="utf-8") as f:
        f.write("%s=%s\n" % (clave, valor))


def hora_utc(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def migrar(datos, clave_lista, id_por_defecto):
    """Convierte el formato antiguo (un solo producto, datos en la raiz) al
    nuevo (namespace por producto). Sin esto, activar multi-producto tiraria
    el historico ya acumulado."""
    if "productos" in datos:
        return datos
    if not datos:
        return {"productos": {}}
    print("Migrando %s al formato multi-producto (id '%s')."
          % (clave_lista, id_por_defecto))
    return {"productos": {id_por_defecto: datos}}


def notificar(titulo, cuerpo, prioridad="default", tags="moneybag",
              url_accion=None, etiqueta_accion="Comprar en Eneba"):
    """Manda un push a ntfy.sh.

    Titulo, tags y la cabecera Actions viajan en cabeceras HTTP, que solo
    admiten ASCII; el cuerpo si admite acentos y emojis.
    """
    if not NTFY_TOPIC:
        print("NTFY_TOPIC no configurado: no envio push.")
        print("--- cuerpo que se habria enviado ---")
        print(cuerpo)
        if url_accion:
            print("[boton] %s -> %s" % (etiqueta_accion, url_accion))
        print("------------------------------------")
        return

    cabeceras = {
        "Title": titulo.encode("ascii", "ignore").decode("ascii"),
        "Priority": prioridad,
        "Tags": tags,
    }
    if url_accion:
        cabeceras["Click"] = url_accion
        # Formato de ntfy: "<tipo>, <etiqueta>, <url>". La etiqueta no puede
        # llevar comas ni acentos (cabecera HTTP = ASCII).
        etiqueta = etiqueta_accion.encode("ascii", "ignore").decode("ascii")
        cabeceras["Actions"] = "view, %s, %s, clear=true" % (etiqueta, url_accion)

    try:
        r = requests.post(
            NTFY_SERVER + "/" + NTFY_TOPIC,
            data=cuerpo.encode("utf-8"),
            headers=cabeceras,
            timeout=20,
        )
        r.raise_for_status()
        print("Push enviado a " + NTFY_SERVER + "/" + NTFY_TOPIC)
    except requests.RequestException as e:
        print("Error enviando el push: " + str(e))


# --- Cola de avisos del silencio nocturno --------------------------------

def enviar_o_encolar(estado, ahora, titulo, cuerpo, prioridad="default",
                     tags="moneybag", url_accion=None):
    """Manda el aviso, o lo guarda para despues si estamos en el silencio.

    Encolar en vez de descartar: una bajada de madrugada sigue siendo una
    bajada por la manana, y perderla seria justo lo que el proyecto quiere
    evitar.
    """
    if not en_silencio(ahora):
        notificar(titulo, cuerpo, prioridad, tags, url_accion)
        return False

    cola = estado.setdefault("pendientes", [])
    cola.append({
        "t": int(ahora),
        "local": hora_local(ahora).strftime("%d/%m %H:%M"),
        "titulo": titulo,
        "cuerpo": cuerpo,
        "prioridad": prioridad,
        "tags": tags,
        "url": url_accion,
    })
    if len(cola) > MAX_PENDIENTES:
        del cola[:len(cola) - MAX_PENDIENTES]
    print("  Silencio nocturno (%s hora local): aviso encolado (%d en cola)."
          % (hora_local(ahora).strftime("%H:%M"), len(cola)))
    return True


def vaciar_cola(estado, ahora):
    """Manda lo que quedo pendiente de la noche, en UN solo push.

    Se agrupa a proposito: ocho ejecuciones nocturnas podrian dejar varios
    avisos, y despertar al usuario con una rafaga de notificaciones a las 8
    de la manana seria peor que el problema que resuelve el silencio.
    """
    cola = estado.get("pendientes") or []
    if not cola or en_silencio(ahora):
        return

    if len(cola) == 1:
        aviso = cola[0]
        titulo = aviso["titulo"]
        cuerpo = ("(Ocurrio durante el silencio nocturno, %s)\n\n%s"
                  % (aviso["local"], aviso["cuerpo"]))
    else:
        titulo = "Eneba: %d avisos de la noche" % len(cola)
        partes = ["Se retuvieron durante el silencio nocturno:", ""]
        for aviso in cola:
            partes.append("──── %s ────" % aviso["local"])
            partes.append(aviso["cuerpo"])
            partes.append("")
        cuerpo = "\n".join(partes).rstrip()

    # La prioridad mas alta de la cola manda, y el enlace del aviso mas
    # reciente, que es el que refleja el precio actual.
    prioridad = "high" if any(a.get("prioridad") == "high" for a in cola) else "default"
    url = next((a["url"] for a in reversed(cola) if a.get("url")), None)

    print("  Fin del silencio: envio %d aviso(s) retenido(s)." % len(cola))
    notificar(titulo, cuerpo, prioridad, "night_with_stars", url)
    estado["pendientes"] = []


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


def preparar_contexto(navegador):
    contexto = navegador.new_context(
        locale="en-GB",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
    )
    # Eneba decide moneda, idioma y region con cookies, que fija por
    # geolocalizacion en la primera visita. Las fijamos nosotros para que el
    # resultado no dependa de desde donde se ejecute.
    # Comprobado el 2026-08-24: con exchange=USD la misma tarjeta de 100 HKD
    # sale como "$12.35" en vez de "€10.58". Sin esto, cada ejecucion desde un
    # runner de GitHub (IP de EE.UU.) daria precios en dolares y el patron, que
    # exige el simbolo del euro, no encontraria nada.
    # OJO: la cookie 'region' NO cambia el precio (probado con spain,
    # united-states y germany: identico). El precio lo decide la IP.
    contexto.add_cookies([
        {"name": "exchange", "value": "EUR", "domain": ".eneba.com", "path": "/"},
        {"name": "lng", "value": "en", "domain": ".eneba.com", "path": "/"},
        {"name": "region", "value": "spain", "domain": ".eneba.com", "path": "/"},
    ])
    return contexto


def url_pagina(base, n):
    """Anade (o sustituye) el parametro page= de la URL base."""
    if re.search(r"[?&]page=\d+", base):
        return re.sub(r"([?&]page=)\d+", r"\g<1>%d" % n, base)
    separador = "&" if "?" in base else "?"
    return "%s%spage=%d" % (base, separador, n)


def obtener_ofertas(pagina, producto):
    """Devuelve (ofertas, enlaces) para un producto.

    ofertas: {100: 10.58, 200: 21.06, ...} precio 'From' en EUR
    enlaces: {100: 'https://www.eneba.com/...'} enlace directo a la ficha
    """
    patron_titulo = re.compile(producto["patron_titulo"], re.DOTALL)
    patron_enlace = (re.compile(producto["patron_enlace"])
                     if producto.get("patron_enlace") else None)

    ofertas, enlaces = {}, {}
    texto_total = ""

    for n in range(1, MAX_PAGINAS + 1):
        pagina.goto(url_pagina(producto["url"], n),
                    wait_until="domcontentloaded", timeout=90_000)
        try:
            pagina.wait_for_selector("text=HKD", timeout=45_000)
        except Exception:
            print("  Pagina %d: no aparecio ningun producto, dejo de paginar." % n)
            break

        pagina.wait_for_timeout(3000)  # margen para que carguen los precios
        texto = pagina.inner_text("body")
        texto_total += texto

        encontradas = {}
        for denom, eur in patron_titulo.findall(texto):
            precio = a_float(eur)
            clave = int(denom)
            # Nos quedamos con el mas barato si el producto sale repetido.
            if clave not in encontradas or precio < encontradas[clave]:
                encontradas[clave] = precio

        # Enlaces directos: se sacan del href, no del texto. El patron del
        # href es estable y evita depender de como se maquete la tarjeta.
        if patron_enlace:
            for href in pagina.eval_on_selector_all(
                    "a[href]", "els => els.map(e => e.getAttribute('href'))"):
                if not href:
                    continue
                m = patron_enlace.match(href)
                if m:
                    ruta, denom = m.group(1), int(m.group(2))
                    enlaces.setdefault(denom, "https://www.eneba.com" + ruta)

        nuevas = [k for k in encontradas if k not in ofertas]
        print("  Pagina %d: %d denominaciones (%d nuevas)"
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

    # Diagnostico util: si la pagina cargo pero en otra moneda, decirlo claro
    # en vez de soltar un generico "no se encontro nada".
    if "€" not in texto_total and re.search(r"[$£]\s?\d", texto_total):
        print("  AVISO: la pagina cargo en otra moneda (no hay simbolo de "
              "euro). La cookie 'exchange' no se aplico.")

    return ofertas, enlaces


# --- Historico -----------------------------------------------------------

def podar(muestras, ahora):
    """Tira las muestras de mas de RETENCION_DIAS para que el archivo no crezca
    sin limite."""
    limite = ahora - RETENCION_DIAS * 86400
    return [m for m in muestras if m.get("t", 0) >= limite]


def en_ventana(muestras, ahora, horas):
    limite = ahora - horas * 3600
    return [m for m in muestras if m.get("t", 0) >= limite]


def rango(muestras, denom):
    """(minimo, maximo) de una denominacion en las muestras dadas."""
    valores = [m["precios"][str(denom)] for m in muestras
               if str(denom) in m.get("precios", {})]
    if not valores:
        return None, None
    return min(valores), max(valores)


def minimo_historico(muestras, denom, ahora):
    """Minimo de una denominacion en la retencion disponible.

    Devuelve (minimo, dias_cubiertos, n_muestras). Si hay menos de RETENCION_DIAS de
    datos, devuelve los dias que haya de verdad: el mensaje debe decir la
    cobertura real, no afirmar '30 dias' cuando solo hay 2 horas.
    """
    conservadas = [m for m in muestras if str(denom) in m.get("precios", {})]
    if not conservadas:
        return None, 0.0, 0
    minimo = min(m["precios"][str(denom)] for m in conservadas)
    dias = (ahora - min(m["t"] for m in conservadas)) / 86400.0
    return minimo, dias, len(conservadas)


def texto_dias(dias):
    """'30 dias', '3 dias', '18 horas'... segun lo que se cubra de verdad."""
    if dias >= 1.5:
        return "%.0f dias" % round(dias)
    if dias >= 1:
        return "1 dia"
    horas = max(1, round(dias * 24))
    return "1 hora" if horas == 1 else "%d horas" % horas


# --- Mensajes ------------------------------------------------------------

def construir_resumen(producto, muestras, ofertas, enlaces, ahora):
    """Cuerpo de un push de resumen. Sirve para el diario y el semanal: lo
    unico que cambia es la ventana de muestras que se le pasa."""
    unidad = producto.get("unidad", "")
    lineas = [producto["nombre"]]

    if muestras:
        antigua = muestras[0]
        horas = (ahora - antigua["t"]) / 3600.0
    else:
        antigua, horas = None, 0.0

    # Honestidad: al principio el historico no cubre la ventana entera, y el
    # mensaje debe decir lo que cubre de verdad, no "24h" ni "7 dias" a secas.
    cobertura = ("%.1f dias" % (horas / 24.0)) if horas >= 48 else ("%.1f h" % horas)
    lineas.append("Ventana: %s, %d muestras" % (cobertura, len(muestras)))
    lineas.append("")

    for denom in producto["denominaciones_vigiladas"]:
        actual = ofertas.get(denom)
        if actual is None:
            lineas.append("%d %s: no encontrado ahora mismo" % (denom, unidad))
            continue

        minimo, maximo = rango(muestras, denom)
        antes = antigua["precios"].get(str(denom)) if antigua else None

        if antes is None:
            cambio = "sin referencia previa"
        elif actual < antes - EPSILON:
            cambio = "baja %.2f" % (antes - actual)
        elif actual > antes + EPSILON:
            cambio = "sube %.2f" % (actual - antes)
        else:
            cambio = "igual"

        if minimo is None:
            lineas.append("%d %s: ahora %.2f € (%s)" % (denom, unidad, actual, cambio))
        else:
            lineas.append("%d %s: ahora %.2f € | min %.2f | max %.2f | %s"
                          % (denom, unidad, actual, minimo, maximo, cambio))

    # Mejor tarjeta de TODO el catalogo, no solo de las vigiladas.
    url_boton = producto["url"]
    if ofertas:
        mejor, precio_mejor = max(ofertas.items(), key=lambda kv: kv[0] / kv[1])
        lineas.append("")
        lineas.append("Mejor tarjeta ahora mismo: %d %s — %.2f %s/€ (%.2f €)"
                      % (mejor, unidad, mejor / precio_mejor, unidad, precio_mejor))
        lineas.append("(%d denominaciones comparadas)" % len(ofertas))
        url_boton = enlaces.get(mejor, url_boton)

    lineas.append("")
    lineas.append(AVISO_ORIENTATIVO)
    return "\n".join(lineas), url_boton


# --- Un producto ---------------------------------------------------------

def procesar(producto, pagina, estado, historial, ahora):
    """Procesa un producto. Devuelve (ok, resumen_enviado)."""
    pid = producto["id"]
    unidad = producto.get("unidad", "")
    print("\n=== %s (%s) ===" % (producto["nombre"], pid))

    est = estado["productos"].setdefault(pid, {})
    hist = historial["productos"].setdefault(pid, {"muestras": []})
    muestras = podar(hist.get("muestras", []), ahora)

    ofertas, enlaces = obtener_ofertas(pagina, producto)

    if not ofertas:
        print("  No se ha podido extraer ninguna oferta. "
              "Probablemente Eneba cambio el HTML: revisa patron_titulo.")
        if not est.get("fallo_previo"):
            enviar_o_encolar(estado, ahora, "Eneba tracker roto: %s" % pid,
                             "No se pudo leer ningun precio de %s. Revisa "
                             "patron_titulo en productos.json."
                             % producto["nombre"],
                             prioridad="high", tags="warning",
                             url_accion=producto["url"])
        est["fallo_previo"] = True
        hist["muestras"] = muestras
        return False, False

    print("  Total denominaciones: %d -> %s" % (len(ofertas), sorted(ofertas)))
    print("  Enlaces directos capturados: %d" % len(enlaces))

    # --- Alerta puntual de bajada ---------------------------------------
    anteriores = est.get("precios", {})
    lineas = [producto["nombre"]]
    hay_alerta = False
    url_boton = producto["url"]
    denom_alerta = None

    for denom in producto["denominaciones_vigiladas"]:
        if denom not in ofertas:
            print("  %d %s: no encontrado en la pagina." % (denom, unidad))
            continue

        precio = ofertas[denom]
        ratio = denom / precio  # unidades por euro; mas alto = mejor
        antes = anteriores.get(str(denom))
        notas = []

        if antes is None:
            marca = "nuevo"
        elif precio < antes - EPSILON:
            bajada = antes - precio
            umbral = max(UMBRAL_BAJADA_EUR, antes * UMBRAL_BAJADA_PCT / 100.0)
            if bajada >= umbral:
                marca = "BAJA %.2f desde %.2f" % (bajada, antes)
                hay_alerta = True
                if denom_alerta is None:
                    denom_alerta = denom
            else:
                marca = ("baja %.2f desde %.2f (bajo umbral %.2f)"
                         % (bajada, antes, umbral))
        elif precio > antes + EPSILON:
            marca = "sube desde %.2f" % antes
        else:
            marca = "igual"

        # Minimo historico: se compara contra el historico ANTERIOR a esta
        # lectura, que aun no se ha anadido.
        min_hist, dias, n_muestras = minimo_historico(muestras, denom, ahora)
        if min_hist is not None and precio <= min_hist + EPSILON:
            notas.append("📉 Precio mas bajo visto en %s" % texto_dias(dias))

            # El minimo historico avisa por si solo, aunque la bajada no llegue
            # al umbral: tocar el minimo de 30 dias es justo cuando interesa
            # enterarse. Con dos matices para no dar la lata:
            #  - Hacen falta MIN_MUESTRAS_HISTORICO lecturas. Un "minimo
            #    historico" calculado sobre una sola muestra no dice nada:
            #    siempre se cumple.
            #  - Si el precio lleva plano en su minimo, se cumpliria cada hora.
            #    Por eso solo dispara cuando marca un minimo NUEVO, o cuando
            #    vuelve a el despues de haber estado por encima.
            if n_muestras >= MIN_MUESTRAS_HISTORICO:
                nuevo_minimo = precio < min_hist - EPSILON
                vuelve_al_minimo = antes is not None and antes > min_hist + EPSILON
                if nuevo_minimo or vuelve_al_minimo:
                    hay_alerta = True
                    if denom_alerta is None:
                        denom_alerta = denom

        if RATIO_OBJETIVO and ratio >= RATIO_OBJETIVO:
            marca += " | objetivo %.2f alcanzado" % RATIO_OBJETIVO
            hay_alerta = True
            if denom_alerta is None:
                denom_alerta = denom

        print("  %d %s -> %.2f EUR (%.2f/€) [%s]%s"
              % (denom, unidad, precio, ratio, marca,
                 " " + " ".join(notas) if notas else ""))
        lineas.append("%d %s: %.2f € (%.2f %s/€) [%s]"
                      % (denom, unidad, precio, ratio, unidad, marca))
        for nota in notas:
            lineas.append("   " + nota)

    mejor, precio_mejor = max(ofertas.items(), key=lambda kv: kv[0] / kv[1])
    lineas.append("Mejor ratio: %d %s (%.2f %s/€)"
                  % (mejor, unidad, mejor / precio_mejor, unidad))
    lineas.append(AVISO_ORIENTATIVO)
    if denom_alerta is not None:
        url_boton = enlaces.get(denom_alerta, producto["url"])

    if not anteriores:
        print("  Primera ejecucion de este producto: guardo estado, sin comparar.")
    elif hay_alerta:
        enviar_o_encolar(estado, ahora,
                         "Eneba: baja %s" % producto["nombre"],
                         "\n".join(lineas), prioridad="high",
                         tags="chart_with_downwards_trend",
                         url_accion=url_boton)
    else:
        print("  Sin bajadas por encima del umbral. No envio alerta.")

    # --- Historico -------------------------------------------------------
    # Solo se guardan las denominaciones vigiladas, no las 34: el historico se
    # commitea cada hora y guardar 34 precios x 30 dias hincharia el repo sin
    # aportar nada (el resto solo se usa en la lectura actual).
    muestras.append({
        "t": int(ahora),
        "iso": hora_utc(ahora),
        "precios": {str(d): ofertas[d]
                    for d in producto["denominaciones_vigiladas"] if d in ofertas},
    })
    muestras.sort(key=lambda m: m["t"])

    # --- Resumenes: semanal y diario -------------------------------------
    resumen_enviado = False

    ultimo_sem = est.get("ultimo_resumen_semanal")
    toca_semanal = (ultimo_sem is not None
                    and (ahora - ultimo_sem) >= DIAS_ENTRE_RESUMENES_SEMANALES * 86400)
    if ultimo_sem is None:
        print("  Sin resumen semanal previo: arranco el contador (~7 dias).")
        est["ultimo_resumen_semanal"] = int(ahora)

    if toca_semanal:
        print("  Toca resumen SEMANAL (%.1f dias desde el ultimo)."
              % ((ahora - ultimo_sem) / 86400.0))
        cuerpo, url_res = construir_resumen(
            producto, en_ventana(muestras, ahora, VENTANA_SEMANAL_HORAS),
            ofertas, enlaces, ahora)
        enviar_o_encolar(estado, ahora,
                         "Eneba: resumen semanal — %s" % producto["nombre"],
                         cuerpo, prioridad="default", tags="calendar",
                         url_accion=url_res)
        est["ultimo_resumen_semanal"] = int(ahora)
        resumen_enviado = True
        # El semanal contiene lo mismo que el diario con mas recorrido:
        # mandar los dos seguidos seria repetirse. Se reinicia el contador
        # del diario para que el siguiente salga dentro de ~24h.
        est["ultimo_resumen"] = int(ahora)
        print("  Diario omitido en esta ejecucion: el semanal ya lo cubre.")

    ultimo = est.get("ultimo_resumen")
    if ultimo is None:
        # Primera vez: no tiene sentido resumir 24h con una sola muestra.
        print("  Sin resumen previo: arranco el contador, el primero en ~24h.")
        est["ultimo_resumen"] = int(ahora)
    elif not toca_semanal and (ahora - ultimo) >= HORAS_ENTRE_RESUMENES * 3600:
        print("  Toca resumen diario (%.1f h desde el ultimo)."
              % ((ahora - ultimo) / 3600.0))
        cuerpo, url_res = construir_resumen(
            producto, en_ventana(muestras, ahora, VENTANA_RESUMEN_HORAS),
            ofertas, enlaces, ahora)
        enviar_o_encolar(estado, ahora,
                         "Eneba: resumen 24h — %s" % producto["nombre"],
                         cuerpo, prioridad="default", tags="bar_chart",
                         url_accion=url_res)
        est["ultimo_resumen"] = int(ahora)
        resumen_enviado = True
    elif not toca_semanal:
        print("  Resumen no toca todavia (faltan %.1f h)."
              % (HORAS_ENTRE_RESUMENES - (ahora - ultimo) / 3600.0))

    # --- Guardar ---------------------------------------------------------
    est["nombre"] = producto["nombre"]
    est["unidad"] = unidad
    est["vigiladas"] = producto["denominaciones_vigiladas"]
    est["precios"] = {str(d): ofertas[d]
                      for d in producto["denominaciones_vigiladas"] if d in ofertas}
    est["todas"] = {str(k): v for k, v in sorted(ofertas.items())}
    est["enlaces"] = {str(k): v for k, v in sorted(enlaces.items())}
    est["actualizado"] = hora_utc(ahora)
    est["fallo_previo"] = False

    hist["muestras"] = muestras
    print("  Historial: %d muestras (retencion %d dias)."
          % (len(muestras), RETENCION_DIAS))
    return True, resumen_enviado


# --- Programa principal --------------------------------------------------

def main():
    ahora = time.time()

    config = leer_json(PRODUCTOS_FILE, None)
    if not config or not config.get("productos"):
        print("No hay productos que vigilar: revisa productos.json.")
        return 1
    productos = config["productos"]
    print("Productos a vigilar: %d" % len(productos))

    id_principal = productos[0]["id"]
    estado = migrar(leer_json(STATE_FILE, {}), "state.json", id_principal)
    historial = migrar(leer_json(HISTORIAL_FILE, {}), "historial.json", id_principal)
    estado.setdefault("productos", {})
    historial.setdefault("productos", {})

    # Lo primero, soltar lo que quedo retenido de la noche. Va antes de
    # consultar precios para que un fallo del scraping no deje los avisos
    # de madrugada atrapados un dia mas.
    if en_silencio(ahora):
        print("Silencio nocturno activo (%s-%s hora de %s; ahora son las %s)."
              % (SILENCIO_INICIO, SILENCIO_FIN, ZONA_USUARIO,
                 hora_local(ahora).strftime("%H:%M")))
    else:
        vaciar_cola(estado, ahora)

    todo_bien = True
    hubo_resumen = False
    with sync_playwright() as p:
        navegador = abrir_navegador(p)
        contexto = preparar_contexto(navegador)
        pagina = contexto.new_page()
        try:
            for producto in productos:
                ok, resumen = procesar(producto, pagina, estado, historial, ahora)
                todo_bien = todo_bien and ok
                hubo_resumen = hubo_resumen or resumen
        finally:
            navegador.close()

    guardar_json(STATE_FILE, estado)
    guardar_json(HISTORIAL_FILE, historial)
    exportar_salida("resumen_enviado", "true" if hubo_resumen else "false")
    return 0 if todo_bien else 1


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
