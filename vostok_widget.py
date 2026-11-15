#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Vostok Amphibia 090679 - widget desktop (PyQt6)

Comandi:
  - trascina sul quadrante/cassa ......... sposta l'orologio
  - trascina sulla ghiera ................ ruota la ghiera (a scatti di 1 minuto)
  - click sulla corona ................... la fa scattare in fuori (0 -> 1 -> 2 -> 0)
  - rotella SOPRA la corona estratta ..... posizione 1: corregge giorno/data
                                            posizione 2: regola ore e minuti
  - rotella altrove ....................... zoom
  - icona in alto (fronte/retro) ......... gira l'orologio
  - icona in basso (solo sul retro) ...... svita/avvita il fondello
  - click centrale ....................... prova dell'allarme
  - click durante l'allarme .............. lo interrompe
  - click destro ......................... chiude il widget

Allarme: quando il puntino nero della ghiera viene messo DOPO la lancetta dei minuti,
al passaggio della lancetta sul puntino l'orologio suona e vibra per 10 secondi.

Il giorno e la data cambiano allo scoccare della mezzanotte (o correggendoli a mano
dalla corona in posizione 1).

C'e' anche qualcosa di nascosto... (vedi EE_* piu' sotto).

Font: la scritta "Амфибия" usa Marck Script (licenza OFL). Metti MarckScript-Regular.ttf
nella stessa cartella di questo script (o in una sottocartella "fonts"). Se manca viene
usato un font di ripiego.

Multipiattaforma: sviluppato e usato su Linux Mint, ma pensato per girare anche su
Windows (l'audio usa winsound al posto dei lettori a riga di comando) e su macOS.

Posizione e dimensione si ricordano da una sessione all'altra (vedi RICORDA_POSIZIONE
qui sotto), in un piccolo file nella cartella utente: ~/.vostok_widget_stato.json.
"""
import sys
import os
import json
import math
import random
import shutil
import struct
import subprocess
import tempfile
import threading
import time
import wave

from PyQt6.QtWidgets import (QApplication, QWidget, QDialog, QVBoxLayout, QFormLayout, QComboBox,
                             QLineEdit, QPushButton, QLabel, QCheckBox)
from PyQt6.QtCore import Qt, QTimer, QPoint, QPointF, QRectF, QLineF, QDateTime
from PyQt6.QtGui import (QPainter, QPen, QBrush, QColor, QFont, QFontDatabase,
                         QFontMetricsF, QPainterPath, QLinearGradient,
                         QRadialGradient, QConicalGradient, QPixmap, QTransform)

# ============================================================
# CONFIGURAZIONE
# ============================================================
DIM_INIZIALE = (600, 500)          # larghezza x altezza iniziali in pixel (usate solo la prima volta)
TIMER_MS = 16                      # 16 = ~60 fps, 33 = ~30 fps
RICORDA_POSIZIONE = True           # True = alla riapertura ricompare dove e come l'avevi lasciato
FILE_STATO = os.path.join(os.path.expanduser("~"), ".vostok_widget_stato.json")
MOSTRA_GIORNO = True               # True = finestrelle giorno + data, False = solo data (come l'originale)

GHIERA_SOLO_ORARIO = True          # True = ghiera unidirezionale (l'easter egg sblocca l'antiorario)
GHIERA_SCATTO_GRADI = 6            # 6 gradi = 1 minuto per scatto
GHIERA_DENTELLATA = True           # bordo della ghiera dentellato
GHIERA_DENTI = 30                  # numero di denti
GHIERA_DENTI_PROFONDITA = 5.2      # profondita' dei denti (unita' base)
GHIERA_MOSTRA_MINUTO = True        # mostra il minuto sotto il puntino mentre giri la ghiera

ALLARME_SUONO = True
ALLARME_TREMOLIO = True
ALLARME_DURATA_S = 10              # durata di trillo, vibrazione e lampeggio
ALLARME_RIPETI_OGNI_ORA = False    # False = suona una volta e si disarma; True = suona a ogni passaggio

# --- Easter egg -------------------------------------------------------------
# 1) Ruota la ghiera fino a mettere il puntino a ore 4 (minuto 20) e TIENILO fermo con il
#    mouse premuto per EE_TENUTA_MS: si sblocca la rotazione in senso antiorario.
# 2) Poi esegui la combinazione: 9 movimenti della ghiera. Ognuno va portato sul minuto indicato
#    e nel verso indicato (+1 = orario, -1 = antiorario), poi la ghiera va lasciata FERMA per circa
#    un secondo (EE_SOSTA_MS): e' in quel momento che il passo viene valutato, anche se tieni ancora
#    il mouse premuto. Puoi rilasciare e riprendere la ghiera quante volte vuoi durante un passo.
#    Ogni passo giusto fa "clic".
#    I numeri sono la posizione nell'alfabeto russo delle lettere di ЧИСТОПОЛЬ (Chistopol,
#    la citta' della fabbrica Vostok): Ч=25 И=10 С=19 Т=20 О=16 П=17 О=16 Л=13 Ь=30.
EASTER_EGG = True
EE_MINUTO_SBLOCCO = 20
EE_TENUTA_MS = 2000                # tempo da tenere fermo il puntino a ore 4 (mouse premuto) per lo sblocco
EE_SOSTA_MS = 900                  # ogni numero va raggiunto e la ghiera lasciata FERMA per questo tempo
EE_TIMEOUT_S = 120                 # dopo tanti secondi tra due passi la combinazione riparte da zero
EE_DEBUG = False                   # True = stampa nel terminale l'esito di ogni passo
EE_COMBINAZIONE = [(25, +1), (10, -1), (19, +1), (20, +1), (16, -1),
                   (17, +1), (16, -1), (13, -1), (30, +1)]
PREMIO_DURATA_S = 12

# --- Corona -------------------------------------------------------------
# Un click sulla corona la fa scattare in fuori di una posizione: 0 -> 1 -> 2 -> 0.
#   posizione 0: normale, a filo della cassa.
#   posizione 1: mezza estrazione. La rotella del mouse SOPRA la corona corregge
#                rapidamente giorno e data (in modo indipendente, come su un vero
#                Vostok 2416): verso l'alto cambia il campo indicato da
#                CROWN_SU_CAMBIA, verso il basso cambia l'altro campo.
#   posizione 2: estrazione completa. La lancetta dei secondi si ferma (come nei
#                meccanici veri) e la rotella regola le lancette, un minuto alla volta.
CROWN_SU_CAMBIA = "data"           # "data" (il numero) oppure "giorno" (il nome del
                                    # giorno) - il verso opposto della rotella cambia
                                    # sempre l'altro campo

# --- Ghiera: materiale ----------------------------------------------------
BEZEL_MATERIAL = "enamel"          # "enamel" = ghiera bianca smaltata con stampa nera
                                    # (il modello 090679 di riferimento) | "steel" =
                                    # ghiera in acciaio nudo con stampa nera | "ceramic"
                                    # = ghiera in ceramica lucida colorata (vedi
                                    # BEZEL_CERAMIC_COLOR) con stampa chiara
BEZEL_CERAMIC_COLOR = "black"      # usato solo se BEZEL_MATERIAL == "ceramic":
                                    # "black" | "blue" | "green" | "orange" | "grigio"

# --- Quadrante: catalogo Vostok -------------------------------------------
DIAL_PRESET = "090679"             # scegli il quadrante dal catalogo DIALS piu' sotto

# --- Fondello (caseback) ---------------------------------------------------
CASEBACK_DEDICA = ""                # testo inciso sul fondello, es. "A Giuseppina, 2026"
                                    # (stringa vuota = nessuna dedica)
CASEBACK_NUMERO_SERIE = "125692"    # numero inciso sotto il logo, come su un fondello vero

# --- Meccanismo: carica a scossa -------------------------------------------
# Il bilanciere non oscilla da solo: un click sul meccanismo (a fondello aperto) lo
# "carica", come dare una scossa a un automatico. Il rotore riceve una spinta e rallenta
# per attrito, e finche' c'e' carica residua il bilanciere batte; poi si ferma, come un
# meccanico che si scarica. Altri click aggiungono altra carica (fino al massimo).
CARICA_PER_SCOSSA = 6.0             # secondi di carica aggiunti per ogni click
CARICA_MASSIMA = 24.0               # secondi di carica accumulabile al massimo
BILANCIERE_HZ = 3.0                 # battiti al secondo del bilanciere (stilizzato)
ROTORE_SPINTA = 240.0               # velocita' angolare (gradi/s) impressa dalla scossa
ROTORE_ATTRITO = 0.965              # quanto rallenta il rotore a ogni fotogramma

DIR_SCRIPT = os.path.dirname(os.path.abspath(__file__))
FILE_FONT_CORSIVO = [os.path.join(DIR_SCRIPT, "MarckScript-Regular.ttf"),
                     os.path.join(DIR_SCRIPT, "fonts", "MarckScript-Regular.ttf")]

# ============================================================
# GEOMETRIA (unita' base: il quadrante e' centrato in 0,0; 500 unita' = altezza finestra)
# ============================================================
R_QUADRANTE = 137.0
R_ORO = (137.0, 144.0)             # anello dorato attorno al quadrante
R_ACCIAIO = (144.0, 157.0)         # anello in acciaio sotto la ghiera
R_GHIERA = (157.0, 178.0)          # fascia bianca della ghiera
R_ORLO = (178.0, 184.5)            # orlo in acciaio della ghiera
R_TRACCIA = 169.5                  # raggio dell'arco nero, dei numeri e del puntino

# ============================================================
# COLORI - ORO E ACCIAIO
# ============================================================
ORO_TESTO = QColor(204, 165, 72)
ORO_LINEE = QColor(196, 158, 64)
LUME = (246, 243, 224)
LUME_NOTTE = (170, 255, 205)
NERO_GHIERA = QColor(16, 16, 18)

# Gradienti metallici (posizione, (r, g, b))
ACCIAIO_CASSA = [(0.00, (236, 238, 242)), (0.14, (190, 194, 201)), (0.30, (224, 227, 232)),
                 (0.46, (170, 175, 183)), (0.62, (214, 217, 223)), (0.80, (164, 169, 177)),
                 (1.00, (200, 204, 211))]
ACCIAIO_ANELLO = [(0.00, (228, 231, 236)), (0.10, (122, 127, 136)), (0.20, (240, 243, 247)),
                  (0.30, (152, 157, 166)), (0.42, (98, 103, 112)), (0.52, (208, 212, 219)),
                  (0.64, (134, 139, 148)), (0.78, (234, 237, 242)), (0.90, (120, 125, 134)),
                  (1.00, (228, 231, 236))]
ACCIAIO_ORLO = [(0.00, (238, 240, 244)), (0.12, (140, 145, 154)), (0.26, (250, 251, 253)),
                (0.42, (128, 133, 142)), (0.58, (236, 238, 243)), (0.74, (146, 151, 160)),
                (0.88, (244, 246, 249)), (1.00, (238, 240, 244))]
ACCIAIO_CILINDRO = [(0.00, (92, 96, 104)), (0.18, (200, 204, 211)), (0.42, (250, 251, 253)),
                    (0.66, (150, 155, 164)), (0.86, (200, 204, 211)), (1.00, (84, 88, 96))]
ORO_ANELLO = [(0.00, (255, 238, 170)), (0.10, (204, 156, 50)), (0.22, (124, 84, 18)),
              (0.34, (248, 216, 122)), (0.50, (180, 132, 34)), (0.62, (255, 241, 178)),
              (0.76, (152, 106, 24)), (0.88, (234, 198, 98)), (1.00, (255, 238, 170))]
ORO_LAMA = [(0.00, (112, 74, 14)), (0.14, (196, 150, 48)), (0.40, (255, 240, 176)),
            (0.58, (228, 186, 84)), (0.82, (168, 122, 32)), (1.00, (98, 64, 12))]
INOX_LAMA = [(0.00, (100, 104, 112)), (0.14, (190, 194, 201)), (0.40, (250, 251, 253)),
             (0.58, (214, 217, 223)), (0.82, (150, 155, 164)), (1.00, (90, 94, 102))]
PERNO_ORO = [(0.0, (255, 244, 186)), (0.45, (226, 184, 80)), (0.8, (164, 118, 30)), (1.0, (110, 74, 14))]
PERNO_INOX = [(0.0, (250, 251, 253)), (0.45, (208, 212, 219)), (0.8, (150, 155, 164)), (1.0, (92, 96, 104))]

# Metallo di indici, lancette, anello e perno centrale
METALLI = {
    "gold": dict(lama=ORO_LAMA, anello=ORO_ANELLO, anello_pen=(96, 64, 12),
                pen_scuro=(88, 58, 10), perno=PERNO_ORO),
    "steel": dict(lama=INOX_LAMA, anello=ACCIAIO_ANELLO, anello_pen=(60, 64, 72),
                 pen_scuro=(60, 64, 72), perno=PERNO_INOX),
}

# Catalogo quadranti (ispirato alla linea Vostok Amphibia su meranom.com; le varianti
# diverse dalla 090679 sono colorazioni plausibili della linea, non riproduzioni esatte
# di un singolo codice prodotto - per una fedelta' pixel-precisa manda la foto di
# riferimento e la ricalibro)
DIALS = {
    "090679": dict(display="090679M - nero, indici e lancette dorate (il modello di riferimento)",
                   dial=((16, 16, 19), (3, 3, 4)), metal="gold", accent=(204, 165, 72)),
    "090059": dict(display="stile 090059M - nero, indici e lancette acciaiate",
                   dial=((16, 16, 19), (3, 3, 4)), metal="steel", accent=(225, 227, 231)),
    "blu-oro": dict(display="variante blu, indici e lancette dorate (linea Amphibia blu)",
                    dial=((10, 26, 54), (3, 10, 26)), metal="gold", accent=(226, 196, 128)),
    "verde-acciaio": dict(display="variante verde scuro, indici e lancette acciaiate (linea Reef/Scuba)",
                          dial=((8, 26, 20), (2, 9, 7)), metal="steel", accent=(214, 222, 218)),
    "marrone-oro": dict(display="variante marrone (\"root beer\"), indici e lancette dorate (linea Amphibia SE)",
                        dial=((46, 28, 14), (16, 9, 5)), metal="gold", accent=(214, 178, 102)),
}

# Tavolozze della ghiera in ceramica (usate solo se BEZEL_MATERIAL == "ceramic")
CERAMIC_PALETTES = {
    "black": dict(base=((46, 48, 52), (10, 11, 13)), ink=(238, 238, 234)),
    "blue": dict(base=((20, 56, 112), (4, 14, 34)), ink=(238, 244, 252)),
    "green": dict(base=((14, 60, 42), (3, 16, 11)), ink=(232, 244, 236)),
    "orange": dict(base=((168, 74, 20), (74, 30, 6)), ink=(255, 246, 232)),
    "grigio": dict(base=((100, 102, 106), (44, 45, 48)), ink=(24, 24, 26)),
}

# Inserto della ghiera in acciaio "nudo": volutamente piu' scuro e contrastato della cassa,
# altrimenti i due acciai si confondono e la ghiera sembra sparire (un vero inserto in
# acciaio di un subacqueo e' quasi sempre opacizzato/brunito per distinguersi dalla cassa lucida)
GHIERA_ACCIAIO = [(0.00, (150, 153, 159)), (0.15, (92, 95, 101)), (0.32, (188, 191, 196)),
                  (0.50, (82, 85, 91)), (0.68, (172, 175, 180)), (0.84, (88, 91, 97)),
                  (1.00, (150, 153, 159))]


def _stops(grad, stops, alpha=255):
    for pos, (r, g, b) in stops:
        grad.setColorAt(pos, QColor(r, g, b, alpha))
    return grad


def grad_lineare(x0, y0, x1, y1, stops):
    return _stops(QLinearGradient(x0, y0, x1, y1), stops)


def grad_conico(angolo, stops):
    return _stops(QConicalGradient(0, 0, angolo), stops)


def grad_radiale(cx, cy, r, stops):
    return _stops(QRadialGradient(QPointF(cx, cy), r), stops)


# ============================================================
# FUNZIONI DI SUPPORTO
# ============================================================
def _intersezione_cerchi(c1, r1, c2, r2):
    (x1, y1), (x2, y2) = c1, c2
    dx, dy = x2 - x1, y2 - y1
    d = math.hypot(dx, dy)
    a = (r1 * r1 - r2 * r2 + d * d) / (2 * d)
    h = math.sqrt(max(r1 * r1 - a * a, 0.0))
    ux, uy = dx / d, dy / d
    px, py = x1 + a * ux, y1 + a * uy
    return [(px - h * uy, py + h * ux), (px + h * uy, py - h * ux)]


def crea_percorso_tonneau(H=228.0, W=195.0, a=143.0, t=8.0, r_raccordo=48.0):
    """
    Cassa tonneau perfettamente simmetrica sui due assi.
      H = semi-altezza ai bordi, W = semi-larghezza massima (a meta' altezza),
      a = semi-larghezza dello spigolo superiore, t = bombatura di lato alto/basso,
      r_raccordo = raggio degli angoli arrotondati.
    Lati = archi di cerchio, angoli = raccordo tangente ai due archi.
    """
    Rt = (a * a + t * t) / (2 * t)                        # arco lato alto
    ct = (0.0, -H - t + Rt)
    Rs = (H * H + (W - a) ** 2) / (2 * (W - a))            # arco lato destro
    cs = (W - Rs, 0.0)
    cand = _intersezione_cerchi(ct, Rt - r_raccordo, cs, Rs - r_raccordo)
    fx, fy = min(cand, key=lambda q: q[1])                 # centro del raccordo in alto a destra

    def su_cerchio(c, R):
        vx, vy = fx - c[0], fy - c[1]
        d = math.hypot(vx, vy)
        return c[0] + vx / d * R, c[1] + vy / d * R

    t1 = su_cerchio(ct, Rt)
    t2 = su_cerchio(cs, Rs)

    quad = []
    th0 = -math.pi / 2
    th1 = math.atan2(t1[1] - ct[1], t1[0] - ct[0])
    for i in range(41):
        th = th0 + (th1 - th0) * i / 40
        quad.append((ct[0] + Rt * math.cos(th), ct[1] + Rt * math.sin(th)))
    a1 = math.atan2(t1[1] - fy, t1[0] - fx)
    a2 = math.atan2(t2[1] - fy, t2[0] - fx)
    if a2 < a1:
        a2 += 2 * math.pi
    for i in range(1, 31):
        th = a1 + (a2 - a1) * i / 30
        quad.append((fx + r_raccordo * math.cos(th), fy + r_raccordo * math.sin(th)))
    p2 = math.atan2(t2[1] - cs[1], t2[0] - cs[0])
    for i in range(1, 61):
        ph = p2 + (0.0 - p2) * i / 60
        quad.append((cs[0] + Rs * math.cos(ph), cs[1] + Rs * math.sin(ph)))

    q1 = quad
    q2 = [(x, -y) for x, y in reversed(quad)][1:]
    q3 = [(-x, -y) for x, y in quad][1:]
    q4 = [(-x, y) for x, y in reversed(quad)][1:-1]
    pts = q1 + q2 + q3 + q4
    path = QPainterPath()
    path.moveTo(pts[0][0], pts[0][1])
    for x, y in pts[1:]:
        path.lineTo(x, y)
    path.closeSubpath()
    return path


def percorso_testo(testo, font, altezza_maiuscole, larghezza=None, condensa=1.0):
    """Testo come tracciato vettoriale centrato in (0,0).
    'larghezza': se data, la spaziatura tra le lettere viene regolata per raggiungerla.
    'condensa': fattore orizzontale (es. 0.8 = lettere piu' strette, come sul quadrante originale)."""
    f = QFont(font)
    f.setPixelSize(100)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.0)
    h = QPainterPath()
    h.addText(0, 0, f, "H")
    s = altezza_maiuscole / h.boundingRect().height()
    p = QPainterPath()
    p.addText(0, 0, f, testo)
    if larghezza and len(testo) > 1:
        extra = (larghezza / (s * condensa) - p.boundingRect().width()) / (len(testo) - 1)
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, extra)
        p = QPainterPath()
        p.addText(0, 0, f, testo)
    br = p.boundingRect()
    tr = QTransform()
    tr.scale(s * condensa, s)
    tr.translate(-(br.x() + br.width() / 2), -(br.y() + br.height() / 2))
    return tr.map(p)


def percorso_testo_largo(testo, font, larghezza):
    """Testo (es. corsivo) scalato in modo uniforme fino alla larghezza indicata."""
    f = QFont(font)
    f.setPixelSize(100)
    p = QPainterPath()
    p.addText(0, 0, f, testo)
    br = p.boundingRect()
    s = larghezza / br.width()
    tr = QTransform()
    tr.scale(s, s)
    tr.translate(-(br.x() + br.width() / 2), -(br.y() + br.height() / 2))
    return tr.map(p)


def percorso_testo_ad_arco(testo, font, altezza_maiuscole, raggio_centro, lunghezza_arco):
    """Testo lungo un arco concentrico al quadrante, in basso, con le lettere rivolte al centro."""
    f = QFont(font)
    f.setPixelSize(100)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.0)
    h = QPainterPath()
    h.addText(0, 0, f, "H")
    s = altezza_maiuscole / h.boundingRect().height()
    fm = QFontMetricsF(f)
    adv = [fm.horizontalAdvance(c) * s for c in testo]
    extra = (lunghezza_arco - sum(adv)) / (len(testo) - 1) if len(testo) > 1 else 0.0
    r_base = raggio_centro + altezza_maiuscole / 2
    totale = sum(adv) + extra * (len(testo) - 1)
    out = QPainterPath()
    pos = 0.0
    for c, a in zip(testo, adv):
        centro = pos + a / 2
        pos += a + extra
        if c == " ":
            continue
        gp = QPainterPath()
        gp.addText(0, 0, f, c)
        tr = QTransform()
        theta = math.pi / 2 - (centro - totale / 2) / r_base
        tr.translate(r_base * math.cos(theta), r_base * math.sin(theta))
        tr.rotate(math.degrees(theta - math.pi / 2))
        tr.scale(s, s)
        tr.translate(-fm.horizontalAdvance(c) / 2, 0)
        out.addPath(tr.map(gp))
    return out


