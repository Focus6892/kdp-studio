"""Optional Kindle Previewer 3 conversion check (the closest thing to KDP's own converter).

Kindle Previewer is a free desktop app from Amazon with a command-line mode:
  "Kindle Previewer 3.exe" book.epub -Convert -Output <dir> -Locale en
It is not installed on every machine, so this module degrades to an info finding.
Set KINDLE_PREVIEWER_PATH to the executable to override discovery.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..findings import FindingList

CANDIDATES = [
    Path(os.environ.get("LOCALAPPDATA", "")) / "Amazon" / "Kindle Previewer 3" / "Kindle Previewer 3.exe",
    Path("C:/Program Files (x86)/Amazon/Kindle Previewer 3/Kindle Previewer 3.exe"),
    Path("C:/Program Files/Amazon/Kindle Previewer 3/Kindle Previewer 3.exe"),
    Path("/Applications/Kindle Previewer 3.app/Contents/MacOS/Kindle Previewer 3"),
]


def find_kindle_previewer() -> Path | None:
    env = os.environ.get("KINDLE_PREVIEWER_PATH")
    if env and Path(env).is_file():
        return Path(env)
    for c in CANDIDATES:
        if str(c) and c.is_file():
            return c
    exe = shutil.which("kindlepreviewer") or shutil.which("Kindle Previewer 3")
    return Path(exe) if exe else None


def run_kindle_previewer(epub: Path, out_dir: Path, timeout_s: int = 900) -> FindingList:
    f = FindingList()
    exe = find_kindle_previewer()
    if exe is None:
        f.info("kindle_previewer.missing", "Kindle Previewer 3 not found; install it from Amazon and set KINDLE_PREVIEWER_PATH to run the conversion check.", epub.name)
        return f
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [str(exe), str(epub), "-Convert", "-Output", str(out_dir), "-Locale", "en"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired:
        f.error("kindle_previewer.timeout", f"Kindle Previewer did not finish within {timeout_s}s.", epub.name)
        return f
    if proc.returncode != 0:
        f.error("kindle_previewer.exit", f"Kindle Previewer exited with code {proc.returncode}: {(proc.stderr or proc.stdout)[-400:]}", epub.name)
    errors = warnings = 0
    logs = sorted(list(out_dir.rglob("*.csv")) + list(out_dir.rglob("*.log")) + list(out_dir.rglob("*.txt")))
    for log_path in logs:
        try:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            low = line.lower()
            if "error" in low and "0 error" not in low:
                errors += 1
            elif "warning" in low and "0 warning" not in low:
                warnings += 1
    converted = list(out_dir.rglob("*.mobi")) + list(out_dir.rglob("*.kpf")) + list(out_dir.rglob("*.azw3"))
    if errors:
        f.error("kindle_previewer.errors", f"Kindle Previewer reported {errors} error line(s); see {out_dir}.", epub.name)
    elif not converted and proc.returncode == 0:
        f.warning("kindle_previewer.no_output", f"Kindle Previewer produced no converted file in {out_dir}.", epub.name)
    if warnings:
        f.warning("kindle_previewer.warnings", f"Kindle Previewer reported {warnings} warning line(s); see {out_dir}.", epub.name)
    if not errors and converted:
        f.info("kindle_previewer.ok", f"Kindle Previewer converted the EPUB ({converted[0].name}).", epub.name)
    return f
