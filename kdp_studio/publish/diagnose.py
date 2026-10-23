"""Decode KDP Print Previewer errors into print settings.

KDP's most common cover rejection reads "Your expected cover size is W1xH1 but the
submitted file size is W2xH2". Both numbers encode trim size, bleed and spine, so the
mismatch can be turned into "the draft is set to 6x9 white paper, your file was built
for 5x8 cream" and a concrete fix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .. import specs

DIM_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)")


def parse_dims(text: str) -> tuple[float, float]:
    m = DIM_RE.search(text)
    if not m:
        raise ValueError(f"No WxH dimensions in {text!r}")
    return float(m.group(1)), float(m.group(2))


@dataclass
class CoverGuess:
    width_in: float
    height_in: float
    trim: str | None = None
    spine_in: float | None = None
    papers: list[str] = field(default_factory=list)  # paper types whose spine factor matches (given pages)
    pages_estimate: dict[str, int] = field(default_factory=dict)  # paper -> implied page count (when pages unknown)

    def describe(self) -> str:
        if not self.trim:
            return f"{self.width_in:.3f} x {self.height_in:.3f} in (no KDP trim size matches this height)"
        paper = "/".join(self.papers) if self.papers else "paper unknown"
        return f"{self.width_in:.3f} x {self.height_in:.3f} in = trim {self.trim}, spine {self.spine_in:.3f} in ({paper})"


def guess_cover(width_in: float, height_in: float, pages: int | None = None) -> CoverGuess:
    g = CoverGuess(width_in, height_in)
    trim_h = height_in - 2 * specs.BLEED_IN
    best = None
    for t in specs.TRIMS.values():
        if abs(t.height_in - trim_h) <= 0.011:
            spine = width_in - 2 * specs.BLEED_IN - 2 * t.width_in
            if spine >= 0.04 and (best is None or abs(spine) < abs(best[1])):
                # several trims share a height (5x8 / 5.25x8); the spine must stay plausible (>= 24 pages)
                best = (t.key, spine)
    if best is None:
        return g
    g.trim, g.spine_in = best[0], round(best[1], 4)
    for paper, factor in specs.SPINE_IN_PER_PAGE.items():
        if pages:
            if abs(factor * pages - g.spine_in) <= 0.0031:
                g.papers.append(paper)
        else:
            g.pages_estimate[paper] = int(round(g.spine_in / factor))
    return g


def explain_cover_size_error(message_or_expected: str, submitted: str | None = None, pages: int | None = None, book=None) -> dict:
    """Parse "expected ... W1xH1 ... submitted ... W2xH2" (or two separate strings) and explain the mismatch."""
    if submitted is None:
        dims = DIM_RE.findall(message_or_expected)
        if len(dims) < 2:
            raise ValueError("Need two WxH sizes (expected and submitted)")
        expected = tuple(float(v) for v in dims[0])
        submitted_d = tuple(float(v) for v in dims[1])
    else:
        expected = parse_dims(message_or_expected)
        submitted_d = parse_dims(submitted)
    exp = guess_cover(*expected, pages=pages)
    sub = guess_cover(*submitted_d, pages=pages)
    lines = [f"KDP expects: {exp.describe()}", f"Your file:   {sub.describe()}"]
    advice: list[str] = []
    if exp.trim and sub.trim and exp.trim != sub.trim:
        advice.append(f"The draft's Print Options use trim {exp.trim}; the cover was built for {sub.trim}. Set Trim Size on the Content tab to {sub.trim} (or rebuild with print.trim: {exp.trim}).")
    if exp.papers and sub.papers and not set(exp.papers) & set(sub.papers):
        advice.append(f"Paper differs too: KDP has {'/'.join(exp.papers)}, the file assumes {'/'.join(sub.papers)}. Match 'Ink and Paper Type' to book.yaml.")
    if exp.trim and sub.trim and exp.trim == sub.trim and abs((exp.spine_in or 0) - (sub.spine_in or 0)) > 0.003:
        advice.append("Same trim but a different spine: the page count or paper used for the cover differs from the uploaded interior. Rebuild the cover after the interior is final.")
    if book is not None:
        p = book.print_
        advice.append(f"book.yaml says trim {p.trim}, paper {p.paper}, bleed {'yes' if p.bleed else 'no'}, finish {p.cover_finish}; make the KDP Print Options match exactly, then re-upload or just re-run the Previewer.")
    if not advice:
        advice.append("Compare trim, paper and page count between the Content tab and the build; rebuild the cover with `kdp build` once they match.")
    return {"expected": exp, "submitted": sub, "lines": lines, "advice": advice}