def percorso_testo_ad_arco_sopra(testo, font, altezza_maiuscole, raggio_centro, lunghezza_arco):
    """Come percorso_testo_ad_arco, ma il testo curva SOPRA il centro (in alto), diritto
    e leggibile da sinistra a destra - per le incisioni sul fondello."""
    f = QFont(font)
    f.setPixelSize(100)
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 0.0)
    h = QPainterPath()
    h.addText(0, 0, f, "H")
    s = altezza_maiuscole / h.boundingRect().height()
    fm = QFontMetricsF(f)
    adv = [fm.horizontalAdvance(c) * s for c in testo]
    extra = (lunghezza_arco - sum(adv)) / (len(testo) - 1) if len(testo) > 1 else 0.0
    r_base = raggio_centro + altezza_maiuscole / 2
    totale = sum(adv) + extra * (len(testo) - 1)
    out = QPainterPath()
    pos = 0.0
    for c, a in zip(testo, adv):
        centro = pos + a / 2
        pos += a + extra
        if c == " ":
            continue
        gp = QPainterPath()
        gp.addText(0, 0, f, c)
        tr = QTransform()
        theta = -math.pi / 2 + (centro - totale / 2) / r_base
        tr.translate(r_base * math.cos(theta), r_base * math.sin(theta))
        tr.rotate(math.degrees(theta + math.pi / 2))
        tr.scale(s, s)
        tr.translate(-fm.horizontalAdvance(c) / 2, 0)
        out.addPath(tr.map(gp))
    return out


def crea_stella(punte=4, r_int=0.38):
    """Stella a 'punte' punte di raggio 1 (per le scintille del premio)."""
    path = QPainterPath()
    for i in range(punte * 2):
        r = 1.0 if i % 2 == 0 else r_int
        a = math.pi * i / punte - math.pi / 2
        q = QPointF(r * math.cos(a), r * math.sin(a))
        path.moveTo(q) if i == 0 else path.lineTo(q)
    path.closeSubpath()
    return path


# ============================================================
# SUONI (sintetizzati: nessun file esterno)
# ============================================================
SR = 22050


def _tono(freq, dur, vol=0.5, decad=0.0, arm=(1.0, 0.25)):
    n = int(SR * dur)
    somma = sum(arm)
    out = []
    for i in range(n):
        t = i / SR
        env = min(1.0, i / (0.004 * SR)) * min(1.0, (n - i) / (0.006 * SR)) * math.exp(-decad * t)
        v = 0.0
        for k, a in enumerate(arm):
            v += a * math.sin(2 * math.pi * freq * (k + 1) * t)
        out.append(vol * env * v / somma)
    return out


def _silenzio(dur):
    return [0.0] * int(SR * dur)


def _mix(*tracce):
    n = max(len(t) for t in tracce)
    out = [0.0] * n
    for t in tracce:
        for i, v in enumerate(t):
            out[i] += v
    return out


def _scrivi_wav(percorso, campioni):
    with wave.open(percorso, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, c)) * 32767)) for c in campioni))


def genera_allarme(percorso):
    """Trillo a toni alternati, lungo ALLARME_DURATA_S secondi."""
    a = _tono(2093, 0.055, 0.55)
    b = _tono(1760, 0.055, 0.55)
    ciclo = []
    for k in range(8):
        ciclo += (a if k % 2 == 0 else b)
    ciclo += _silenzio(0.32)
    tot = int(SR * ALLARME_DURATA_S)
    camp = []
    while len(camp) < tot:
        camp += ciclo
    camp = camp[:tot]
    fade = int(SR * 0.05)
    for i in range(fade):
        camp[-1 - i] *= i / fade
    _scrivi_wav(percorso, camp)


def genera_click(percorso):
    _scrivi_wav(percorso, _tono(1500, 0.035, 0.6, decad=70, arm=(1.0, 0.6)))


def genera_sblocco(percorso):
    _scrivi_wav(percorso, _tono(1000, 0.04, 0.6, decad=60, arm=(1.0, 0.6)) + _silenzio(0.11) +
                _tono(1500, 0.05, 0.6, decad=60, arm=(1.0, 0.6)))


