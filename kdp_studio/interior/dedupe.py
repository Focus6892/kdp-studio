"""Near-duplicate detection for coloring pages, within a book and across the catalog.

KDP removes books whose content is "excessively reused, recycled, or repeated
within or across books". Sparse black-and-white line art defeats a plain 64-bit
pHash (distinct drawings with the same frame/composition land within a few bits,
while a shifted copy can be 20+ bits away), so each page gets a descriptor built
on the ink bounding box:

* pHash + dHash of the cropped art (catches identical / re-encoded files)
* a 32x32 ink-density map, compared by Pearson correlation

A page is a duplicate only when BOTH the pHash distance is small AND the density
correlation is high. Measured on 40 deliberately samey placeholder pages
(2026-10-23): false positives 0.8% of pairs; recall 100% for exact copies, JPEG
re-encodes and small shifts, ~60% for rescaled/re-thresholded copies. Thresholds
live in book.yaml (interior.dedupe.max_distance / min_correlation).
Pure numpy, no scipy.
"""

from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

DENSITY_N = 32


def _dct_matrix(n: int) -> np.ndarray:
    k = np.arange(n)[:, None]
    i = np.arange(n)[None, :]
    m = np.sqrt(2.0 / n) * np.cos(math.pi * (2 * i + 1) * k / (2 * n))
    m[0, :] /= math.sqrt(2.0)
    return m


_DCT32 = _dct_matrix(32)


def bbox_crop(img: Image.Image, threshold: int = 128) -> Image.Image:
    """Crop to the bounding box of the ink so margins and framing don't matter."""
    a = np.asarray(img.convert("L")) < threshold
    ys, xs = np.where(a)
    if len(xs) == 0:
        return img
    return img.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))


def phash(img: Image.Image, hash_size: int = 8) -> int:
    g = img.convert("L").resize((32, 32), Image.LANCZOS)
    a = np.asarray(g, dtype=np.float64)
    coeffs = _DCT32 @ a @ _DCT32.T
    low = coeffs[:hash_size, :hash_size].flatten()
    median = np.median(low[1:])
    bits = low > median
    bits[0] = False
    out = 0
    for bit in bits:
        out = (out << 1) | int(bit)
    return out


def dhash(img: Image.Image, hash_size: int = 8) -> int:
    g = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    out = 0
    for bit in bits:
        out = (out << 1) | int(bit)
    return out


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def density_grid(img: Image.Image, n: int = DENSITY_N) -> np.ndarray:
    """Ink coverage per cell (0..255) of an n x n grid over the (already cropped) art."""
    ink = Image.fromarray(((np.asarray(img.convert("L")) < 128) * 255).astype(np.uint8))
    return np.asarray(ink.resize((n, n), Image.BOX), dtype=np.uint8)


def _normalize(grid: np.ndarray) -> np.ndarray:
    v = grid.astype(np.float64).flatten()
    v -= v.mean()
    s = np.linalg.norm(v)
    return v / s if s else v


@dataclass
class Descriptor:
    phash: int
    dhash: int
    grid: np.ndarray  # uint8 n x n

    @property
    def vector(self) -> np.ndarray:
        return _normalize(self.grid)

    def to_json(self) -> dict:
        return {"phash": self.phash, "dhash": self.dhash, "grid_b64": base64.b64encode(self.grid.tobytes()).decode("ascii"), "grid_n": int(self.grid.shape[0])}

    @classmethod
    def from_json(cls, d: dict) -> "Descriptor":
        n = int(d.get("grid_n", DENSITY_N))
        raw = base64.b64decode(d["grid_b64"]) if d.get("grid_b64") else bytes(n * n)
        grid = np.frombuffer(raw, dtype=np.uint8).reshape(n, n)
        return cls(int(d["phash"]), int(d["dhash"]), grid)


def describe(img: Image.Image) -> Descriptor:
    crop = bbox_crop(img)
    return Descriptor(phash(crop), dhash(crop), density_grid(crop))


def correlation(a: Descriptor, b: Descriptor) -> float:
    if a.grid.shape != b.grid.shape:
        return 0.0
    return float(np.dot(a.vector, b.vector))


def is_duplicate(a: Descriptor, b: Descriptor, max_distance: int, min_correlation: float) -> tuple[bool, int, float]:
    d = hamming(a.phash, b.phash)
    c = correlation(a, b)
    return (d <= max_distance and c >= min_correlation), d, c


@dataclass
class HashEntry:
    book_id: str
    page: int
    descriptor: Descriptor
    source: str = ""

    def to_json(self) -> dict:
        return {"book_id": self.book_id, "page": self.page, "source": self.source, **self.descriptor.to_json()}

    @classmethod
    def from_json(cls, d: dict) -> "HashEntry":
        return cls(d["book_id"], int(d["page"]), Descriptor.from_json(d), d.get("source", ""))


@dataclass
class Match:
    entry: HashEntry
    distance: int
    correlation: float


@dataclass
class HashLibrary:
    path: Path
    entries: list[HashEntry] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "HashLibrary":
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls(path, [HashEntry.from_json(e) for e in data.get("entries", [])])
        return cls(path, [])

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"version": 2, "entries": [e.to_json() for e in self.entries]}), encoding="utf-8")

    def find_near(self, desc: Descriptor, max_distance: int, min_correlation: float, exclude_book: str | None = None) -> list[Match]:
        out = []
        for e in self.entries:
            if exclude_book and e.book_id == exclude_book:
                continue
            dup, d, c = is_duplicate(desc, e.descriptor, max_distance, min_correlation)
            if dup:
                out.append(Match(e, d, c))
        return sorted(out, key=lambda m: (m.distance, -m.correlation))

    def replace_book(self, book_id: str, entries: list[HashEntry]) -> None:
        self.entries = [e for e in self.entries if e.book_id != book_id] + entries


def duplicates_within(descs: list[Descriptor], max_distance: int, min_correlation: float) -> list[tuple[int, int, int, float]]:
    """(i, j, distance, correlation) for every pair judged duplicate."""
    out = []
    for i in range(len(descs)):
        for j in range(i + 1, len(descs)):
            dup, d, c = is_duplicate(descs[i], descs[j], max_distance, min_correlation)
            if dup:
                out.append((i, j, d, c))
    return out
