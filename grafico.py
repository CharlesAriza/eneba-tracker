"""
Genera un PNG por producto con la evolucion de precio y ratio a partir de
historial.json. Se ejecuta despues de check_price.py.

Va en un script aparte a proposito: si matplotlib falla o no esta instalado,
la vigilancia de precios (que es lo importante) no se cae con el.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # sin ventana: en un runner no hay pantalla
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

AQUI = Path(__file__).parent
HISTORIAL_FILE = AQUI / "historial.json"
PRODUCTOS_FILE = AQUI / "productos.json"

DIAS = 30
COLORES = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e"]


def leer(ruta, por_defecto):
    if ruta.exists():
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return por_defecto


def dibujar(pid, nombre, unidad, vigiladas, muestras, destino):
    if not muestras:
        print("  %s: sin muestras, no genero grafico." % pid)
        return False

    # Solo las denominaciones vigiladas. Las muestras antiguas guardaban las
    # 34 del catalogo: pintarlas todas hace ilegible la leyenda y el grafico.
    presentes = {int(d) for m in muestras for d in m.get("precios", {})}
    denoms = sorted(presentes & set(vigiladas)) if vigiladas else sorted(presentes)
    if not denoms:
        print("  %s: las muestras no traen precios de las vigiladas." % pid)
        return False

    fechas = [datetime.fromtimestamp(m["t"], timezone.utc) for m in muestras]
    span_h = (muestras[-1]["t"] - muestras[0]["t"]) / 3600.0

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(11, 7.5), sharex=True,
        gridspec_kw={"height_ratios": [1, 1], "hspace": 0.18})

    for i, d in enumerate(denoms):
        color = COLORES[i % len(COLORES)]
        xs = [f for f, m in zip(fechas, muestras) if str(d) in m.get("precios", {})]
        ys = [m["precios"][str(d)] for m in muestras if str(d) in m.get("precios", {})]
        if not ys:
            continue
        ratios = [d / y for y in ys]

        ax1.plot(xs, ratios, marker="o", ms=3, lw=1.6, color=color,
                 label="%d %s" % (d, unidad))
        ax2.plot(xs, ys, marker="o", ms=3, lw=1.6, color=color,
                 label="%d %s" % (d, unidad))

        # Marcamos el minimo de precio: es el dato que interesa al comprar.
        imin = min(range(len(ys)), key=lambda k: ys[k])
        ax2.annotate("min %.2f €" % ys[imin], (xs[imin], ys[imin]),
                     textcoords="offset points", xytext=(0, -14),
                     fontsize=8, color=color, ha="center")

    # Con pocas horas de datos, "ultimos 0 dias" no informa de nada.
    if span_h < 48:
        cobertura = "ultimas %.0f h" % max(1, round(span_h))
    else:
        cobertura = "ultimos %.0f dias" % round(span_h / 24.0)
    ax1.set_title("%s — %s (%d muestras)"
                  % (nombre, cobertura, len(muestras)), fontsize=13)
    ax1.set_ylabel("Ratio %s por € (mas alto = mejor)" % unidad)
    ax2.set_ylabel("Precio en €")
    ax2.set_xlabel("Fecha (UTC)")

    for ax in (ax1, ax2):
        ax.grid(True, alpha=0.3, ls="--")
        ax.legend(loc="best", fontsize=9, ncol=min(len(denoms), 4))

    # Con pocas horas de datos, las etiquetas por dia salen todas iguales.
    if span_h <= 48:
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m %H:%M"))
    else:
        ax2.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m"))
    fig.autofmt_xdate(rotation=30, ha="right")

    fig.text(0.5, 0.015,
             "Precios orientativos: los ve un servidor en EE.UU. y van ~5% "
             "por encima de los de Espana. Verificar en Eneba antes de comprar.",
             ha="center", fontsize=8, style="italic", color="#555555")

    fig.savefig(destino, dpi=110, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("  %s -> %s (%d muestras, %.1f h)"
          % (pid, destino.name, len(muestras), span_h))
    return True


def main():
    historial = leer(HISTORIAL_FILE, {}).get("productos", {})
    config = leer(PRODUCTOS_FILE, {}).get("productos", [])
    metadatos = {p["id"]: p for p in config}

    if not historial:
        print("historial.json vacio: nada que dibujar.")
        return 0

    generados = 0
    for pid, cont in sorted(historial.items()):
        meta = metadatos.get(pid, {})
        muestras = sorted(cont.get("muestras", []), key=lambda m: m["t"])
        destino = AQUI / ("historial-%s.png" % pid)
        if dibujar(pid, meta.get("nombre", pid), meta.get("unidad", ""),
                   meta.get("denominaciones_vigiladas", []),
                   muestras, destino):
            generados += 1

    print("Graficos generados: %d" % generados)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
