"""Thirty flower coloring pages as vector drawing specs (kdp_studio/interior/vector.py), composed from a small library
of flower parts. Authored by Claude, so the pages are AI-generated content for KDP's disclosure. Run
`python make_specs.py` to (re)write drawings/*.json next to this file; `kdp draw-preview drawings` renders them."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

OUT = Path(__file__).resolve().parent / "drawings"
W, H, CX, CY = 1000, 1500, 500, 750
BOLD, MID, FINE = 16, 12, 8


def P(x, y):
    return [round(float(x), 1), round(float(y), 1)]


def _s(shape, stroke):
    if stroke:
        shape["stroke"] = stroke
    return shape


def circle(c, r, stroke=None):
    return _s({"type": "circle", "c": P(*c), "r": round(r, 1)}, stroke)


def ellipse(c, rx, ry, rotate=0, stroke=None):
    return _s({"type": "ellipse", "c": P(*c), "rx": round(rx, 1), "ry": round(ry, 1), "rotate": rotate}, stroke)


def dot(c, r):
    return {"type": "dot", "c": P(*c), "r": round(r, 1)}


def curve(points, closed=False, stroke=None):
    s = {"type": "curve", "points": [P(*p) for p in points]}
    if closed:
        s["closed"] = True
    return _s(s, stroke)


def line(points, stroke=None):
    return _s({"type": "line", "points": [P(*p) for p in points]}, stroke)


def polygon(points, stroke=None):
    return _s({"type": "polygon", "points": [P(*p) for p in points]}, stroke)


def arc(c, r, start, end, stroke=None):
    return _s({"type": "arc", "c": P(*c), "r": round(r, 1), "start": start, "end": end}, stroke)


def petal(c, r_inner, length, width, angle, stroke=None):
    return _s({"type": "petal", "c": P(*c), "r_inner": round(r_inner, 1), "length": round(length, 1), "width": round(width, 1), "angle": angle}, stroke)


def repeat(count, center, shapes, start=0.0):
    return {"type": "repeat", "count": count, "center": P(*center), "start": start, "shapes": shapes}


def mirror(shapes, axis_x=CX):
    return {"type": "mirror", "axis_x": axis_x, "shapes": shapes}


def polar(c, r, deg):
    a = math.radians(deg)
    return (c[0] + r * math.cos(a), c[1] + r * math.sin(a))


def wavy(c, r, bumps, depth=0.12, phase=0.0, stroke=None, n=None):
    """Closed smooth curve around c with `bumps` scallops: rose, peony and carnation outlines, scalloped frames."""
    n = n or max(24, bumps * 6)
    pts = [polar(c, r * (1 + depth * math.cos(bumps * 2 * math.pi * i / n + phase)), 360.0 * i / n) for i in range(n)]
    return curve(pts, closed=True, stroke=stroke)


# ---------------------------------------------------------------- flower parts
def petal_ring(c, n, r_inner, length, width, start=0.0, stroke=None):
    return repeat(n, c, [petal(c, r_inner, length, width, -90, stroke)], start)


def center_disc(c, r, dots=8, dot_r=None, ring_r=None):
    out = [circle(c, r)]
    if dots:
        out.append(repeat(dots, c, [dot((c[0], c[1] - (ring_r or r * 0.55)), dot_r or max(6, r * 0.11))]))
    return out


def daisy(c, r_core, n=12, length=220, width=110, double=False):
    out = [petal_ring(c, n, r_core, length, width)]
    if double:
        out.append(petal_ring(c, n, r_core + 10, length * 0.6, width * 0.55, stroke=FINE))  # nested inside each petal, no crossing lines
    return out + center_disc(c, r_core)


def stem(top, bottom, bend=40, stroke=None):
    (x0, y0), (x1, y1) = top, bottom
    return curve([top, (x0 + bend, y0 + (y1 - y0) * 0.33), (x1 - bend * 0.6, y0 + (y1 - y0) * 0.7), bottom], stroke=stroke)


def leaf(base, angle, length, width, stroke=None, rib=True):
    out = [petal(base, 0, length, width, angle, stroke)]
    if rib:
        out.append(line([base, polar(base, length * 0.85, angle)], FINE))
    return out


def tulip_head(c, size=1.0):
    rel = [(0, 0), (-100, -120), (-100, -280), (-40, -210), (0, -330), (40, -210), (100, -280), (100, -120)]
    return curve([(c[0] + x * size, c[1] + y * size) for x, y in rel], closed=True)


def rose_head(c, r):
    return [petal_ring(c, 7, r * 0.42, r * 0.58, r * 0.5, stroke=BOLD), petal_ring(c, 5, r * 0.12, r * 0.28, r * 0.3, start=25),
            curve([polar(c, r * 0.10 * (1 - i / 14), 40 * i) for i in range(15)])]


def pot(cx, top, w_top, w_bottom, h, rim=50):
    return [polygon([(cx - w_top / 2, top + rim), (cx + w_top / 2, top + rim), (cx + w_bottom / 2, top + h), (cx - w_bottom / 2, top + h)], BOLD),
            polygon([(cx - w_top / 2 - 25, top), (cx + w_top / 2 + 25, top), (cx + w_top / 2 + 25, top + rim), (cx - w_top / 2 - 25, top + rim)], BOLD)]


def vase(cx, top, h, neck=90, belly=190, foot=120):
    pts = [(cx - neck, top), (cx - neck - 10, top + h * 0.18), (cx - belly, top + h * 0.5), (cx - foot, top + h * 0.9), (cx - foot - 10, top + h),
           (cx + foot + 10, top + h), (cx + foot, top + h * 0.9), (cx + belly, top + h * 0.5), (cx + neck + 10, top + h * 0.18), (cx + neck, top)]
    return [curve(pts, closed=True, stroke=BOLD), line([(cx - neck, top), (cx + neck, top)], BOLD)]


def ribbon_bow(c, size=1.0):
    x, y = c
    return [ellipse((x - 70 * size, y), 70 * size, 42 * size, rotate=-15), ellipse((x + 70 * size, y), 70 * size, 42 * size, rotate=15), circle((x, y), 22 * size),
            curve([(x - 10 * size, y + 20 * size), (x - 60 * size, y + 90 * size), (x - 40 * size, y + 160 * size)]),
            curve([(x + 10 * size, y + 20 * size), (x + 60 * size, y + 90 * size), (x + 40 * size, y + 160 * size)])]


def sun(c, r, rays=12, ray_len=70):
    return [circle(c, r, BOLD), repeat(rays, c, [line([(c[0], c[1] - r - 25), (c[0], c[1] - r - 25 - ray_len)])])]


def bee(c, size=1.0):
    x, y = c
    return [ellipse((x, y), 60 * size, 38 * size), circle((x - 72 * size, y), 22 * size), dot((x - 80 * size, y - 6 * size), 4 * size),
            *[line([(x - 25 * size + i * 25 * size, y - 34 * size), (x - 25 * size + i * 25 * size, y + 34 * size)], FINE) for i in range(3)],
            ellipse((x - 10 * size, y - 55 * size), 40 * size, 22 * size, rotate=-25), ellipse((x + 30 * size, y - 55 * size), 38 * size, 20 * size, rotate=-10)]


def poppy(c, r):
    return [wavy(c, r, 4, 0.14, stroke=BOLD), circle(c, r * 0.32), repeat(6, c, [dot((c[0], c[1] - r * 0.5), 8)])]


def daffodil(c, r):
    return [petal_ring(c, 6, r * 0.35, r, r * 0.55), wavy(c, r * 0.42, 6, 0.15, stroke=MID), circle(c, r * 0.18)]


def blossom(c, r):
    return [petal_ring(c, 5, r * 0.25, r, r * 0.8), circle(c, r * 0.22), repeat(5, c, [dot((c[0], c[1] - r * 0.3), 5)], start=36)]


def bell(c, size=1.0, angle=0.0):
    rel = [(0, 0), (-35, 20), (-55, 95), (-70, 150), (-45, 135), (-20, 155), (0, 140), (20, 155), (45, 135), (70, 150), (55, 95), (35, 20)]
    pts = [polar(c, math.hypot(x, y) * size, math.degrees(math.atan2(y, x)) + angle) if (x or y) else c for x, y in rel]
    return curve(pts, closed=True, stroke=MID)


def orchid_bloom(c, r):
    return [petal_ring(c, 5, r * 0.18, r, r * 0.62, start=36), wavy((c[0], c[1] + r * 0.55), r * 0.38, 5, 0.18, stroke=MID), circle(c, r * 0.16)]


def seed(c, size=1.0, angle=-90):
    tip = polar(c, 70 * size, angle)
    return [dot(c, 9 * size), line([c, tip], FINE)] + [line([tip, polar(tip, 48 * size, angle + d)], FINE) for d in (-55, -28, 0, 28, 55)]


def jagged_leaf(base, tip, width, teeth=5, stroke=None):
    (x0, y0), (x1, y1) = base, tip
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    px, py = -dy / length, dx / length
    left, right = [], []
    for i in range(1, teeth + 1):
        t = i / (teeth + 1)
        w = width * math.sin(math.pi * t) * (0.5 if i % 2 else 0.25)
        bx, by = x0 + dx * t, y0 + dy * t
        left.append((bx + px * w, by + py * w))
        right.append((bx - px * w, by - py * w))
    return polygon([base, *left, tip, *reversed(right)], stroke)


def heart_leaf(c, size=1.0):
    x, y = c
    rel = [(0, -20), (-60, -70), (-90, -20), (-40, 60), (0, 100), (40, 60), (90, -20), (60, -70)]
    return curve([(x + a * size, y + b * size) for a, b in rel], closed=True)


def morning_glory(c, r):
    star = [polar(c, r * (0.55 if i % 2 else 0.95), -90 + 36 * i) for i in range(10)]
    return [circle(c, r, BOLD), curve(star, closed=True, stroke=FINE), circle(c, r * 0.18)]


def pansy(c, r):
    return [petal_ring(c, 5, r * 0.2, r, r * 0.8), circle(c, r * 0.18), repeat(5, c, [line([(c[0], c[1] - r * 0.2), (c[0], c[1] - r * 0.55)], FINE)], start=36)]


# ---------------------------------------------------------------- pages
def p00():  # a single large daisy filling the page
    c = (CX, 690)
    return daisy(c, 140, 14, 330, 170, double=True) + [stem((CX, 1260), (CX, 1450), 30, BOLD)] + leaf((490, 1330), 200, 230, 110) + leaf((510, 1390), -20, 220, 100)


def p01():  # a tulip in a tall vase
    return vase(CX, 780, 660, 110, 230, 150) + [line([(CX, 780), (CX, 470)], BOLD), tulip_head((CX, 470), 1.2)] + leaf((470, 780), 250, 360, 140) + leaf((530, 780), -70, 360, 140)


def p02():  # a rose with wide curled petals
    return rose_head((CX, 640), 400) + [stem((CX, 1045), (CX, 1450), 40, BOLD)] + leaf((500, 1180), 200, 260, 120) + leaf((500, 1300), -20, 240, 110)


def p03():  # a sunflower with a big round center and wide petals
    c = (CX, 620)
    return [petal_ring(c, 16, 170, 280, 120), petal_ring(c, 16, 180, 200, 80, stroke=FINE), circle(c, 170, BOLD), circle(c, 120, FINE),
            repeat(12, c, [dot((c[0], c[1] - 145), 9)]), repeat(8, c, [dot((c[0], c[1] - 85), 9)], start=22.5), dot(c, 12),
            stem((CX, 1070), (CX, 1450), 30, BOLD)] + leaf((500, 1200), 195, 300, 150) + leaf((500, 1320), -15, 280, 140)


def p04():  # five tulips tied together with a ribbon bow
    out = []
    for hx, hy in [(250, 490), (375, 370), (500, 330), (625, 370), (750, 490)]:
        out.append(tulip_head((hx, hy), 0.8))
        out.append(curve([(hx, hy), (hx + (CX - hx) * 0.3, hy + 250), (CX, 1040)], stroke=MID))
    out += ribbon_bow((CX, 1070), 1.1)
    for dx in (-110, -55, 0, 55, 110):
        out.append(curve([(CX, 1100), (CX + dx * 0.5, 1250), (CX + dx, 1420)], stroke=MID))
    return out + leaf((430, 980), 210, 260, 100) + leaf((570, 980), -30, 260, 100)


def p05():  # a potted cactus with one bloom
    body = curve([(500, 440), (400, 490), (360, 700), (370, 1000), (630, 1000), (640, 700), (600, 490)], closed=True, stroke=BOLD)
    arm_l = curve([(362, 760), (250, 740), (200, 620), (230, 520), (300, 520), (300, 620), (335, 660)], stroke=BOLD)
    arm_r = curve([(638, 700), (760, 690), (800, 560), (770, 460), (700, 460), (700, 560), (668, 600)], stroke=BOLD)
    spines = [line([(x, y - 18), (x, y + 18)], FINE) for x, y in [(440, 600), (560, 600), (500, 800), (420, 900), (580, 900), (250, 580), (750, 520)]]
    return [body, arm_l, arm_r, *spines] + pot(CX, 1000, 320, 260, 400, 60) + daisy((CX, 330), 55, 8, 120, 70)


def p06():  # three poppies on long stems
    out = []
    for x, y, r, bx in [(270, 480, 170, 390), (520, 330, 190, 500), (750, 520, 160, 610)]:
        out += poppy((x, y), r)
        out.append(curve([(x, y + r), (x + (bx - x) * 0.4, y + r + 300), (bx, 1450)], stroke=MID))
    return out + leaf((450, 1150), 200, 220, 70) + leaf((560, 1250), -20, 220, 70) + leaf((420, 1320), 190, 200, 60)


def p07():  # a lily with curling petals
    c = (CX, 640)
    return [petal_ring(c, 6, 50, 400, 180, start=30), petal_ring(c, 6, 60, 250, 90, start=30, stroke=FINE),
            repeat(5, c, [line([(c[0], c[1] - 20), (c[0], c[1] - 170)], FINE), dot((c[0], c[1] - 185), 14)], start=-40),
            stem((CX, 1090), (CX, 1450), 30, BOLD)] + leaf((500, 1220), 205, 330, 90) + leaf((500, 1330), -25, 300, 80)


def p08():  # a lotus floating on a pond with lily pads
    out = [petal((500, 900), 0, 480, 170, -90, BOLD), petal((440, 905), 0, 400, 150, -112, BOLD), petal((560, 905), 0, 400, 150, -68, BOLD),
           petal((390, 920), 0, 300, 130, -135), petal((610, 920), 0, 300, 130, -45), petal((350, 950), 0, 200, 110, -160), petal((650, 950), 0, 200, 110, -20),
           curve([(60, 1000), (200, 980), (340, 1010), (480, 990), (620, 1010), (760, 985), (940, 1000)], stroke=BOLD)]
    for x, y, rx, ry in [(250, 1120, 170, 70), (740, 1160, 190, 80), (520, 1330, 220, 90)]:
        out += [ellipse((x, y), rx, ry), line([(x, y), (x + rx * 0.75, y - ry * 0.6)], FINE)]
    return out + [arc((400, 1250), 60, 20, 160, FINE), arc((820, 1320), 50, 20, 160, FINE), arc((150, 1380), 55, 20, 160, FINE)]


def p09():  # a wreath of roses and leaves
    c, R = (CX, 760), 370
    top = (CX, c[1] - R)
    rose = [wavy(top, 95, 6, 0.12, stroke=BOLD), wavy(top, 60, 5, 0.14, phase=1.5), curve([polar(top, 30 * (1 - i / 8), 50 * i) for i in range(9)], stroke=FINE)]
    leaves = leaf((CX + 95, top[1] - 25), 10, 150, 70) + leaf((CX + 95, top[1] + 35), 40, 140, 65) + [dot((CX + 150, top[1] + 95), 12), dot((CX + 185, top[1] + 60), 12)]
    return [repeat(6, c, rose + leaves)]


def p10():  # a hibiscus with a long stamen
    c = (CX, 700)
    return [petal_ring(c, 5, 40, 410, 300), petal_ring(c, 5, 50, 300, 120, stroke=FINE), circle(c, 45),
            curve([c, (c[0] + 120, c[1] - 160), (c[0] + 230, c[1] - 330)], stroke=MID), repeat(5, (c[0] + 240, c[1] - 345), [dot((c[0] + 240, c[1] - 375), 11)]),
            stem((CX, 1110), (CX, 1450), 35, BOLD)] + leaf((500, 1240), 200, 260, 120) + leaf((500, 1340), -20, 240, 110)


def p11():  # a basket of mixed wildflowers
    out = [polygon([(230, 950), (770, 950), (700, 1320), (300, 1320)], BOLD), polygon([(200, 900), (800, 900), (800, 955), (200, 955)], BOLD),
           arc((CX, 950), 420, 200, 340, BOLD), arc((CX, 950), 392, 204, 336, FINE)]
    out += [line([(260 + i * 60, 960), (300 + i * 50, 1315)], FINE) for i in range(1, 8)]
    out += [curve([(300, 1080), (500, 1120), (700, 1080)], stroke=FINE), curve([(310, 1200), (500, 1240), (690, 1200)], stroke=FINE)]
    for x, y, r in [(330, 740, 70), (560, 690, 85), (720, 790, 60)]:
        out += daisy((x, y), r * 0.45, 10, r, r * 0.55) + [line([(x, y + r * 1.4), (x, 900)], MID)]
    for x, y in [(430, 700), (650, 720)]:
        out += [tulip_head((x, y), 0.5), line([(x, y), (x, 900)], MID)]
    return out + leaf((400, 890), 240, 180, 70) + leaf((620, 890), -60, 180, 70)


def p12():  # a lavender bunch tied with string
    out = []
    for tx, ty in [(260, 330), (380, 220), (500, 180), (620, 220), (740, 330)]:
        out.append(curve([(tx, ty + 330), (tx + (CX - tx) * 0.3, ty + 600), (CX, 1040)], stroke=MID))
        out += [ellipse((tx, ty + k * 48), 26 if k else 18, 22, stroke=MID) for k in range(7)]
    out += ribbon_bow((CX, 1070), 0.9)
    return out + [curve([(CX, 1100), (CX + dx * 0.6, 1260), (CX + dx, 1430)], stroke=MID) for dx in (-90, -45, 0, 45, 90)]


def p13():  # a small watering can with three large daisies standing in it
    out = [curve([(330, 900), (670, 900), (690, 1380), (310, 1380)], closed=True, stroke=BOLD), polygon([(300, 860), (700, 860), (700, 905), (300, 905)], BOLD),
           line([(690, 1000), (900, 760)], BOLD), line([(690, 1090), (930, 830)], BOLD), ellipse((915, 795), 45, 28, rotate=-45, stroke=BOLD),
           arc((500, 860), 170, 200, 340, BOLD), arc((500, 860), 140, 205, 335, FINE), line([(300, 1100), (700, 1100)], FINE), line([(300, 1300), (700, 1300)], FINE)]
    for x, y, r, sx in [(260, 470, 85, 380), (500, 330, 100, 500), (740, 470, 85, 620)]:
        out += daisy((x, y), r * 0.45, 12, r, r * 0.5) + [curve([(x, y + r * 1.45), (x + (sx - x) * 0.4, y + 300), (sx, 860)], stroke=MID)]
    return out + leaf((430, 760), 215, 170, 70) + leaf((580, 740), -40, 170, 70)


def p14():  # a single large peony flower head seen from above
    c = (CX, 720)
    return [petal_ring(c, 10, 200, 260, 190, stroke=BOLD), petal_ring(c, 10, 210, 170, 100, stroke=FINE), petal_ring(c, 8, 70, 130, 120, start=18),
            circle(c, 60), repeat(8, c, [dot((c[0], c[1] - 36), 8)])] + leaf((430, 1230), 215, 230, 110) + leaf((570, 1230), -35, 230, 110)


def p15():  # a pair of daffodils with leaves
    out = daffodil((330, 430), 200) + daffodil((650, 560), 190)
    out += [curve([(330, 640), (360, 900), (420, 1450)], stroke=BOLD), curve([(650, 760), (620, 1000), (560, 1450)], stroke=BOLD)]
    return out + leaf((300, 1450), 255, 560, 90, rib=False) + leaf((700, 1450), -80, 540, 90, rib=False) + leaf((490, 1450), 268, 420, 70, rib=False)


def p16():  # a hanging planter with trailing flowers
    out = [line([(CX, 60), (CX, 200)], BOLD), line([(CX, 200), (280, 560)], MID), line([(CX, 200), (720, 560)], MID), line([(CX, 200), (CX, 540)], MID),
           polygon([(240, 540), (760, 540), (760, 600), (240, 600)], BOLD), arc((CX, 600), 250, 0, 180, BOLD), arc((CX, 600), 215, 10, 170, FINE)]
    for x, y, r in [(360, 470, 60), (500, 440, 70), (640, 470, 60)]:
        out += daisy((x, y), r * 0.42, 10, r, r * 0.55)
    for side in (-1, 1):
        x0 = CX + side * 240
        vine = [(x0, 650), (x0 + side * 90, 850), (x0 - side * 20, 1050), (x0 + side * 80, 1250), (x0, 1430)]
        out.append(curve(vine, stroke=MID))
        for vx, vy in vine[1:4]:
            out += leaf((vx, vy), 180 if side < 0 else 0, 120, 60) + [petal_ring((vx + side * 10, vy + 90), 5, 12, 45, 32), dot((vx + side * 10, vy + 90), 10)]
    return out


def p17():  # a flower mandala with eight petals
    c = (CX, CY)
    return [wavy(c, 480, 16, 0.04, stroke=BOLD), circle(c, 430, FINE), petal_ring(c, 8, 160, 240, 170), petal_ring(c, 8, 165, 150, 80, start=22.5, stroke=FINE),
            circle(c, 160, BOLD), petal_ring(c, 8, 40, 110, 70), circle(c, 40), repeat(16, c, [dot((c[0], c[1] - 445), 10)], start=11.25)]


def p18():  # a cherry blossom branch
    out = [curve([(80, 1400), (300, 1150), (520, 900), (700, 600), (900, 280)], stroke=20), curve([(300, 1150), (420, 1180), (560, 1130)], stroke=MID),
           curve([(520, 900), (640, 930), (760, 850)], stroke=MID), curve([(700, 600), (650, 480), (660, 350)], stroke=MID)]
    for x, y, r, ax, ay in [(210, 1280, 85, 300, 1150), (440, 1050, 90, 500, 920), (620, 990, 75, 560, 1130), (560, 760, 90, 650, 680), (770, 730, 80, 760, 850),
                            (650, 430, 85, 700, 600), (880, 440, 80, 860, 350), (820, 190, 65, 870, 320)]:
        out += blossom((x, y), r) + [line([(ax, ay), polar((x, y), r * 0.3 + r, math.degrees(math.atan2(ay - y, ax - x)))], MID)]
    return out + [circle((x, y), 22) for x, y in [(330, 1070), (700, 540), (620, 300)]]


def p19():  # a garden gate with climbing roses
    out = [polygon([(150, 700), (210, 700), (210, 1450), (150, 1450)], BOLD), polygon([(790, 700), (850, 700), (850, 1450), (790, 1450)], BOLD),
           arc((CX, 740), 290, 180, 360, BOLD), line([(210, 740), (790, 740)], FINE), line([(210, 950), (790, 950)], MID), line([(210, 1350), (790, 1350)], MID)]
    for x in range(280, 740, 60):
        out.append(line([(x, 740 - math.sqrt(max(0.0, 290 ** 2 - (x - CX) ** 2))), (x, 1450)], MID))
    vine = [curve([(180, 1100), (120, 900), (160, 700), (110, 520), (200, 360), (320, 300), (430, 330)], stroke=MID)]
    for x, y, r in [(140, 980, 55), (170, 760, 60), (110, 560, 55), (190, 390, 60), (330, 300, 55)]:
        vine += [wavy((x, y), r, 6, 0.12, stroke=MID), wavy((x, y), r * 0.55, 5, 0.15, phase=1.2, stroke=FINE)]
    vine += leaf((150, 860), 170, 90, 45) + leaf((135, 640), 190, 90, 45) + leaf((150, 460), 200, 90, 45) + leaf((260, 330), 250, 90, 45)
    return out + [mirror(vine)]


def p20():  # a magnolia bloom on a branch
    out = [petal((500, 900), 0, 500, 200, -90, BOLD), petal((430, 905), 0, 430, 180, -112, BOLD), petal((570, 905), 0, 430, 180, -68, BOLD),
           petal((380, 915), 0, 330, 150, -132), petal((620, 915), 0, 330, 150, -48),
           curve([(80, 1200), (300, 1120), (520, 980), (760, 900), (940, 820)], stroke=20), curve([(300, 1120), (330, 1000), (420, 940)], stroke=MID),
           petal((760, 900), 0, 180, 80, -110, MID), ellipse((250, 1300), 130, 60, rotate=-30), line([(130, 1370), (370, 1230)], FINE),
           ellipse((880, 1000), 110, 50, rotate=25), line([(780, 955), (980, 1045)], FINE)]
    return out


def p21():  # a morning glory vine on a trellis
    out = [polygon([(150, 150), (850, 150), (850, 1400), (150, 1400)], BOLD)]
    for d in range(-1250, 701, 150):  # slope +1 lattice lines y = x - d, clipped to the frame
        x0, x1 = max(150, 150 + d), min(850, 1400 + d)
        if x1 > x0:
            out.append(line([(x0, x0 - d), (x1, x1 - d)], FINE))
    for d in range(300, 2251, 150):  # slope -1 lattice lines y = d - x
        x0, x1 = max(150, d - 1400), min(850, d - 150)
        if x1 > x0:
            out.append(line([(x0, d - x0), (x1, d - x1)], FINE))
    out.append(curve([(200, 1400), (350, 1150), (300, 900), (480, 700), (560, 450), (720, 250)], stroke=BOLD))
    for x, y, r in [(260, 1050, 95), (430, 820, 100), (640, 560, 95), (780, 330, 85)]:
        out += morning_glory((x, y), r)
    return out + [heart_leaf((420, 1230), 0.9), heart_leaf((360, 720), 0.9), heart_leaf((620, 760), 0.8), heart_leaf((700, 420), 0.8)]


def ruffle(c, r, bumps, a0=195, a1=345, depth=0.12, stroke=None):
    """Open scalloped arc from angle a0 to a1 (upper half when 180..360): carnation and peony ruffles seen from the side."""
    n = max(16, bumps * 6)
    pts = [polar(c, r * (1 + depth * math.cos(bumps * 2 * math.pi * i / n)), a0 + (a1 - a0) * i / n) for i in range(n + 1)]
    return curve(pts, stroke=stroke)


def p22():  # a carnation with ruffled petals
    c = (CX, 900)
    e0, e1 = polar(c, 420 * 1.12, 195), polar(c, 420 * 1.12, 345)
    out = [ruffle(c, 420, 9, 195, 345, 0.12, BOLD), ruffle(c, 330, 7, 200, 340, 0.14), ruffle(c, 240, 6, 205, 335, 0.16), ruffle(c, 150, 4, 210, 330, 0.18),
           line([e0, (400, 880)], BOLD), line([e1, (600, 880)], BOLD),
           curve([(400, 880), (430, 1060), (500, 1110), (570, 1060), (600, 880)], stroke=BOLD), curve([(400, 880), (500, 850), (600, 880)], stroke=MID), line([(500, 890), (500, 1070)], FINE),
           stem((CX, 1110), (CX, 1450), 25, BOLD)]
    return out + leaf((500, 1250), 200, 230, 60, rib=False) + leaf((500, 1330), -20, 220, 55, rib=False)


def p23():  # a teacup planted with pansies
    out = [curve([(240, 820), (760, 820), (720, 1200), (280, 1200)], closed=True, stroke=BOLD), ellipse((CX, 820), 265, 45, stroke=BOLD),
           arc((790, 1000), 110, 270, 450, BOLD), arc((790, 1000), 75, 275, 445, MID), ellipse((CX, 1230), 360, 70, stroke=BOLD), ellipse((CX, 1230), 300, 45, stroke=FINE)]
    for x, y, r in [(340, 600, 120), (520, 480, 135), (690, 620, 115)]:
        out += pansy((x, y), r) + [curve([(x, y + r * 1.15), (x + (CX - x) * 0.3, 760), (CX + (x - CX) * 0.4, 830)], stroke=MID)]
    return out + leaf((420, 800), 230, 150, 70) + leaf((600, 800), -50, 150, 70)


def p24():  # a dandelion with floating seeds
    c = (CX, 560)
    out = [circle(c, 60, BOLD), repeat(24, c, [line([(c[0], c[1] - 70), (c[0], c[1] - 300)], FINE), dot((c[0], c[1] - 312), 9)], start=7.5),
           circle(c, 335, FINE), stem((CX, 900), (CX, 1450), 25, BOLD), jagged_leaf((500, 1450), (300, 980), 180), jagged_leaf((500, 1450), (700, 1020), 170)]
    for x, y, a, s in [(770, 250, -60, 1.0), (870, 480, -30, 0.9), (820, 720, -80, 0.8), (160, 400, -110, 0.9), (230, 220, -70, 0.8)]:
        out += seed((x, y), s, a)
    return out


def p25():  # a bluebell cluster with a bee
    out = [curve([(620, 1450), (560, 1000), (420, 600), (300, 380), (150, 300)], stroke=BOLD)]
    for x, y, a in [(545, 900, -25), (470, 700, -20), (390, 540, -15), (300, 400, -5), (190, 320, 5)]:
        out += [line([(x, y), (x - 20, y + 40)], FINE), bell((x - 20, y + 40), 0.95, a)]
    out += leaf((640, 1450), 262, 540, 80, rib=False) + leaf((720, 1450), 270, 460, 70, rib=False) + leaf((560, 1450), 254, 380, 60, rib=False)
    return out + bee((780, 520), 1.0)


def p26():  # a window box of geraniums
    out = [polygon([(120, 100), (880, 100), (880, 900), (120, 900)], BOLD), polygon([(170, 150), (830, 150), (830, 850), (170, 850)], MID),
           line([(CX, 150), (CX, 850)], MID), line([(170, 500), (830, 500)], MID), polygon([(90, 900), (910, 900), (910, 990), (90, 990)], BOLD),
           polygon([(140, 990), (860, 990), (820, 1300), (180, 1300)], BOLD), line([(180, 1140), (820, 1140)], FINE)]
    for cx_ in (250, 500, 750):
        for dx, dy in [(0, -150), (-85, -70), (85, -70)]:
            out += [petal_ring((cx_ + dx, 880 + dy), 5, 14, 60, 48), dot((cx_ + dx, 880 + dy), 12)]
        out += [wavy((cx_ - 90, 930), 48, 7, 0.1, stroke=MID), wavy((cx_ + 90, 935), 45, 7, 0.1, stroke=MID), line([(cx_, 880), (cx_, 940)], MID)]
    return out


def p27():  # an orchid with three blooms
    out = [curve([(500, 1300), (520, 1000), (600, 700), (560, 420), (420, 260)], stroke=BOLD)]
    for x, y, r in [(300, 330, 150), (720, 540, 150), (330, 760, 140)]:
        out += orchid_bloom((x, y), r)
    out += [line([(560, 470), (430, 420)], MID), line([(590, 620), (680, 580)], MID), line([(540, 900), (440, 820)], MID)]
    out += leaf((480, 1300), 250, 420, 120) + leaf((520, 1300), -70, 420, 120) + leaf((500, 1300), 255, 300, 100)
    return out + pot(CX, 1300, 300, 240, 150, 40)


def p28():  # a daisy chain border around a single bloom
    pts = [(150, 150), (383, 150), (617, 150), (850, 150), (850, 390), (850, 630), (850, 870), (850, 1110), (850, 1350), (617, 1350), (383, 1350), (150, 1350),
           (150, 1110), (150, 870), (150, 630), (150, 390)]
    out = [polygon(pts, FINE)]
    for x, y in pts:
        out += [petal_ring((x, y), 8, 20, 72, 46), dot((x, y), 17)]
    return out + daisy((CX, 750), 85, 12, 230, 115, double=True)


def p29():  # a tulip field under a round sun
    out = sun((760, 260), 110, 12, 60) + [curve([(60, 820), (300, 760), (600, 800), (940, 740)], stroke=BOLD), curve([(60, 980), (350, 930), (700, 990), (940, 940)], stroke=MID)]
    for x, y in [(160, 700), (330, 680), (500, 690), (670, 680), (840, 700)]:
        out += [tulip_head((x, y), 0.42), line([(x, y), (x, y + 110)], MID)]
    for x, y, s in [(140, 1180, 0.75), (320, 1120, 0.8), (500, 1200, 0.8), (680, 1120, 0.8), (860, 1180, 0.75)]:
        out += [tulip_head((x, y), s), line([(x, y), (x, 1450)], BOLD)] + leaf((x - 5, 1450), 250, 230, 70, rib=False) + leaf((x + 5, 1450), -70, 230, 70, rib=False)
    return out


PAGES = [("a single large daisy filling the page", p00), ("a tulip in a tall vase", p01), ("a rose with wide curled petals", p02), ("a sunflower with a big round center and wide petals", p03),
         ("five tulips tied together with a ribbon bow", p04), ("a potted cactus with one bloom", p05), ("three poppies on long stems", p06), ("a lily with curling petals", p07),
         ("a lotus floating on a pond with lily pads", p08), ("a wreath of roses and leaves", p09), ("a hibiscus with a long stamen", p10), ("a basket of mixed wildflowers", p11),
         ("a lavender bunch tied with string", p12), ("a small watering can with three large daisies", p13), ("a single large peony seen from above", p14), ("a pair of daffodils with leaves", p15),
         ("a hanging planter with trailing flowers", p16), ("a flower mandala with eight petals", p17), ("a cherry blossom branch", p18), ("a garden gate with climbing roses", p19),
         ("a magnolia bloom on a branch", p20), ("a morning glory vine on a trellis", p21), ("a carnation with ruffled petals", p22), ("a teacup planted with pansies", p23),
         ("a dandelion with floating seeds", p24), ("a bluebell cluster with a bee", p25), ("a window box of geraniums", p26), ("an orchid with three blooms", p27),
         ("a daisy chain border around a single bloom", p28), ("a tulip field under a round sun", p29)]


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for old in OUT.glob("*.json"):
        old.unlink()
    total = 0
    for i, (title, fn) in enumerate(PAGES):
        spec = {"title": title, "canvas": [W, H], "stroke": 14, "shapes": fn()}
        text = json.dumps(spec, separators=(",", ":"))
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:32]
        (OUT / f"{i:03d}_{slug}.json").write_text(text, encoding="utf-8")
        total += len(text)
        print(f"{i:02d} {len(text):6d} chars  {title}")
    print(f"{len(PAGES)} specs, {total:,} chars, {total // len(PAGES):,} per page")


if __name__ == "__main__":
    main()
