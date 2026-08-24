"""
Genera los iconos de la PWA a partir de un unico diseno.

Se ejecuta a mano cuando cambia el diseno; no forma parte del workflow.

Diseno: la misma linea descendente que dibuja el panel (una bajada de precio
es la buena noticia que persigue el proyecto) sobre el azul oscuro del tema,
con el punto final en el verde que ya usan los graficos y un simbolo del euro
como marca de agua.

Se generan dos variantes. La normal ('any') aprovecha todo el cuadrado. La
'maskable' encoge el dibujo al 78% para que quepa en la zona segura de
Android: alli el sistema recorta el icono en circulo u otra forma, y con el
dibujo a tamano completo el punto verde se quedaria fuera del recorte.

Las imagenes son cuadradas a sangre, sin esquinas redondeadas propias: iOS y
Android aplican su propia mascara. Redondearlas aqui daria un doble
redondeado feo.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

AQUI = Path(__file__).parent
DESTINO = AQUI / "icons"

SUPER = 4  # se dibuja a 4x y se reduce: asi salen bordes suaves

FONDO_ARRIBA = (34, 48, 74)     # #22304a
FONDO_ABAJO = (14, 18, 24)      # #0e1218
LINEA = (90, 169, 230)          # #5aa9e6, el acento del panel en oscuro
PUNTO = (53, 196, 106)          # #35c46a, "buen precio"
ANILLO = (14, 18, 24)

# Puntos de la linea, en fracciones del lado. Baja en conjunto pero con un
# repunte: una linea recta parece un icono de "menos", no un grafico.
RUTA = [(0.15, 0.33), (0.33, 0.45), (0.47, 0.39), (0.63, 0.60), (0.85, 0.73)]

FUENTES = [
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def fondo(lado):
    """Degradado vertical, sutil, para que no sea un cuadrado plano."""
    img = Image.new("RGB", (lado, lado))
    px = img.load()
    for y in range(lado):
        t = y / max(1, lado - 1)
        color = tuple(int(a + (b - a) * t) for a, b in zip(FONDO_ARRIBA, FONDO_ABAJO))
        for x in range(lado):
            px[x, y] = color
    return img


def marca_euro(img, lado, escala):
    """Simbolo del euro como marca de agua. Si no hay fuente, se omite: es
    decoracion, no debe romper la generacion."""
    ruta = next((f for f in FUENTES if Path(f).exists()), None)
    if not ruta:
        print("  (sin fuente disponible: omito la marca de agua)")
        return
    capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(capa)
    # Se escala junto con la linea: en la version maskable, un euro a tamano
    # completo se saldria de la zona segura igual que se salia el punto.
    fuente = ImageFont.truetype(ruta, int(lado * 0.54 * escala))
    caja = d.textbbox((0, 0), "€", font=fuente)
    ancho, alto = caja[2] - caja[0], caja[3] - caja[1]
    d.text((lado * 0.5 - ancho / 2 - caja[0], lado * 0.5 - alto / 2 - caja[1]),
           "€", font=fuente, fill=(255, 255, 255, 30))
    img.paste(Image.alpha_composite(img.convert("RGBA"), capa).convert("RGB"), (0, 0))


def dibujar(lado, escala=1.0):
    grande = lado * SUPER
    img = fondo(grande)
    marca_euro(img, grande, escala)
    d = ImageDraw.Draw(img)

    # Encoger alrededor del centro conserva la composicion; recortar no.
    pts = [((0.5 + (x - 0.5) * escala) * grande,
            (0.5 + (y - 0.5) * escala) * grande) for x, y in RUTA]
    grosor = int(grande * 0.075 * escala)

    # joint="curve" redondea los vertices; los circulos redondean las puntas.
    d.line(pts, fill=LINEA, width=grosor, joint="curve")
    for x, y in (pts[0], pts[-1]):
        r = grosor / 2
        d.ellipse([x - r, y - r, x + r, y + r], fill=LINEA)

    # Punto final: anillo del color del fondo para que despegue de la linea.
    xf, yf = pts[-1]
    r_ext = grande * 0.105 * escala
    r_int = grande * 0.072 * escala
    d.ellipse([xf - r_ext, yf - r_ext, xf + r_ext, yf + r_ext], fill=ANILLO)
    d.ellipse([xf - r_int, yf - r_int, xf + r_int, yf + r_int], fill=PUNTO)

    return img.resize((lado, lado), Image.LANCZOS)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="f" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#22304a"/>
      <stop offset="1" stop-color="#0e1218"/>
    </linearGradient>
  </defs>
  <rect width="512" height="512" fill="url(#f)"/>
  <text x="256" y="266" font-family="Segoe UI, Arial, sans-serif" font-weight="700"
        font-size="317" fill="#ffffff" fill-opacity="0.11"
        text-anchor="middle" dominant-baseline="central">&#8364;</text>
  <polyline points="76.8,169 169,230 241,200 322,307 435,374"
            fill="none" stroke="#5aa9e6" stroke-width="38"
            stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="435" cy="374" r="54" fill="#0e1218"/>
  <circle cx="435" cy="374" r="37" fill="#35c46a"/>
</svg>
"""


def main():
    DESTINO.mkdir(exist_ok=True)
    # 180 = apple-touch-icon; 192 y 512 = minimos que pide el manifest.
    for lado, nombre, escala in [(180, "apple-touch-icon-180.png", 1.0),
                                 (192, "icon-192.png", 1.0),
                                 (512, "icon-512.png", 1.0),
                                 (512, "icon-512-maskable.png", 0.78)]:
        img = dibujar(lado, escala)
        ruta = DESTINO / nombre
        img.save(ruta, "PNG", optimize=True)
        print("  %s (%dx%d, %.1f KB)"
              % (nombre, lado, lado, ruta.stat().st_size / 1024))

    (DESTINO / "icon.svg").write_text(SVG, encoding="utf-8")
    print("  icon.svg (vectorial, para la pestana del navegador)")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
