"""Vector drawing specs -> crisp coloring-page line art, with no image model involved.

A spec is a small JSON document that Claude (or a person) can write by hand:

    {"title": "daisy in a round frame", "canvas": [1000, 1500], "stroke": 14,
     "shapes": [
        {"type": "circle", "c": [500, 700], "r": 430},
        {"type": "repeat", "count": 12, "center": [500, 700],
         "shapes": [{"type": "petal", "c": [500, 700], "r_inner": 90, "length": 300, "width": 120, "angle": -90}]},
        {"type": "curve", "points": [[500, 1130], [480, 1250], [520, 1400]]}
     ]}

Coordinates live on the spec's own canvas (default 1000 x 1500, portrait) and are scaled to the
requested pixel size, so the same spec renders cleanly at 300 DPI. Shapes: circle, ellipse, arc,
line (polyline), curve (smooth Catmull-Rom through the points, optionally closed), bezier (cubic),
polygon, petal (leaf/petal outline, as in the placeholder art), dot (filled circle, for eyes and
centres), repeat (rotational copies around a centre) and mirror (left-right copies). Any shape may
carry its own "stroke". Output is pure black on white, so cleanup/QA treat it like any other page.

Who drew it: a spec written by Claude is AI-generated content for KDP's disclosure; a spec you
wrote yourself is not.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

Point = tuple[float, float]


def _pt(p: Any) -> Point:
    return float(p[0]), float(p[1])


def catmull_rom(points: list[Point], closed: bool = False, steps: int = 16) -> list[Point]:
    """Smooth polyline through the given points."""
    if len(points) < 3:
        return points
    pts = list(points)
    if closed:
        pts = [pts[-1], *pts, pts[0], pts[1]]
    else:
        pts = [pts[0], *pts, pts[-1]]
    out: list[Point] = []
    for i in range(1, len(pts) - 2):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[i + 1], pts[i + 2]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
            y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
            out.append((x, y))
    out.append(pts[-2])
    return out


def cubic_bezier(p0: Point, c1: Point, c2: Point, p1: Point, steps: int = 40) -> list[Point]:
    out = []
    for s in range(steps + 1):
        t = s / steps
        u = 1 - t
        x = u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p1[0]
        y = u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p1[1]
        out.append((x, y))
    return out


def petal_outline(c: Point, r_inner: float, length: float, width: float, angle_deg: float, steps: int = 36) -> list[Point]:
    a = math.radians(angle_deg)
    ux, uy = math.cos(a), math.sin(a)
    pts = []
    for i in range(steps + 1):
        t = 2 * math.pi * i / steps
        ex = (length / 2) * (1 + math.cos(t))
        ey = (width / 2) * math.sin(t)
        pts.append((c[0] + ux * (r_inner + ex) - uy * ey, c[1] + uy * (r_inner + ex) + ux * ey))
    return pts


def _rotate(p: Point, center: Point, angle_deg: float) -> Point:
    a = math.radians(angle_deg)
    dx, dy = p[0] - center[0], p[1] - center[1]
    return center[0] + dx * math.cos(a) - dy * math.sin(a), center[1] + dx * math.sin(a) + dy * math.cos(a)


def _mirror(p: Point, axis_x: float) -> Point:
    return 2 * axis_x - p[0], p[1]


def flatten(shapes: list[dict], transform=None) -> list[tuple[str, list[Point], dict]]:
    """Expand repeat/mirror groups into primitive polylines/ellipses with absolute coordinates.
    Returns (kind, points, extra) where kind is 'poly' (open), 'closed', 'ellipse' or 'dot'."""
    out: list[tuple[str, list[Point], dict]] = []
    tf = transform or (lambda p: p)
    for sh in shapes:
        kind = sh.get("type")
        stroke = sh.get("stroke")
        extra = {"stroke": stroke}
        if kind == "repeat":
            center = _pt(sh.get("center", [500, 750]))
            count = int(sh.get("count", 6))
            start = float(sh.get("start", 0.0))
            for k in range(count):
                ang = start + 360.0 * k / count
                out.extend(flatten(sh.get("shapes", []), lambda p, ang=ang, center=center: tf(_rotate(p, center, ang))))
            continue
        if kind == "mirror":
            axis = float(sh.get("axis_x", 500))
            inner = sh.get("shapes", [])
            out.extend(flatten(inner, tf))
            out.extend(flatten(inner, lambda p, axis=axis: tf(_mirror(p, axis))))
            continue
        if kind in ("circle", "ellipse", "dot"):
            c = _pt(sh["c"])
            rx = float(sh.get("r", sh.get("rx", 10)))
            ry = float(sh.get("r", sh.get("ry", rx)))
            # approximate as a polygon so rotation/mirroring work uniformly
            rot = float(sh.get("rotate", 0.0))
            pts = []
            for i in range(72):
                t = 2 * math.pi * i / 72
                p = (c[0] + rx * math.cos(t), c[1] + ry * math.sin(t))
                pts.append(tf(_rotate(p, c, rot)))
            out.append(("dot" if kind == "dot" else "closed", pts, extra))
            continue
        if kind == "arc":
            c = _pt(sh["c"])
            r = float(sh["r"])
            a0, a1 = float(sh.get("start", 0)), float(sh.get("end", 180))
            n = max(8, int(abs(a1 - a0) / 4))
            pts = [tf((c[0] + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), c[1] + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))) for i in range(n + 1)]
            out.append(("poly", pts, extra))
            continue
        if kind == "line":
            out.append(("poly", [tf(_pt(p)) for p in sh["points"]], extra))
            continue
        if kind == "polygon":
            out.append(("closed", [tf(_pt(p)) for p in sh["points"]], extra))
            continue
        if kind == "curve":
            pts = catmull_rom([_pt(p) for p in sh["points"]], closed=bool(sh.get("closed", False)))
            out.append(("closed" if sh.get("closed") else "poly", [tf(p) for p in pts], extra))
            continue
        if kind == "bezier":
            p = [_pt(q) for q in sh["points"]]
            if len(p) != 4:
                raise ValueError("bezier needs exactly 4 points: start, control 1, control 2, end")
            out.append(("poly", [tf(q) for q in cubic_bezier(*p)], extra))
            continue
        if kind == "petal":
            pts = petal_outline(_pt(sh["c"]), float(sh.get("r_inner", 0)), float(sh["length"]), float(sh["width"]), float(sh.get("angle", -90)))
            out.append(("closed", [tf(p) for p in pts], extra))
            continue
        raise ValueError(f"unknown shape type {kind!r}")
    return out


def render_spec(spec: dict, size: tuple[int, int]) -> Image.Image:
    """Rasterise a spec onto a white canvas of `size` pixels (black strokes only)."""
    cw, ch = spec.get("canvas", [1000, 1500])
    sx, sy = size[0] / float(cw), size[1] / float(ch)
    scale = min(sx, sy)
    ox, oy = (size[0] - cw * scale) / 2, (size[1] - ch * scale) / 2
    base_stroke = float(spec.get("stroke", 12))
    img = Image.new("L", size, 255)
    d = ImageDraw.Draw(img)

    def to_px(p: Point) -> tuple[float, float]:
        return ox + p[0] * scale, oy + p[1] * scale

    for kind, pts, extra in flatten(spec.get("shapes", [])):
        px = [to_px(p) for p in pts]
        w = max(2, int(round((extra.get("stroke") or base_stroke) * scale)))
        if kind == "dot":
            xs, ys = [p[0] for p in px], [p[1] for p in px]
            d.ellipse((min(xs), min(ys), max(xs), max(ys)), fill=0)
        elif kind == "closed":
            d.line([*px, px[0]], fill=0, width=w, joint="curve")
            _round_caps(d, [*px, px[0]], w)
        else:
            d.line(px, fill=0, width=w, joint="curve")
            _round_caps(d, px, w)
    return img


def _round_caps(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], w: int) -> None:
    r = w / 2
    for p in (pts[0], pts[-1]):
        d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=0)


def load_specs(folder: Path) -> list[tuple[Path, dict]]:
    out = []
    for p in sorted(folder.glob("*.json")):
        out.append((p, json.loads(p.read_text(encoding="utf-8"))))
    if not out:
        raise FileNotFoundError(f"No drawing specs (*.json) in {folder}")
    return out


def validate_spec(spec: dict) -> list[str]:
    """Cheap structural checks so a bad spec fails with a message instead of a stack trace."""
    problems = []
    if not isinstance(spec.get("shapes"), list) or not spec["shapes"]:
        problems.append("spec has no shapes")
    try:
        flatten(spec.get("shapes", []))
    except (KeyError, ValueError, TypeError) as exc:
        problems.append(f"shape error: {exc}")
    return problems