def genera_svita(percorso):
    """Una manciata di piccoli clic discendenti, come una ghiera filettata che gira."""
    camp = []
    for f in (1400, 1200, 1000, 850, 720):
        camp += _tono(f, 0.045, 0.5, decad=55, arm=(1.0, 0.5))
        camp += _silenzio(0.045)
    _scrivi_wav(percorso, camp)


def genera_fanfara(percorso):
    camp = []
    for f in (523.25, 659.25, 783.99, 1046.5):
        camp += _tono(f, 0.14, 0.5, decad=3.0)
    camp += _mix(_tono(1046.5, 1.8, 0.5, 1.8), _tono(1318.5, 1.8, 0.45, 1.8),
                 _tono(1568.0, 1.8, 0.4, 1.8), _tono(523.25, 1.8, 0.35, 1.5))
    _scrivi_wav(percorso, camp)


# ============================================================
# WIDGET
# ============================================================
class VostokWidget(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(*DIM_INIZIALE)

        # Preferenze modificabili a caldo dalla finestra di impostazioni (di default, i valori
        # scelti in cima al file); _carica_stato(), subito sotto, le puo' sovrascrivere con
        # quelle salvate l'ultima volta, se RICORDA_POSIZIONE e' attivo
        self.dial_preset = DIAL_PRESET
        self.bezel_material = BEZEL_MATERIAL
        self.bezel_ceramic_color = BEZEL_CERAMIC_COLOR
        self.caseback_dedica = CASEBACK_DEDICA
        self.caseback_numero_serie = CASEBACK_NUMERO_SERIE
        self.crown_su_cambia = CROWN_SU_CAMBIA
        self._dlg_impostazioni = None

        if RICORDA_POSIZIONE:
            self._carica_stato()

        # Stato ghiera / allarme
        self.drag_position = QPoint()
        self.bezel_rotation = 0            # gradi, in senso orario, 0 = puntino a ore 12
        self.dragging_bezel = False
        self._bezel_ang_prec = 0.0
        self._bezel_accum = 0.0
        self._ee_passi_acc = 0             # scatti (con segno) dall'ultima valutazione
        self._minuto_fino = 0.0            # fino a quando mostrare il minuto sotto il puntino
        self._cache_minuti = {}
        self._ee_tenuta_t0 = 0.0
        self.alarm_armed = False           # si arma quando l'utente muove la ghiera
        self._allarme_fine = 0.0
        self._prev_min_angle = None
        self._shake_fino = 0.0
        self._shake_origin = None
        self._shake_amp = 5.0
        self._procs = {}                   # riproduzioni audio in corso

        # Stato easter egg
        self._ccw_sbloccato = not GHIERA_SOLO_ORARIO
        self._ee_progresso = 0
        self._ee_ultimo = 0.0
        self._ee_bagliore_fino = 0.0
        self._premio_t0 = None
        self._premio_ultimo = 0.0
        self._particelle = []
        self._emissione = 0.0

        # Corona (0 = normale, 1 = correzione giorno/data, 2 = regolazione ore/minuti)
        self.crown_pos = 0
        self._crown_freeze_dt = None
        self._time_offset_ms = 0      # scarto (in ms) tra l'ora mostrata e quella di sistema
        self._date_offset = 0
        self._day_offset = 0
        self._crown_hint_fino = 0.0

        # Fronte / retro e fondello
        self._flip_t = 0.0
        self._flip_target = 0.0
        self._svita_t = 0.0
        self._svita_target = 0.0
        self._rotore_ang = 0.0
        self._bilanciere_ang = 0.0
        self._rotore_vel = 0.0              # velocita' angolare del rotore (gradi/s), decade da sola
        self._carica = 0.0                  # secondi di carica residua: finche' >0 il bilanciere batte
        self._ingranaggio_ang = 0.0         # un piccolo ingranaggio decorativo che gira mentre c'e' carica
        self._pm_retro = None
        self._key_retro = None

        # Palette (quadrante dal catalogo + metallo di indici/lancette/anello)
        preset = DIALS[self.dial_preset]
        metallo = METALLI[preset["metal"]]
        self.pal = dict(metallo)
        self.pal["dial"] = preset["dial"]
        self.pal["accent"] = preset["accent"]

        self.ang_sec = self.ang_min = self.ang_hour = 0.0

        # Font
        self._carica_font()

        # Forme fisse
        self.case_path = crea_percorso_tonneau()
        self._stella = crea_stella()
        self._crea_lancette()
        self._crea_grana_acciaio()
        self._tp_poehali = percorso_testo_largo("Поехали!", self._font_corsivo(), 96)

        # Cache dei livelli statici
        self._pm_base = None
        self._key_base = None
        self._pm_bezel = None
        self._key_bezel = None

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(TIMER_MS)

        self.shake_timer = QTimer(self)
        self.shake_timer.timeout.connect(self._shake_step)

        self._ee_timer = QTimer(self)
        self._ee_timer.setSingleShot(True)
        self._ee_timer.timeout.connect(self._ee_sblocca_antiorario)

        self._ee_sosta = QTimer(self)
        self._ee_sosta.setSingleShot(True)
        self._ee_sosta.timeout.connect(self._ee_valuta_sosta)

    # --------------------------------------------------------
    # Font
    # --------------------------------------------------------
    def _carica_font(self):
        self.fam_corsivo = None
        self.corsivo_italic = False
        for percorso_font in FILE_FONT_CORSIVO:
            if os.path.exists(percorso_font):
                fid = QFontDatabase.addApplicationFont(percorso_font)
                if fid >= 0:
                    fams = QFontDatabase.applicationFontFamilies(fid)
                    if fams:
                        self.fam_corsivo = fams[0]
                        break
        tutte = set(QFontDatabase.families())
        if not self.fam_corsivo:
            for c in ("Marck Script", "Bad Script", "Z003", "URW Chancery L"):
                if c in tutte:
                    self.fam_corsivo = c
                    break
            else:
                self.fam_corsivo = "DejaVu Serif"
                self.corsivo_italic = True
        self.fam_sans = next((c for c in ("Liberation Sans", "Arimo", "Arial", "Helvetica", "DejaVu Sans")
                              if c in tutte), "sans-serif")

    def _font_sans(self, bold=True):
        f = QFont(self.fam_sans)
        f.setBold(bold)
        return f

    def _font_corsivo(self):
        f = QFont(self.fam_corsivo)
        f.setItalic(self.corsivo_italic)
        return f

    # --------------------------------------------------------
    # Tempo, lancette e allarme
    # --------------------------------------------------------
    def _now(self):
        """L'orario mostrato dalle lancette. In posizione 2 la corona 'ferma' il tempo
        (come la carica a manovella nei meccanici veri, hacking dei secondi); altrove
        segue l'orologio di sistema con l'eventuale scarto impostato a mano."""
        if self.crown_pos == 2 and self._crown_freeze_dt is not None:
            return self._crown_freeze_dt
        return QDateTime.currentDateTime().addMSecs(self._time_offset_ms)

    def _tick(self):
        t = self._now().time()
        sec = t.second() + t.msec() / 1000.0
        self.ang_sec = sec * 6.0
        self.ang_min = (t.minute() + sec / 60.0) * 6.0
        self.ang_hour = ((t.hour() % 12) + t.minute() / 60.0 + sec / 3600.0) * 30.0
        self._check_alarm(self.ang_min)
        self._aggiorna_premio()

        # Animazioni fronte/retro (gira l'orologio, svita il fondello)
        self._flip_t += max(-0.09, min(0.09, self._flip_target - self._flip_t))
        if abs(self._flip_t - self._flip_target) < 0.01:
            self._flip_t = self._flip_target
        self._svita_t += max(-0.05, min(0.05, self._svita_target - self._svita_t))
        if abs(self._svita_t - self._svita_target) < 0.01:
            self._svita_t = self._svita_target

        # Meccanismo: il rotore gira per inerzia dopo una scossa e rallenta da solo;
        # finche' c'e' carica residua il bilanciere batte (altrimenti resta fermo)
        dt = TIMER_MS / 1000.0
        self._rotore_ang = (self._rotore_ang + self._rotore_vel * dt) % 360.0
        self._rotore_vel *= ROTORE_ATTRITO
        if self._carica > 0.0:
            self._carica = max(0.0, self._carica - dt)
            ampiezza = 22.0 * min(1.0, self._carica)      # si spegne dolcemente nell'ultimo secondo
            self._bilanciere_ang = ampiezza * math.sin(time.monotonic() * 2 * math.pi * BILANCIERE_HZ)
            self._ingranaggio_ang = (self._ingranaggio_ang + 90.0 * dt) % 360.0
        else:
            self._bilanciere_ang = 0.0

        self.update()

    def _check_alarm(self, min_angle):
        """
        Scatta quando la lancetta dei minuti ATTRAVERSA il puntino nero della ghiera.
        Il puntino, ruotando la ghiera di N gradi in senso orario, sta a N gradi dal 12
        (stessa scala della lancetta dei minuti). Si confronta la posizione precedente
        e quella attuale della lancetta, cosi' non si perde mai il passaggio.
        """
        prec = self._prev_min_angle
        self._prev_min_angle = min_angle
        if prec is None or not self.alarm_armed:
            return
        mossa = (min_angle - prec) % 360.0
        if mossa == 0.0 or mossa > 180.0:      # fermo, oppure salto dell'orologio di sistema
            return
        verso_puntino = (self.bezel_rotation - prec) % 360.0
        if 0.0 < verso_puntino <= mossa:
            if self.dragging_bezel or self._ee_progresso > 0:   # non disturbare i gesti sulla ghiera
                self.alarm_armed = False
                return
            if not ALLARME_RIPETI_OGNI_ORA:
                self.alarm_armed = False
            self.trigger_alarm()

    def _allarme_attivo(self):
        return time.monotonic() < self._allarme_fine

    def trigger_alarm(self):
        self._allarme_fine = time.monotonic() + ALLARME_DURATA_S
        if ALLARME_TREMOLIO:
            self._avvia_vibrazione(ALLARME_DURATA_S, 5.0)
        if ALLARME_SUONO:
            self._riproduci("allarme_%ds" % int(ALLARME_DURATA_S), genera_allarme)

    def _ferma_allarme(self):
        self._allarme_fine = 0.0
        self._shake_fino = 0.0
        self._ferma_audio("allarme_%ds" % int(ALLARME_DURATA_S))
        self._shake_step()

    # --- vibrazione ---
    def _avvia_vibrazione(self, durata, ampiezza):
        if self._shake_origin is None:
            self._shake_origin = self.pos()
        self._shake_fino = max(self._shake_fino, time.monotonic() + durata)
        self._shake_amp = ampiezza
        if not self.shake_timer.isActive():
            self.shake_timer.start(24)

    def _shake_step(self):
        if time.monotonic() >= self._shake_fino or self._shake_origin is None:
            self.shake_timer.stop()
            if self._shake_origin is not None:
                self.move(self._shake_origin)
            self._shake_origin = None
            return
        a = self._shake_amp
        dx = int(random.uniform(-a, a))
        dy = int(random.uniform(-a, a) * 0.6)
        self.move(self._shake_origin + QPoint(dx, dy))

    # --- audio ---
    def _riproduci(self, nome, generatore):
        def lavoro():
            percorso = os.path.join(tempfile.gettempdir(), "vostok_widget_%s.wav" % nome)
            if not os.path.exists(percorso):
                try:
                    generatore(percorso)
                except OSError as e:
                    print("Vostok: impossibile creare il file audio:", e, file=sys.stderr)
                    return

            if sys.platform.startswith("win"):
                try:
                    import winsound
                    winsound.PlaySound(percorso, winsound.SND_FILENAME | winsound.SND_ASYNC)
                    return
                except Exception as e:
                    print("Vostok: impossibile riprodurre l'audio con winsound:", e, file=sys.stderr)
                    return

            lettori = (["paplay", percorso], ["pw-play", percorso], ["aplay", "-q", percorso],
                       ["play", "-q", percorso],
                       ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", percorso])
            for cmd in lettori:
                if shutil.which(cmd[0]) is None:
                    continue
                try:
                    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    continue
                self._procs[nome] = proc
                rc = proc.wait()
                if rc == 0 or self._procs.get(nome) is not proc:   # finito, oppure fermato apposta
                    self._procs.pop(nome, None)
                    return
            print("Vostok: nessun lettore audio funzionante (provati paplay, pw-play, aplay, play, ffplay)",
                  file=sys.stderr)
            sys.stdout.write("\a")
            sys.stdout.flush()

        threading.Thread(target=lavoro, daemon=True).start()

    def _ferma_audio(self, nome):
        if sys.platform.startswith("win"):
            try:
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)      # ferma qualsiasi suono winsound in corso
            except Exception:
                pass
            return
        proc = self._procs.pop(nome, None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    # --------------------------------------------------------
    # Easter egg
    # --------------------------------------------------------
    def _ee_log(self, testo):
        if EE_DEBUG:
            print("[EE]", testo, file=sys.stderr)

    def _ee_controlla_tenuta(self):
        """Il puntino a ore 4 tenuto fermo a mouse premuto sblocca la rotazione antioraria."""
        if not EASTER_EGG or self._ccw_sbloccato:
            return
        if self.bezel_rotation == EE_MINUTO_SBLOCCO * 6:
            if not self._ee_timer.isActive():
                self._ee_tenuta_t0 = time.monotonic()
                self._ee_timer.start(EE_TENUTA_MS)
                self._ee_log("puntino a ore 4: tienilo fermo %.1f s" % (EE_TENUTA_MS / 1000.0))
        else:
            self._ee_timer.stop()

    def _ee_sblocca_antiorario(self):
        if self.dragging_bezel and self.bezel_rotation == EE_MINUTO_SBLOCCO * 6 and not self._ccw_sbloccato:
            self._ccw_sbloccato = True
            self._ee_progresso = 0
            self._ee_passi_acc = 0
            self._ee_ultimo = time.monotonic()
            self._bezel_accum = 0.0
            self._ee_bagliore_fino = time.monotonic() + 0.9
            self._riproduci("sblocco", genera_sblocco)
            self._ee_log("SBLOCCATA la rotazione antioraria")

    def _ee_registra_passi(self, scatti):
        """Ogni scatto della ghiera rimette in moto l'attesa: il passo viene valutato quando resta ferma."""
        if not EASTER_EGG or not self._ccw_sbloccato:
            return
        self._ee_passi_acc += scatti
        self._ee_sosta.start(EE_SOSTA_MS)

    def _ee_valuta_sosta(self):
        """La ghiera e' ferma da EE_SOSTA_MS: controlla dove e' arrivata e in che verso."""
        passi = self._ee_passi_acc
        self._ee_passi_acc = 0
        if not EASTER_EGG or not self._ccw_sbloccato or passi == 0:
            return
        ora = time.monotonic()
        if ora - self._ee_ultimo > EE_TIMEOUT_S:
            self._ee_progresso = 0
            self._ee_log("tempo scaduto: la combinazione riparte da zero")
        self._ee_ultimo = ora
        verso = 1 if passi > 0 else -1
        minuto = self.bezel_rotation / 6.0

        def corretto(i):
            m, v = EE_COMBINAZIONE[i]
            return abs(minuto - m) < 1e-6 and verso == v

        att_m, att_v = EE_COMBINAZIONE[self._ee_progresso]
        if corretto(self._ee_progresso):
            self._ee_progresso += 1
            esito = "GIUSTO"
        elif corretto(0):
            self._ee_progresso = 1                  # il movimento sbagliato puo' essere un nuovo inizio
            esito = "sbagliato, ma vale come primo passo"
        else:
            self._ee_progresso = 0
            esito = "sbagliato: si riparte da zero"
        self._ee_log("arrivato al minuto %g, verso %s (%+d scatti) | atteso: minuto %d, verso %s -> %s"
                     % (minuto, "orario" if verso > 0 else "antiorario", passi, att_m,
                        "orario" if att_v > 0 else "antiorario", esito))
        if self._ee_progresso >= len(EE_COMBINAZIONE):
            self._ee_progresso = 0
            self._premio_avvia()
        elif self._ee_progresso > 0:
            self._riproduci("click", genera_click)

    def _premio_avvia(self):
        self._premio_t0 = time.monotonic()
        self._premio_ultimo = self._premio_t0
        self._particelle = []
        self._emissione = 0.0
        self._emetti_particelle(80)
        self._riproduci("fanfara", genera_fanfara)

    def _emetti_particelle(self, n):
        colori = [(255, 226, 120), (255, 246, 200), (255, 192, 64), (232, 64, 52)]
        for _ in range(n):
            ang = random.uniform(0, 2 * math.pi)
            vel = random.uniform(80, 280)
            self._particelle.append({
                "x": random.uniform(-8, 8), "y": random.uniform(-8, 8),
                "vx": vel * math.cos(ang), "vy": vel * math.sin(ang) - 70.0,
                "rot": random.uniform(0, 360), "vr": random.uniform(-260, 260),
                "s": random.uniform(4.0, 10.0), "ttl": random.uniform(2.4, 4.6), "eta": 0.0,
                "col": random.choice(colori)})

    def _aggiorna_premio(self):
        if self._premio_t0 is None:
            return
        ora = time.monotonic()
        dt = min(ora - self._premio_ultimo, 0.1)
        self._premio_ultimo = ora
        t = ora - self._premio_t0
        if t >= PREMIO_DURATA_S:
            self._premio_t0 = None
            self._particelle = []
            return
        if t < 2.5:
            self._emissione += 26.0 * dt
            n = int(self._emissione)
            if n:
                self._emissione -= n
                self._emetti_particelle(n)
        vivi = []
        for q in self._particelle:
            q["eta"] += dt
            if q["eta"] >= q["ttl"]:
                continue
            q["vy"] += 95.0 * dt
            q["vx"] *= (1.0 - 0.5 * dt)
            q["x"] += q["vx"] * dt
            q["y"] += q["vy"] * dt
            q["rot"] += q["vr"] * dt
            vivi.append(q)
        self._particelle = vivi

    def _premio_env(self, t):
        if t < 0.6:
            return t / 0.6
        if t > PREMIO_DURATA_S - 1.5:
            return max(0.0, (PREMIO_DURATA_S - t) / 1.5)
        return 1.0

    # --------------------------------------------------------
    # Lancette (forme in unita', puntate verso le 12; x = larghezza, y = -lunghezza)
    # --------------------------------------------------------
    @staticmethod
    def _poligono(punti):
        path = QPainterPath()
        vw = [QPointF(w, -v) for v, w in punti]
        path.moveTo(vw[0])
        for q in vw[1:]:
            path.lineTo(q)
        path.closeSubpath()
        return path

    def _crea_lancette(self):
        pol = self._poligono
        # Lancetta minuti: spada
        self.h_min = pol([(-16, -3.6), (2, -5.4), (98, -4.7), (115, 0), (98, 4.7), (2, 5.4), (-16, 3.6)])
        self.h_min_lume = pol([(12, -1.9), (98, -1.9), (107, 0), (98, 1.9), (12, 1.9)])
        # Lancetta ore: freccia
        self.h_ore = pol([(-16, -4.4), (2, -5.2), (47, -4.6), (44.5, -12.6), (81, 0),
                          (44.5, 12.6), (47, 4.6), (2, 5.2), (-16, 4.4)])
        self.h_ore_lume_asta = pol([(10, -1.7), (40, -1.7), (40, 1.7), (10, 1.7)])
        self.h_ore_lume_punta = pol([(51, -7.2), (70, 0), (51, 7.2)])

    def _crea_grana_acciaio(self):
        """Satinatura dell'acciaio: tante strisce orizzontali sottili, sempre uguali."""
        rng = random.Random(7)
        self._grana = []
        for _ in range(1100):
            y = rng.uniform(-240, 240)
            x0 = rng.uniform(-210, 60)
            x1 = x0 + rng.uniform(40, 260)
            chiaro = rng.random() < 0.55
            a = rng.randint(8, 26)
            self._grana.append((y, x0, x1, chiaro, a))

    # --------------------------------------------------------
    # Pittura
    # --------------------------------------------------------
    def paintEvent(self, event):
        w, h = self.width(), self.height()
        scale = min(w, h) / 500.0
        dpr = self.devicePixelRatioF()
        self._assicura_cache(w, h, scale, dpr)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        t = self._flip_t
        if t <= 0.001:
            self._disegna_faccia(p, "front", w, h, scale)
        elif t >= 0.999:
            self._disegna_faccia(p, "back", w, h, scale)
        else:
            # In transizione: dissolvenza incrociata fronte -> retro (o viceversa)
            p.setOpacity(1.0 - t)
            self._disegna_faccia(p, "front", w, h, scale)
            p.setOpacity(t)
            self._disegna_faccia(p, "back", w, h, scale)
            p.setOpacity(1.0)

        p.save()
        p.translate(w / 2.0, h / 2.0)
        p.scale(scale, scale)
        self._disegna_icone(p)
        p.restore()

    def _disegna_faccia(self, p, faccia, w, h, scale):
        """Disegna un lato dell'orologio: il livello statico in pixel (cache), poi il
        contenuto dinamico di quel lato (lancette e effetti sul fronte, meccanismo e
        fondello sul retro)."""
        if faccia == "front":
            p.drawPixmap(0, 0, self._pm_base)
            p.drawPixmap(0, 0, self._pm_bezel)
        else:
            p.drawPixmap(0, 0, self._pm_retro)

        p.save()
        p.translate(w / 2.0, h / 2.0)
        p.scale(scale, scale)
        ora = time.monotonic()

        if faccia == "front":
            # Lampeggio dell'allarme
            resto = self._allarme_fine - ora
            if resto > 0 and int(resto / 0.25) % 2 == 0:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(255, 40, 40, 80))
                p.drawPath(self.case_path)

            # Bagliore dell'easter egg (sblocco)
            if ora < self._ee_bagliore_fino:
                k = (self._ee_bagliore_fino - ora) / 0.9
                self._anello(p, R_GHIERA[0], R_ORLO[1], QColor(255, 214, 110, int(150 * k)))

            # Premio: lume "acceso" sugli indici
            t_premio = None
            env = 0.0
            if self._premio_t0 is not None:
                t_premio = ora - self._premio_t0
                env = self._premio_env(t_premio)
                self._disegna_bagliore(p, env, t_premio)

            self._disegna_lancette(p, env)

            if t_premio is not None:
                self._disegna_premio(p, t_premio, env)

            # Tenuta a ore 4: un alone dorato cresce fino allo sblocco
            if self._ee_timer.isActive() and not self._ccw_sbloccato:
                k = min(1.0, (ora - self._ee_tenuta_t0) / (EE_TENUTA_MS / 1000.0))
                self._anello(p, R_GHIERA[0], R_ORLO[1], QColor(255, 214, 110, int(110 * k * k)))

            if GHIERA_MOSTRA_MINUTO and ora < self._minuto_fino:
                self._disegna_minuto(p)

            if self.crown_pos > 0 and ora < self._crown_hint_fino:
                self._disegna_corona_hint(p)
        else:
            self._disegna_retro_dinamico(p, ora)

        p.restore()

    def _nuovo_livello(self, w, h, scale, dpr):
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.translate(w / 2.0, h / 2.0)
        p.scale(scale, scale)
        return pm, p

    def _assicura_cache(self, w, h, scale, dpr):
        # La data e' nella chiave: allo scoccare della mezzanotte il livello si ridisegna da solo.
        # Corona, correzioni di giorno/data e quadrante ci sono anch'esse, perche' cambiano la
        # finestrella, il disegno della corona e i colori del quadrante stesso.
        kb = (w, h, dpr, self._now().date().toJulianDay(), self.crown_pos,
              self._date_offset, self._day_offset, self.dial_preset)
        if kb != self._key_base:
            pm, p = self._nuovo_livello(w, h, scale, dpr)
            self._render_base(p)
            p.end()
            self._pm_base, self._key_base = pm, kb
        kz = (w, h, dpr, self.bezel_rotation, self.bezel_material, self.bezel_ceramic_color)
        if kz != self._key_bezel:
            pm, p = self._nuovo_livello(w, h, scale, dpr)
            self._render_ghiera(p, self.bezel_rotation)
            p.end()
            self._pm_bezel, self._key_bezel = pm, kz
        kr = (w, h, dpr, self.crown_pos, self.dial_preset)
        if kr != self._key_retro:
            pm, p = self._nuovo_livello(w, h, scale, dpr)
            self._render_retro(p)
            p.end()
            self._pm_retro, self._key_retro = pm, kr

    # ---------- utilita' di disegno ----------
    @staticmethod
    def _anello(p, r_in, r_out, brush):
        path = QPainterPath()
        path.addEllipse(QPointF(0, 0), r_out, r_out)
        path.addEllipse(QPointF(0, 0), r_in, r_in)
        path.setFillRule(Qt.FillRule.OddEvenFill)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(brush)
        p.drawPath(path)

    @staticmethod
    def _cerchio(p, cx, cy, r, brush, pen=None):
        p.setPen(pen if pen is not None else Qt.PenStyle.NoPen)
        p.setBrush(brush)
        p.drawEllipse(QPointF(cx, cy), r, r)

    # ---------- livello 1: cassa + quadrante ----------
    def _render_base(self, p):
        self._disegna_corona(p)
        self._disegna_cassa(p)
        self._disegna_pozzetto(p)
        self._disegna_anelli(p)
        self._disegna_quadrante(p)

    def _disegna_corona(self, p):
        x0, x1, half = self._corona_rect()
        p.setPen(QPen(QColor(70, 74, 82), 1.4))
        p.setBrush(QBrush(grad_lineare(0, -half, 0, half, ACCIAIO_CILINDRO)))
        p.drawRoundedRect(QRectF(x0, -half, x1 - x0, 2 * half), 5, 5)
        p.setPen(QPen(QColor(50, 54, 62, 150), 0.9))
        y = -half + 4
        while y < half - 3:
            p.drawLine(QLineF(x0 + 8, y, x1 - 2, y))
            y += 4.2
        if self.crown_pos > 0:
            colore = QColor(214, 168, 60) if self.crown_pos == 1 else QColor(198, 62, 52)
            p.setPen(QPen(colore, 2.0))
            p.drawLine(QLineF(x1 - 3.0, -half + 3, x1 - 3.0, half - 3))

    def _corona_rect(self, pos=None):
        """Rettangolo (x0, x1, meta' altezza) della corona nella posizione data,
        in unita' base: piu' e' estratta, piu' x1 si allontana dalla cassa."""
        pos = self.crown_pos if pos is None else pos
        return 186.0, 219.0 + 11.0 * pos, 30.0

    def _in_corona(self, dx, dy):
        x0, x1, half = self._corona_rect()
        return x0 <= dx <= x1 and -half <= dy <= half

    def _disegna_cassa(self, p):
        path = self.case_path
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(grad_lineare(-200, -236, 200, 236, ACCIAIO_CASSA)))
        p.drawPath(path)

        # Satinatura
        p.save()
        p.setClipPath(path)
        for y, x0, x1, chiaro, a in self._grana:
            p.setPen(QPen(QColor(255, 255, 255, a) if chiaro else QColor(40, 44, 52, a), 0.6))
            p.drawLine(QLineF(x0, y, x1, y))
        # Riflesso diagonale morbido
        rif = QLinearGradient(-200, -236, 200, 236)
        rif.setColorAt(0.00, QColor(255, 255, 255, 0))
        rif.setColorAt(0.30, QColor(255, 255, 255, 0))
        rif.setColorAt(0.40, QColor(255, 255, 255, 58))
        rif.setColorAt(0.50, QColor(255, 255, 255, 0))
        rif.setColorAt(1.00, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(-200, -240, 400, 480), QBrush(rif))
        p.restore()

        # Smusso lucido: bordo con luce in alto a sinistra e ombra in basso a destra
        gb = QLinearGradient(-195, -236, 195, 236)
        gb.setColorAt(0.0, QColor(255, 255, 255, 250))
        gb.setColorAt(0.45, QColor(168, 173, 182, 210))
        gb.setColorAt(1.0, QColor(58, 62, 70, 255))
        pen = QPen(QBrush(gb), 3.6)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        interno = QTransform().scale(0.955, 0.955).map(path)
        p.setPen(QPen(QColor(255, 255, 255, 150), 1.2))
        p.drawPath(interno)
        interno2 = QTransform().scale(0.94, 0.94).map(path)
        p.setPen(QPen(QColor(50, 54, 62, 90), 0.9))
        p.drawPath(interno2)

    def _disegna_pozzetto(self, p):
        # Pozzetto scuro attorno alla ghiera (solo sul fronte, dove la ghiera e' incassata)
        self._anello(p, 176.0, 186.0, QColor(36, 39, 46, 225))
        self._anello(p, 186.0, 189.0, QColor(30, 33, 40, 60))

    def _disegna_anelli(self, p):
        # Anello in acciaio lucido
        self._anello(p, *R_ACCIAIO, QBrush(grad_conico(100, ACCIAIO_ANELLO)))
        p.setPen(QPen(QColor(60, 64, 72, 220), 0.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), R_ACCIAIO[0], R_ACCIAIO[0])
        p.setPen(QPen(QColor(255, 255, 255, 120), 0.7))
        p.drawEllipse(QPointF(0, 0), R_ACCIAIO[1] - 0.6, R_ACCIAIO[1] - 0.6)

        # Anello attorno al quadrante: oro o acciaio secondo il quadrante scelto (self.pal)
        self._anello(p, *R_ORO, QBrush(grad_conico(60, self.pal["anello"])))
        p.setPen(QPen(QColor(*self.pal["anello_pen"], 200), 0.8))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), R_ORO[0], R_ORO[0])

    def _disegna_quadrante(self, p):
        r = R_QUADRANTE
        vicino, lontano = self.pal["dial"]
        g = QRadialGradient(QPointF(-25, -30), 190)
        g.setColorAt(0.0, QColor(*vicino))
        g.setColorAt(1.0, QColor(*lontano))
        self._cerchio(p, 0, 0, r, QBrush(g))

        # Riflessi sul vetro
        p.save()
        clip = QPainterPath()
        clip.addEllipse(QPointF(0, 0), r, r)
        p.setClipPath(clip)
        sg = QLinearGradient(-r, -r, r * 0.6, r * 0.6)
        sg.setColorAt(0.0, QColor(255, 255, 255, 26))
        sg.setColorAt(0.42, QColor(255, 255, 255, 0))
        p.fillRect(QRectF(-r, -r, 2 * r, 2 * r), QBrush(sg))
        interno = QPainterPath()
        interno.addEllipse(QPointF(11, 15), r, r)
        mezzaluna = clip.subtracted(interno)
        cg = QLinearGradient(-r, -r, 0, 0)
        cg.setColorAt(0.0, QColor(255, 255, 255, 46))
        cg.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(cg))
        p.drawPath(mezzaluna)
        p.restore()

        # Tacche dei minuti
        p.setPen(QPen(QColor(*self.pal["accent"]), 1.25, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        for i in range(60):
            if i % 5 == 0:
                continue
            p.save()
            p.rotate(i * 6)
            p.drawLine(QLineF(0, -127.5, 0, -108.5))
            p.restore()

        # Indici e puntini luminescenti
        for i in range(12):
            if i == 3:           # a ore 3 c'e' la finestrella della data
                continue
            self._disegna_indice(p, i * 30, spesso=(i == 0))
            self._disegna_puntino(p, i * 30)

        # Scritte
        self._disegna_scritte(p)
        self._disegna_data(p)

    def _disegna_indice(self, p, angolo, spesso=False):
        r_in, r_out = 90.0, 125.0
        hw = 8.8 if spesso else 6.2
        p.save()
        p.rotate(angolo)
        p.setPen(QPen(QColor(*self.pal["pen_scuro"]), 0.9))
        p.setBrush(QBrush(grad_lineare(-hw, 0, hw, 0, self.pal["lama"])))      # sfumatura in larghezza
        p.drawRoundedRect(QRectF(-hw, -r_out, 2 * hw, r_out - r_in), 2.4, 2.4)

        # Riflesso: striscia di luce lungo l'asse dell'indice (verticale su 12 e 6)
        lung = QLinearGradient(0, -r_out, 0, -r_in)
        lung.setColorAt(0.0, QColor(255, 252, 226, 0))
        lung.setColorAt(0.14, QColor(255, 252, 226, 205))
        lung.setColorAt(0.55, QColor(255, 252, 226, 240))
        lung.setColorAt(0.86, QColor(255, 252, 226, 190))
        lung.setColorAt(1.0, QColor(255, 252, 226, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(lung))
        p.drawRoundedRect(QRectF(-hw * 0.60, -r_out + 2.2, hw * 0.34, r_out - r_in - 4.4), 1.3, 1.3)
        lung2 = QLinearGradient(0, -r_out, 0, -r_in)
        lung2.setColorAt(0.0, QColor(255, 244, 200, 0))
        lung2.setColorAt(0.3, QColor(255, 244, 200, 90))
        lung2.setColorAt(0.8, QColor(255, 244, 200, 70))
        lung2.setColorAt(1.0, QColor(255, 244, 200, 0))
        p.setBrush(QBrush(lung2))
        p.drawRoundedRect(QRectF(hw * 0.38, -r_out + 3, hw * 0.16, r_out - r_in - 6), 0.8, 0.8)
        p.restore()

    def _disegna_puntino(self, p, angolo):
        p.save()
        p.rotate(angolo)
        g = QRadialGradient(QPointF(0, -129.5), 4.0)
        g.setColorAt(0.0, QColor(252, 249, 226))
        g.setColorAt(1.0, QColor(216, 192, 122))
        self._cerchio(p, 0, -129.5, 3.7, QBrush(g), QPen(QColor(140, 104, 28), 0.7))
        p.restore()

    def _disegna_scritte(self, p):
        accento = QColor(*self.pal["accent"])
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(accento))

        # Logo: B in un cerchio
        self._cerchio(p, 0, -70, 6.9, Qt.BrushStyle.NoBrush, QPen(accento, 1.2))
        b = percorso_testo("В", self._font_sans(True), 6.3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(accento))
        p.save()
        p.translate(0, -70)
        p.drawPath(b)
        p.restore()

        # "Амфибия" in corsivo, con sottolineatura
        amf = percorso_testo_largo("Амфибия", self._font_corsivo(), 76)
        p.save()
        p.translate(2, -47)
        p.drawPath(amf)
        p.restore()
        sott = QPainterPath()
        sott.moveTo(-4, -37.4)
        sott.lineTo(40, -38.4)
        sott.lineTo(40, -37.2)
        sott.lineTo(-4, -36.6)
        sott.closeSubpath()
        p.drawPath(sott)

        # Scritte a ore 6
        for testo, cap, larg, y in (("АВТОПОДЗАВОД", 6.8, 68, 45), ("200 М", 7.0, 27, 60)):
            tp = percorso_testo(testo, self._font_sans(True), cap, larg, condensa=0.80)
            p.save()
            p.translate(0, y)
            p.drawPath(tp)
            p.restore()

        arco = percorso_testo_ad_arco("СДЕЛАНО В РОССИИ", self._font_sans(False), 5.6, 84.0, 90.0)
        p.drawPath(arco)

    def _disegna_data(self, p):
        """Finestrelle giorno e data a ore 3. Leggono la data dello stesso orologio delle lancette,
        quindi cambiano esattamente a mezzanotte, piu' l'eventuale correzione fatta a mano con la
        corona in posizione 1 (self._day_offset / self._date_offset)."""
        oggi = self._now().date()
        giorni = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
        nome_giorno = giorni[(oggi.dayOfWeek() - 1 + self._day_offset) % 7]
        numero_data = ((oggi.day() - 1 + self._date_offset) % 31) + 1
        hh = 18.0
        if MOSTRA_GIORNO:
            finestre = [(nome_giorno, 88.0, 22.0, 8.4),
                        (str(numero_data), 110.0, 22.0, 9.2)]
        else:
            finestre = [(str(numero_data), 100.0, 32.0, 9.6)]
        for testo, x, ww, cap in finestre:
            p.setPen(QPen(QColor(150, 110, 30), 1.3))
            p.setBrush(QBrush(QColor(250, 250, 246)))
            p.drawRect(QRectF(x, -hh / 2, ww, hh))
            # finestra incassata: ombra in alto
            ombra = QLinearGradient(0, -hh / 2, 0, hh / 2)
            ombra.setColorAt(0.0, QColor(0, 0, 0, 80))
            ombra.setColorAt(0.28, QColor(0, 0, 0, 0))
            ombra.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(ombra))
            p.drawRect(QRectF(x + 0.6, -hh / 2 + 0.6, ww - 1.2, hh - 1.2))
            tp = percorso_testo(testo, self._font_sans(True), cap)
            br = tp.boundingRect()
            massimo = ww - 4.0
            if br.width() > massimo:
                f = massimo / br.width()
                tp = QTransform().scale(f, f).map(tp)
            p.save()
            p.translate(x + ww / 2, 0)
            p.setBrush(QBrush(NERO_GHIERA))
            p.drawPath(tp)
            p.restore()

    # ---------- retro: fondello e meccanismo ----------
    def _render_retro(self, p):
        """Parte statica del retro: cassa e movimento (sempre visibile, sotto il fondello)."""
        self._disegna_corona(p)
        self._disegna_cassa(p)
        self._disegna_movimento_statico(p)

    def _disegna_movimento_statico(self, p):
        r = R_ACCIAIO[0]        # raggio del vano/fondello
        g = QRadialGradient(QPointF(-20, -25), r * 1.6)
        g.setColorAt(0.0, QColor(74, 76, 82))
        g.setColorAt(1.0, QColor(26, 27, 31))
        self._cerchio(p, 0, 0, r, QBrush(g))

        # Ponte: una piastra allungata che regge le due ruote in basso a destra,
        # come nella foto di riferimento
        p.save()
        p.translate(46, 44)
        p.rotate(-28)
        ponte = QPainterPath()
        ponte.addRoundedRect(QRectF(-58, -20, 116, 40), 18, 18)
        pg = QLinearGradient(-58, -20, 58, 20)
        pg.setColorAt(0.0, QColor(200, 202, 206))
        pg.setColorAt(0.5, QColor(232, 234, 238))
        pg.setColorAt(1.0, QColor(184, 186, 190))
        p.setPen(QPen(QColor(120, 122, 128), 1.0))
        p.setBrush(QBrush(pg))
        p.drawPath(ponte)
        for vx in (-46, 46):
            self._cerchio(p, vx, 0, 4.2, QBrush(QColor(210, 212, 216)), QPen(QColor(130, 132, 138), 0.8))
            self._cerchio(p, vx, 0, 1.6, QBrush(QColor(90, 92, 98)))
        p.restore()

        # Due ruote dentate (la terza e un rocchetto), fisse: quella che "batte" col
        # bilanciere e' disegnata a parte, nel livello dinamico, cosi' puo' girare
        for cx, cy, rr, jewel in ((48, 30, 22, True), (14, 66, 12, True)):
            self._disegna_ruota(p, cx, cy, rr, 0.0, jewel)

        arco = percorso_testo_ad_arco("VOSTOK  \u00b7  CAL. 2416B  \u00b7  17 JEWELS  \u00b7  MADE IN RUSSIA",
                                      self._font_sans(False), 6.2, r - 22, 300.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(184, 186, 192))
        p.drawPath(arco)

    def _disegna_ruota(self, p, cx, cy, rr, angolo, rubino=False, denti=None):
        """Una ruota dentata dorata, opzionalmente con un rubino al centro. 'angolo' ruota
        i denti (usato per la ruota animata mentre il movimento e' carico)."""
        p.save()
        p.translate(cx, cy)
        p.rotate(angolo)
        gg = QRadialGradient(QPointF(-rr * 0.3, -rr * 0.3), rr * 1.4)
        gg.setColorAt(0.0, QColor(206, 184, 116))
        gg.setColorAt(1.0, QColor(120, 100, 54))
        p.setPen(QPen(QColor(58, 48, 22), 1.0))
        p.setBrush(QBrush(gg))
        p.drawEllipse(QPointF(0, 0), rr, rr)
        n = denti or max(8, int(rr * 0.7))
        p.setPen(QPen(QColor(58, 48, 22), 1.4))
        for i in range(n):
            a = 2 * math.pi * i / n
            p.drawLine(QLineF((rr - 3) * math.cos(a), (rr - 3) * math.sin(a),
                              (rr + 2) * math.cos(a), (rr + 2) * math.sin(a)))
        p.restore()
        if rubino:
            rg = QRadialGradient(QPointF(cx - 1.5, cy - 1.5), 5)
            rg.setColorAt(0.0, QColor(240, 90, 70))
            rg.setColorAt(1.0, QColor(148, 20, 20))
            self._cerchio(p, cx, cy, 4.2, QBrush(rg), QPen(QColor(60, 20, 15), 0.6))

    def _disegna_retro_dinamico(self, p, ora):
        """Rotore (gira per inerzia dopo una scossa), una ruota e il bilanciere (si muovono
        solo finche' c'e' carica residua), e sopra, se non e' ancora del tutto svitato, il
        fondello stesso."""
        opacita = 0.30 + 0.70 * self._svita_t
        p.save()
        p.setOpacity(opacita)

        # Ruota animata: gira solo mentre il movimento e' carico
        self._disegna_ruota(p, 82, 58, 14, self._ingranaggio_ang, rubino=True, denti=10)

        # Bilanciere: sempre visibile, ma oscilla solo mentre c'e' carica (altrimenti fermo)
        p.save()
        p.translate(-56, 50)
        p.rotate(self._bilanciere_ang)
        p.setPen(QPen(QColor(212, 216, 222), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), 17, 17)
        for a in (0, 90, 180, 270):
            th = math.radians(a)
            p.drawLine(QLineF(15 * math.cos(th), 15 * math.sin(th), 19 * math.cos(th), 19 * math.sin(th)))
        # accenno di spirale (la molla del bilanciere)
        spirale = QPainterPath()
        giri, punti = 1.6, 26
        for i in range(punti + 1):
            t = i / punti
            rr = 1.5 + t * 10.5
            a = t * giri * 2 * math.pi
            q = QPointF(rr * math.cos(a), rr * math.sin(a))
            spirale.moveTo(q) if i == 0 else spirale.lineTo(q)
        p.setPen(QPen(QColor(190, 194, 200), 0.8))
        p.drawPath(spirale)
        self._cerchio(p, 0, 0, 1.6, QBrush(QColor(220, 222, 226)))
        p.restore()

        # Rotore: gira per inerzia dopo una scossa
        p.save()
        p.rotate(self._rotore_ang)
        rotore = QPainterPath()
        rotore.moveTo(0, -6)
        rotore.arcTo(QRectF(-92, -92, 184, 184), 100, 160)
        rotore.lineTo(0, 6)
        rotore.closeSubpath()
        p.setPen(QPen(QColor(*self.pal["pen_scuro"]), 1.0))
        p.setBrush(QBrush(grad_lineare(-90, -90, 90, 90, self.pal["lama"])))
        p.drawPath(rotore)
        # piccolo medaglione inciso, decorativo (due archi concentrici, non un logo)
        p.setPen(QPen(QColor(*self.pal["pen_scuro"], 140), 1.1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(-24, -74, 48, 48), 20 * 16, 320 * 16)
        p.drawArc(QRectF(-16, -66, 32, 32), 20 * 16, 320 * 16)
        self._cerchio(p, 0, 0, 9, QBrush(grad_radiale(0, 0, 9, self.pal["perno"])),
                      QPen(QColor(*self.pal["pen_scuro"]), 0.8))
        p.restore()
        p.restore()

        if self._svita_t < 0.995:
            self._disegna_fondello_piastra(p)

    def _disegna_fondello_piastra(self, p):
        """Il fondello avvitato: gira e sfuma mentre si 'svita' (self._svita_t: 0 chiuso, 1 aperto).
        Inciso come un fondello vero: scritta ad arco sopra, nome del modello al centro,
        numero di serie sotto, scritta ad arco sotto."""
        r = R_ACCIAIO[0] + 4.0
        alpha = 1.0 - self._svita_t
        p.save()
        p.setOpacity(alpha)
        p.rotate(self._svita_t * 250.0)
        f = 1.0 - 0.12 * self._svita_t
        p.scale(f, f)

        p.setPen(QPen(QColor(60, 64, 72), 1.2))
        p.setBrush(QBrush(grad_conico(95, ACCIAIO_CASSA)))
        p.drawEllipse(QPointF(0, 0), r, r)

        p.setPen(QPen(QColor(70, 74, 82, 200), 1.0))       # ghiera filettata
        for i in range(70):
            a = 2 * math.pi * i / 70
            p.drawLine(QLineF((r - 5) * math.cos(a), (r - 5) * math.sin(a),
                              (r - 1) * math.cos(a), (r - 1) * math.sin(a)))

        inciso = QColor(64, 68, 76)
        arco_sopra = percorso_testo_ad_arco_sopra("ВОДОНЕПРОНИЦАЕМЫЙ", self._font_sans(False),
                                                   6.4, r - 36, 230.0)
        arco_sotto = percorso_testo_ad_arco("СДЕЛАНО В РОССИИ", self._font_sans(False),
                                            6.0, r - 32, 190.0)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(inciso)
        p.drawPath(arco_sopra)
        p.drawPath(arco_sotto)

        nome = percorso_testo_largo("Амфибия", self._font_corsivo(), 90)
        p.save()
        p.translate(0, -6)
        p.setBrush(inciso)
        p.drawPath(nome)
        p.restore()

        if self.caseback_numero_serie:
            numero = percorso_testo("\u2116 " + self.caseback_numero_serie, self._font_sans(False), 7.6)
            p.save()
            p.translate(0, 22)
            p.setBrush(inciso)
            p.drawPath(numero)
            p.restore()

        if self.caseback_dedica:
            self._disegna_dedica(p, self.caseback_dedica, y=-58.0)
        p.restore()

    def _disegna_dedica(self, p, testo, y=-58.0):
        larghezza = min(190.0, max(50.0, 9.0 * len(testo)))
        tp = percorso_testo_largo(testo, self._font_corsivo(), larghezza)
        br = tp.boundingRect()
        p.save()
        p.translate(-br.center().x(), y - br.center().y())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(18, 19, 22, 215))
        p.save()
        p.translate(0.8, 1.0)
        p.drawPath(tp)
        p.restore()
        p.setBrush(QColor(208, 212, 218, 235))
        p.drawPath(tp)
        p.restore()

    # ---------- livello 2: ghiera ----------
    def _orlo_dentellato(self, p, brush, rot):
        """Orlo con denti arrotondati (onda quadra smussata). I denti girano con la ghiera."""
        r_out, r_in = R_ORLO[1], R_ORLO[0]
        n, prof = GHIERA_DENTI, GHIERA_DENTI_PROFONDITA
        passi = max(720, 24 * n)
        rot_r = math.radians(rot)
        est = QPainterPath()
        for i in range(passi + 1):
            a = 2 * math.pi * i / passi
            s = math.tanh(3.0 * math.sin(n * a)) / math.tanh(3.0)
            r = r_out - prof * (1.0 - s) / 2.0
            th = a + rot_r
            q = QPointF(r * math.sin(th), -r * math.cos(th))
            est.moveTo(q) if i == 0 else est.lineTo(q)
        est.closeSubpath()
        anello = QPainterPath(est)
        anello.addEllipse(QPointF(0, 0), r_in, r_in)
        anello.setFillRule(Qt.FillRule.OddEvenFill)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(brush)
        p.drawPath(anello)
        p.setPen(QPen(QColor(96, 101, 110, 230), 0.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(est)

    def _fascia_ghiera_e_ink(self):
        """Restituisce (brush della fascia, colore della stampa) secondo self.bezel_material."""
        if self.bezel_material == "ceramic":
            tav = CERAMIC_PALETTES.get(self.bezel_ceramic_color, CERAMIC_PALETTES["black"])
            vicino, lontano = tav["base"]
            g = QRadialGradient(QPointF(-35, -45), R_GHIERA[1] * 2.1)
            g.setColorAt(0.0, QColor(*[min(255, c + 60) for c in vicino]))
            g.setColorAt(0.45, QColor(*vicino))
            g.setColorAt(1.0, QColor(*lontano))
            return QBrush(g), QColor(*tav["ink"])
        if self.bezel_material == "steel":
            return QBrush(grad_conico(70, GHIERA_ACCIAIO)), NERO_GHIERA
        # "enamel" (predefinito): ghiera bianca smaltata, come il modello 090679 di riferimento
        rg = QRadialGradient(QPointF(0, 0), R_GHIERA[1])
        a = R_GHIERA[0] / R_GHIERA[1]
        rg.setColorAt(a, QColor(214, 214, 210))
        rg.setColorAt(a + 0.035, QColor(248, 248, 244))
        rg.setColorAt(0.95, QColor(250, 250, 246))
        rg.setColorAt(1.0, QColor(222, 222, 218))
        return QBrush(rg), NERO_GHIERA

    def _render_ghiera(self, p, rot):
        # Orlo in acciaio lucido (la luce non ruota con la ghiera)
        brush_orlo = QBrush(grad_conico(110, ACCIAIO_ORLO))
        if GHIERA_DENTELLATA:
            self._orlo_dentellato(p, brush_orlo, rot)
        else:
            self._anello(p, *R_ORLO, brush_orlo)

        # Fascia della ghiera: smalto, acciaio o ceramica, secondo self.bezel_material
        fascia_brush, ink = self._fascia_ghiera_e_ink()
        self._anello(p, *R_GHIERA, fascia_brush)
        p.setPen(QPen(QColor(90, 94, 102, 220), 0.9))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(0, 0), R_GHIERA[0], R_GHIERA[0])
        p.drawEllipse(QPointF(0, 0), R_GHIERA[1], R_GHIERA[1])
        if self.bezel_material == "steel":
            # Solco scuro sui due bordi: senza, l'acciaio della ghiera si confonde con
            # quello della cassa e la ghiera sembra sparire
            p.setPen(QPen(QColor(30, 31, 35, 235), 1.6))
            p.drawEllipse(QPointF(0, 0), R_GHIERA[0] + 0.8, R_GHIERA[0] + 0.8)
            p.setPen(QPen(QColor(40, 42, 47, 210), 1.3))
            p.drawEllipse(QPointF(0, 0), R_GHIERA[1] - 0.8, R_GHIERA[1] - 0.8)

        p.save()
        p.rotate(rot)

        # Zigrinatura fine sull'orlo (solo se non e' dentellato)
        if not GHIERA_DENTELLATA:
            p.setPen(QPen(QColor(50, 54, 62, 130), 0.9))
            for i in range(60):
                p.save()
                p.rotate(i * 6)
                p.drawLine(QLineF(0, -R_ORLO[0] - 1.0, 0, -R_ORLO[1] + 0.8))
                p.restore()

        # Arco con interruzioni per il puntino (0) e i numeri (15, 30, 45)
        r = R_TRACCIA
        pen = QPen(ink, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        vuoti = {0: 7.0, 90: 9.0, 180: 9.0, 270: 9.0}
        angoli = [0, 90, 180, 270, 360]
        for a0, a1 in zip(angoli[:-1], angoli[1:]):
            g0 = vuoti[a0 % 360]
            g1 = vuoti[a1 % 360]
            s, e = a0 + g0, a1 - g1
            arco = QPainterPath()
            n = int((e - s) / 1.0)
            for k in range(n + 1):
                th = math.radians(s + (e - s) * k / n)
                q = QPointF(r * math.sin(th), -r * math.cos(th))
                arco.moveTo(q) if k == 0 else arco.lineTo(q)
            p.drawPath(arco)

        # Tacche ogni 5 minuti (non dove ci sono numeri e puntino)
        p.setPen(QPen(ink, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        for m in range(5, 60, 5):
            if m in (15, 30, 45):
                continue
            p.save()
            p.rotate(m * 6)
            p.drawLine(QLineF(0, -(r + 1.2), 0, -(r - 11.5)))
            p.restore()

        # Numeri 15, 30, 45 (rivolti verso il centro)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(ink))
        for m in (15, 30, 45):
            tp = percorso_testo(str(m), self._font_sans(True), 17.0)
            p.save()
            p.rotate(m * 6)
            p.translate(0, -r)
            p.rotate(180)
            p.drawPath(tp)
            p.restore()

        # Puntino a ore 12
        self._cerchio(p, 0, -r, 7.6, QBrush(ink))
        p.restore()

    # ---------- livello 3: lancette (ogni fotogramma) ----------
    @staticmethod
    def _colore_lume(env):
        r = LUME[0] + (LUME_NOTTE[0] - LUME[0]) * env
        g = LUME[1] + (LUME_NOTTE[1] - LUME[1]) * env
        b = LUME[2] + (LUME_NOTTE[2] - LUME[2]) * env
        return QColor(int(r), int(g), int(b))

    def _disegna_lancetta(self, p, angolo, forma, lumi, env=0.0):
        oro = grad_lineare(-6, 0, 6, 0, self.pal["lama"])
        p.save()
        p.translate(2.2, 3.2)
        p.rotate(angolo)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawPath(forma)
        p.restore()
        p.save()
        p.rotate(angolo)
        p.setPen(QPen(QColor(*self.pal["pen_scuro"]), 0.9))
        p.setBrush(QBrush(oro))
        p.drawPath(forma)
        p.setPen(QPen(QColor(176, 140, 56), 0.5))
        p.setBrush(QBrush(self._colore_lume(env)))
        for lume in lumi:
            p.drawPath(lume)
        p.restore()

    def _disegna_lancette(self, p, env=0.0):
        self._disegna_lancetta(p, self.ang_hour, self.h_ore, (self.h_ore_lume_asta, self.h_ore_lume_punta), env)
        self._disegna_lancetta(p, self.ang_min, self.h_min, (self.h_min_lume,), env)

        # Lancetta dei secondi: bianca, sottile, con disco luminescente
        p.save()
        p.translate(1.6, 2.6)
        p.rotate(self.ang_sec)
        p.setPen(QPen(QColor(0, 0, 0, 80), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QLineF(0, 22, 0, -101))
        p.restore()
        p.save()
        p.rotate(self.ang_sec)
        p.setPen(QPen(QColor(240, 240, 238), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QLineF(0, 22, 0, -101))
        g = QRadialGradient(QPointF(0, -56), 6.5)
        g.setColorAt(0.0, QColor(252, 250, 236))
        g.setColorAt(1.0, QColor(226, 218, 176))
        self._cerchio(p, 0, -56, 6.3, QBrush(g), QPen(QColor(196, 160, 68), 1.0))
        p.restore()

        # Perno centrale (metallo dalla palette)
        g = grad_radiale(-2.5, -3, 13, self.pal["perno"])
        self._cerchio(p, 0, 0, 10.5, QBrush(g), QPen(QColor(*self.pal["pen_scuro"]), 0.9))
        self._cerchio(p, 0, 0, 4.2, QBrush(self._colore_lume(env)), QPen(QColor(176, 140, 56), 0.7))
        self._cerchio(p, 0, 0, 1.3, QBrush(QColor(196, 186, 146)))

    def _disegna_minuto(self, p):
        """Piccolo indicatore del minuto sotto il puntino, visibile mentre si gira la ghiera."""
        m = int(round(self.bezel_rotation / 6.0)) % 60
        tp = self._cache_minuti.get(m)
        if tp is None:
            tp = percorso_testo(str(m), self._font_sans(True), 12.0)
            self._cache_minuti[m] = tp
        p.setPen(QPen(QColor(200, 150, 48, 235), 1.4))
        p.setBrush(QColor(20, 22, 28, 220))
        p.drawRoundedRect(QRectF(-22, 14, 44, 26), 6, 6)
        p.save()
        p.translate(0, 27)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 232, 160))
        p.drawPath(tp)
        p.restore()

    def _disegna_corona_hint(self, p):
        """Etichetta vicino alla corona estratta: giorno/data mentre si correggono
        (posizione 1), l'ora mentre si regolano le lancette (posizione 2)."""
        if self.crown_pos == 1:
            oggi = self._now().date()
            giorni = ["ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС"]
            nome_giorno = giorni[(oggi.dayOfWeek() - 1 + self._day_offset) % 7]
            numero_data = ((oggi.day() - 1 + self._date_offset) % 31) + 1
            testo = "%s %d" % (nome_giorno, numero_data)
        elif self.crown_pos == 2:
            testo = self._now().time().toString("HH:mm")
        else:
            return
        tp = percorso_testo(testo, self._font_sans(True), 11.0)
        br = tp.boundingRect()
        larg = br.width() + 16
        p.save()
        p.translate(152.0, -46.0)
        p.setPen(QPen(QColor(200, 150, 48, 235), 1.4))
        p.setBrush(QColor(20, 22, 28, 225))
        p.drawRoundedRect(QRectF(-larg / 2, -13, larg, 26), 6, 6)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 232, 160))
        p.save()
        p.translate(-br.center().x(), -br.center().y())
        p.drawPath(tp)
        p.restore()
        p.restore()

    def _disegna_icone(self, p):
        """Tre piccole icone sempre uguali a se stesse: in alto per girare l'orologio, in
        basso (solo sul retro) per svitare/avvitare il fondello, e a sinistra (sempre) per
        aprire le impostazioni."""
        cx, cy, r = 0.0, -205.0, 13.0
        p.setPen(QPen(QColor(230, 230, 230, 235), 1.6))
        p.setBrush(QColor(30, 32, 38, 200))
        p.drawEllipse(QPointF(cx, cy), r, r)
        p.setPen(QPen(QColor(230, 230, 230, 235), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(cx - 7, cy - 7, 14, 14), 20 * 16, 200 * 16)
        p.drawArc(QRectF(cx - 7, cy - 7, 14, 14), 200 * 16, 200 * 16)
        for ang in (20, 200):
            a = math.radians(ang)
            px, py = cx + 7 * math.cos(a), cy + 7 * math.sin(a)
            p.save()
            p.translate(px, py)
            p.rotate(-ang + 90)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(230, 230, 230, 235))
            freccia = QPainterPath()
            freccia.moveTo(-2.6, 0)
            freccia.lineTo(2.6, 0)
            freccia.lineTo(0, 4.2)
            freccia.closeSubpath()
            p.drawPath(freccia)
            p.restore()

        if self._flip_target >= 0.5:
            cx2, cy2 = 0.0, 205.0
            p.setPen(QPen(QColor(230, 230, 230, 235), 1.6))
            p.setBrush(QColor(30, 32, 38, 200))
            p.drawEllipse(QPointF(cx2, cy2), r, r)
            p.setPen(QPen(QColor(230, 230, 230, 235), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QLineF(cx2 - 7, cy2, cx2 + 7, cy2))

        # Impostazioni: un piccolo ingranaggio sul lato sinistro, come una seconda corona
        cx3, cy3 = self._icona_impostazioni_centro()
        p.setPen(QPen(QColor(230, 230, 230, 235), 1.6))
        p.setBrush(QColor(30, 32, 38, 200))
        p.drawEllipse(QPointF(cx3, cy3), r, r)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(230, 230, 230, 235))
        for i in range(8):
            p.save()
            p.translate(cx3, cy3)
            p.rotate(i * 45)
            p.drawRect(QRectF(-1.6, -9.5, 3.2, 4.2))
            p.restore()
        p.setPen(QPen(QColor(30, 32, 38, 235), 1.6))
        p.setBrush(QColor(230, 230, 230, 235))
        p.drawEllipse(QPointF(cx3, cy3), 4.6, 4.6)

    def _icona_impostazioni_centro(self):
        return -201.0, 0.0

    # ---------- corona e fronte/retro ----------
    def _corona_click(self):
        """Un click sulla corona la fa scattare in fuori di una posizione (0 -> 1 -> 2 -> 0)."""
        vecchia = self.crown_pos
        self.crown_pos = (self.crown_pos + 1) % 3
        if vecchia == 2 and self.crown_pos == 0:
            # richiusa dopo aver regolato le lancette: l'orario impostato riprende a scorrere
            adesso = QDateTime.currentDateTime()
            self._time_offset_ms = adesso.msecsTo(self._crown_freeze_dt)
            self._crown_freeze_dt = None
        elif self.crown_pos == 2:
            # estratta del tutto: le lancette si fermano all'orario mostrato in quel momento
            self._crown_freeze_dt = self._now()
        self._crown_hint_fino = time.monotonic() + 2.4
        self._riproduci("crown_click", genera_click)
        self.update()

    def _flip_toggle(self):
        self._flip_target = 0.0 if self._flip_target >= 0.5 else 1.0
        self._riproduci("flip", genera_click)

    # ---------- impostazioni (finestra separata, effetto immediato) ----------
    def _applica_quadrante(self, nome):
        if nome not in DIALS:
            return
        self.dial_preset = nome
        preset = DIALS[nome]
        metallo = METALLI[preset["metal"]]
        self.pal = dict(metallo)
        self.pal["dial"] = preset["dial"]
        self.pal["accent"] = preset["accent"]
        self.update()

    def _applica_bezel_material(self, materiale):
        if materiale in ("enamel", "steel", "ceramic"):
            self.bezel_material = materiale
            self.update()

    def _applica_bezel_colore(self, colore):
        if colore in CERAMIC_PALETTES:
            self.bezel_ceramic_color = colore
            self.update()

    def _applica_crown_su_cambia(self, valore):
        if valore in ("data", "giorno"):
            self.crown_su_cambia = valore

    def _applica_dedica(self, testo):
        self.caseback_dedica = testo
        self.update()

    def _applica_numero_serie(self, testo):
        self.caseback_numero_serie = testo
        self.update()

    # ---------- avvio automatico col computer (Windows e Linux) ----------
    def _comando_avvio(self):
        """Il comando che deve rilanciare questo stesso widget: l'eseguibile compilato se
        e' stato impacchettato (PyInstaller e simili), altrimenti l'interprete Python piu'
        il percorso di questo script."""
        if getattr(sys, "frozen", False):
            return sys.executable, None
        script = os.path.abspath(__file__)
        if sys.platform.startswith("win"):
            pitone = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
            if not os.path.exists(pitone):
                pitone = sys.executable          # ripiego: mostrera' comunque una console
            return pitone, script
        return sys.executable, script

    def _percorso_autostart(self):
        if sys.platform.startswith("win"):
            cartella = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                                    "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
            return os.path.join(cartella, "vostok_widget_autostart.vbs")
        if sys.platform.startswith("linux"):
            cartella = os.path.join(os.path.expanduser("~"), ".config", "autostart")
            return os.path.join(cartella, "vostok-widget.desktop")
        return None

    def _autostart_supportato(self):
        return self._percorso_autostart() is not None

    def _autostart_attivo(self):
        percorso = self._percorso_autostart()
        return percorso is not None and os.path.exists(percorso)

    def _imposta_autostart(self, attivo):
        """Scrive (o toglie) il file che fa partire il widget da solo al prossimo accesso.
        Restituisce (riuscito, messaggio_di_errore_o_None)."""
        percorso = self._percorso_autostart()
        if percorso is None:
            return False, "su questo sistema operativo va impostato a mano"
        try:
            if not attivo:
                if os.path.exists(percorso):
                    os.remove(percorso)
                return True, None
            os.makedirs(os.path.dirname(percorso), exist_ok=True)
            eseguibile, script = self._comando_avvio()
            if sys.platform.startswith("win"):
                if script is None:
                    riga = 'objShell.Run """{0}""", 0, False'.format(eseguibile)
                else:
                    riga = 'objShell.Run """{0}"" ""{1}""", 0, False'.format(eseguibile, script)
                contenuto = 'Set objShell = CreateObject("WScript.Shell")\n' + riga + '\n'
            else:
                comando = '"%s"' % eseguibile if script is None else '"%s" "%s"' % (eseguibile, script)
                contenuto = ("[Desktop Entry]\n"
                            "Type=Application\n"
                            "Name=Vostok Amphibia Widget\n"
                            "Exec=%s\n"
                            "X-GNOME-Autostart-enabled=true\n"
                            "Terminal=false\n" % comando)
            with open(percorso, "w", encoding="utf-8") as f:
                f.write(contenuto)
            return True, None
        except OSError as e:
            return False, str(e)

    def _apri_impostazioni(self):
        if self._dlg_impostazioni is not None:
            self._dlg_impostazioni.show()
            self._dlg_impostazioni.raise_()
            self._dlg_impostazioni.activateWindow()
            return

        dlg = QDialog(self, Qt.WindowType.Window)
        dlg.setWindowTitle("Impostazioni \u2014 Vostok Amphibia")
        dlg.setModal(False)
        dlg.resize(360, 10)
        form = QFormLayout()

        combo_quad = QComboBox()
        chiavi_quad = list(DIALS.keys())
        for chiave in chiavi_quad:
            combo_quad.addItem(DIALS[chiave].get("display", chiave), chiave)
        combo_quad.setCurrentIndex(max(0, chiavi_quad.index(self.dial_preset)) if self.dial_preset in chiavi_quad else 0)
        combo_quad.currentIndexChanged.connect(lambda i: self._applica_quadrante(combo_quad.itemData(i)))
        form.addRow("Quadrante:", combo_quad)

        combo_mat = QComboBox()
        materiali = [("enamel", "Smaltata (bianca)"), ("steel", "Acciaio"), ("ceramic", "Ceramica")]
        for chiave, etichetta in materiali:
            combo_mat.addItem(etichetta, chiave)
        combo_mat.setCurrentIndex([m[0] for m in materiali].index(self.bezel_material))
        form.addRow("Ghiera:", combo_mat)

        combo_col = QComboBox()
        colori = [("black", "Nero"), ("blue", "Blu"), ("green", "Verde"), ("orange", "Arancione"),
                 ("grigio", "Grigio")]
        for chiave, etichetta in colori:
            combo_col.addItem(etichetta, chiave)
        combo_col.setCurrentIndex([c[0] for c in colori].index(self.bezel_ceramic_color))
        combo_col.setEnabled(self.bezel_material == "ceramic")
        form.addRow("Colore ceramica:", combo_col)

        def _cambia_materiale(i):
            chiave = combo_mat.itemData(i)
            self._applica_bezel_material(chiave)
            combo_col.setEnabled(chiave == "ceramic")

        combo_mat.currentIndexChanged.connect(_cambia_materiale)
        combo_col.currentIndexChanged.connect(lambda i: self._applica_bezel_colore(combo_col.itemData(i)))

        combo_corona = QComboBox()
        versi = [("data", "in su cambia la data"), ("giorno", "in su cambia il giorno")]
        for chiave, etichetta in versi:
            combo_corona.addItem(etichetta, chiave)
        combo_corona.setCurrentIndex([v[0] for v in versi].index(self.crown_su_cambia))
        combo_corona.currentIndexChanged.connect(lambda i: self._applica_crown_su_cambia(combo_corona.itemData(i)))
        form.addRow("Rotella (corona estratta):", combo_corona)

        campo_dedica = QLineEdit(self.caseback_dedica)
        campo_dedica.setMaxLength(40)
        campo_dedica.setPlaceholderText("es. A Giuseppina, 2026")
        campo_dedica.textChanged.connect(self._applica_dedica)
        form.addRow("Dedica sul fondello:", campo_dedica)

        campo_numero = QLineEdit(self.caseback_numero_serie)
        campo_numero.setMaxLength(12)
        campo_numero.textChanged.connect(self._applica_numero_serie)
        form.addRow("Numero di serie:", campo_numero)

        casella_avvio = QCheckBox("Avvia con il computer")
        supportato = self._autostart_supportato()
        casella_avvio.setEnabled(supportato)
        casella_avvio.setChecked(self._autostart_attivo() if supportato else False)
        etichetta_avvio = QLabel("" if supportato else "Su questo sistema va impostato a mano.")
        etichetta_avvio.setWordWrap(True)

        def _cambia_avvio(spuntato):
            riuscito, errore = self._imposta_autostart(bool(spuntato))
            if riuscito:
                etichetta_avvio.setText("Si aprir\u00e0 da solo al prossimo accesso."
                                        if spuntato else "Avvio automatico disattivato.")
            else:
                casella_avvio.blockSignals(True)
                casella_avvio.setChecked(not spuntato)
                casella_avvio.blockSignals(False)
                etichetta_avvio.setText("Non sono riuscito a impostarlo: %s" % errore)

        casella_avvio.toggled.connect(_cambia_avvio)
        form.addRow("", casella_avvio)
        form.addRow("", etichetta_avvio)

        nota = QLabel("Le modifiche si vedono subito e restano ricordate alla prossima apertura.")
        nota.setWordWrap(True)

        pulsante = QPushButton("Chiudi")
        pulsante.clicked.connect(dlg.close)

        layout = QVBoxLayout(dlg)
        layout.addLayout(form)
        layout.addWidget(nota)
        layout.addWidget(pulsante)

        self._dlg_impostazioni = dlg
        dlg.show()

    def _scuoti_movimento(self):
        """Una scossa (click) sul meccanismo a vista: carica il bilanciere e da' una
        spinta al rotore, come dare un colpetto a un automatico per farlo ripartire."""
        self._carica = min(CARICA_MASSIMA, self._carica + CARICA_PER_SCOSSA)
        self._rotore_vel += ROTORE_SPINTA + random.uniform(-25.0, 25.0)
        self._riproduci("click", genera_click)

    # ---------- premio dell'easter egg ----------
    def _disegna_bagliore(self, p, env, t):
        """Indici e puntini 'accesi' come al buio."""
        k = env * (0.82 + 0.18 * math.sin(t * 4.0))
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(12):
            if i == 3:
                continue
            hw = 8.8 if i == 0 else 6.2
            p.save()
            p.rotate(i * 30)
            p.setBrush(QColor(110, 255, 185, int(60 * k)))
            p.drawRoundedRect(QRectF(-hw - 4.5, -125 - 4.5, 2 * hw + 9, 35 + 9), 7, 7)
            p.setBrush(QColor(140, 255, 200, int(105 * k)))
            p.drawRoundedRect(QRectF(-hw - 1.6, -125 - 1.6, 2 * hw + 3.2, 35 + 3.2), 4, 4)
            p.setBrush(QColor(215, 255, 235, int(215 * k)))
            p.drawRoundedRect(QRectF(-hw * 0.6, -125 + 3, hw * 1.2, 35 - 6), 2.4, 2.4)
            p.setBrush(QColor(110, 255, 185, int(70 * k)))
            p.drawEllipse(QPointF(0, -129.5), 7.0, 7.0)
            p.setBrush(QColor(225, 255, 240, int(230 * k)))
            p.drawEllipse(QPointF(0, -129.5), 3.7, 3.7)
            p.restore()

    def _disegna_premio(self, p, t, env):
        # Onda d'urto dorata
        if t < 1.4:
            u = t / 1.4
            r = 20 + 300 * (u ** 0.7)
            p.setPen(QPen(QColor(255, 224, 120, int(210 * (1 - u))), 7 * (1 - u) + 1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(0, 0), r, r)

        # Scritta "Поехали!"
        p.save()
        p.translate(0, 19)
        pen = QPen(QColor(24, 12, 0, int(220 * env)), 5.0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self._tp_poehali)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 226, 140, int(255 * env)))
        p.drawPath(self._tp_poehali)
        p.restore()

        # Scintille
        p.setPen(Qt.PenStyle.NoPen)
        for q in self._particelle:
            vita = 1.0 - q["eta"] / q["ttl"]
            r, g, b = q["col"]
            p.setBrush(QColor(r, g, b, int(255 * min(1.0, vita * 1.6))))
            p.save()
            p.translate(q["x"], q["y"])
            p.rotate(q["rot"])
            p.scale(q["s"], q["s"])
            p.drawPath(self._stella)
            p.restore()

    # --------------------------------------------------------
    # Mouse
    # --------------------------------------------------------
    def _pos_unita(self, event):
        scale = min(self.width(), self.height()) / 500.0
        dx = (event.position().x() - self.width() / 2.0) / scale
        dy = (event.position().y() - self.height() / 2.0) / scale
        return dx, dy

    @staticmethod
    def _angolo_da_12(dx, dy):
        return math.degrees(math.atan2(dx, -dy)) % 360.0

    def mousePressEvent(self, event):
        if self._allarme_attivo():          # il primo click durante l'allarme lo interrompe
            self._ferma_allarme()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            dx, dy = self._pos_unita(event)
            if self._in_corona(dx, dy):
                self._corona_click()
                return
            if math.hypot(dx, dy - (-205.0)) <= 15.0:
                self._flip_toggle()
                return
            cxi, cyi = self._icona_impostazioni_centro()
            if math.hypot(dx - cxi, dy - cyi) <= 15.0:
                self._apri_impostazioni()
                return
            if self._flip_target >= 0.5 and math.hypot(dx, dy - 205.0) <= 15.0:
                self._svita_target = 1.0 - self._svita_target
                self._riproduci("svita", genera_svita)
                return
            if self._flip_target >= 0.5 and self._svita_target >= 0.999 and math.hypot(dx, dy) <= R_ACCIAIO[0]:
                self._scuoti_movimento()
                return
            if self._flip_target < 0.5 and R_GHIERA[0] <= math.hypot(dx, dy) <= R_ORLO[1]:
                self.dragging_bezel = True
                self._bezel_ang_prec = self._angolo_da_12(dx, dy)
                self._bezel_accum = 0.0
                self._minuto_fino = time.monotonic() + 1.4
                self._ee_controlla_tenuta()
            else:
                self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.trigger_alarm()
        elif event.button() == Qt.MouseButton.RightButton:
            self.close()               # passa da closeEvent: salva posizione/dimensione prima di uscire

    def mouseMoveEvent(self, event):
        if self.dragging_bezel:
            dx, dy = self._pos_unita(event)
            ang = self._angolo_da_12(dx, dy)
            delta = (ang - self._bezel_ang_prec + 540.0) % 360.0 - 180.0
            self._bezel_ang_prec = ang
            self._bezel_accum += delta
            passo = float(GHIERA_SCATTO_GRADI)
            if self._ccw_sbloccato or not GHIERA_SOLO_ORARIO:
                scatti = int(self._bezel_accum / passo)
            else:                                    # ghiera unidirezionale: solo senso orario
                self._bezel_accum = max(0.0, self._bezel_accum)
                scatti = int(self._bezel_accum // passo)
            if scatti != 0:
                self._bezel_accum -= scatti * passo
                self.bezel_rotation = (self.bezel_rotation + scatti * GHIERA_SCATTO_GRADI) % 360
                self._ee_registra_passi(scatti)
                self._minuto_fino = time.monotonic() + 1.4
                self.alarm_armed = True     # il puntino e' stato posizionato: l'allarme e' attivo
                self._ee_controlla_tenuta()
                self.update()
        elif event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)

    def mouseReleaseEvent(self, event):
        if self.dragging_bezel:
            self.dragging_bezel = False
            self._ee_timer.stop()
            self._minuto_fino = time.monotonic() + 1.4

    def wheelEvent(self, event):
        dx, dy = self._pos_unita(event)
        if self.crown_pos > 0 and self._in_corona(dx, dy):
            su = event.angleDelta().y() > 0
            if self.crown_pos == 1:
                cambia_data = su if self.crown_su_cambia == "data" else not su
                if cambia_data:
                    self._date_offset = (self._date_offset + 1) % 31
                else:
                    self._day_offset = (self._day_offset + 1) % 7
            else:                                    # posizione 2: regola le lancette
                self._crown_freeze_dt = self._crown_freeze_dt.addSecs(60 if su else -60)
            self._crown_hint_fino = time.monotonic() + 2.4
            self.update()
            return
        delta = event.angleDelta().y()
        nuova_larg = self.width() + (30 if delta > 0 else -30)
        nuova_larg = max(350, min(1300, nuova_larg))
        self.resize(nuova_larg, int(nuova_larg * 500 / 600))

    # --------------------------------------------------------
    # Posizione e dimensione ricordate da una sessione all'altra
    # --------------------------------------------------------
    def _carica_stato(self):
        """Se esiste uno stato salvato da una chiusura precedente, riapre il widget nella
        stessa posizione e alla stessa dimensione, un po' come farebbe un vero widget da
        scrivania - e con le stesse preferenze scelte l'ultima volta nella finestra di
        impostazioni. Qualunque problema (file assente, corrotto, schermo cambiato, valore
        non valido) si ignora in silenzio: quel singolo valore resta quello di default."""
        try:
            with open(FILE_STATO, "r", encoding="utf-8") as f:
                dati = json.load(f)
        except Exception:
            return
        try:
            larg = max(350, min(1300, int(dati["w"])))
            alt = int(larg * 500 / 600)
            self.resize(larg, alt)
            schermo = QApplication.primaryScreen().availableGeometry()
            x = max(schermo.left() - larg + 60, min(int(dati["x"]), schermo.right() - 60))
            y = max(schermo.top(), min(int(dati["y"]), schermo.bottom() - 60))
            self.move(x, y)
        except Exception:
            pass
        if dati.get("dial_preset") in DIALS:
            self.dial_preset = dati["dial_preset"]
        if dati.get("bezel_material") in ("enamel", "steel", "ceramic"):
            self.bezel_material = dati["bezel_material"]
        if dati.get("bezel_ceramic_color") in CERAMIC_PALETTES:
            self.bezel_ceramic_color = dati["bezel_ceramic_color"]
        if dati.get("crown_su_cambia") in ("data", "giorno"):
            self.crown_su_cambia = dati["crown_su_cambia"]
        if isinstance(dati.get("caseback_dedica"), str):
            self.caseback_dedica = dati["caseback_dedica"]
        if isinstance(dati.get("caseback_numero_serie"), str):
            self.caseback_numero_serie = dati["caseback_numero_serie"]

    def _salva_stato(self):
        try:
            dati = {"x": self.x(), "y": self.y(), "w": self.width(),
                    "dial_preset": self.dial_preset, "bezel_material": self.bezel_material,
                    "bezel_ceramic_color": self.bezel_ceramic_color,
                    "crown_su_cambia": self.crown_su_cambia,
                    "caseback_dedica": self.caseback_dedica,
                    "caseback_numero_serie": self.caseback_numero_serie}
            with open(FILE_STATO, "w", encoding="utf-8") as f:
                json.dump(dati, f)
        except OSError:
            pass

    def closeEvent(self, event):
        if RICORDA_POSIZIONE:
            self._salva_stato()
        if self._dlg_impostazioni is not None:
            self._dlg_impostazioni.close()
        super().closeEvent(event)
        # L'uscita e' esplicita: vedi setQuitOnLastWindowClosed(False) in fondo al file
        QApplication.instance().quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    # Il widget e' una finestra di tipo Tool, che Qt non conta tra le finestre "principali":
    # senza questa riga, chiudendo la finestra delle impostazioni (l'unica finestra normale)
    # Qt crederebbe chiusa l'ultima finestra e terminerebbe l'intera applicazione.
    # Cosi' invece il programma esce solo dal click destro sull'orologio (closeEvent).
    app.setQuitOnLastWindowClosed(False)
    widget = VostokWidget()
    widget.show()
    sys.exit(app.exec())
