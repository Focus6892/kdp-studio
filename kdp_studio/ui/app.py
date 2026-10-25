"""Local web interface for kdp-studio.

One Flask app, bound to 127.0.0.1 by default: the books it can see (folders holding book.yaml), their
build state, one-click build / image-test jobs with live logs, the publish queue where you tick the
books to upload, the run folders with their screenshots, this week's KDP quota, which API keys are
present (names only) and the license status. Browser-driven publishing keeps its human gates, so
"Run" opens a console window running `kdp publish ...` instead of hiding it behind a web button.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import threading
import uuid
import webbrowser
from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_file, url_for

from .. import keys as keymod
from ..env import key_status
from ..paths import data_path, project_root
from ..publish.checklist import artifacts_for, build_checklist
from ..publish.quota import quota_status
from ..publish.store import PublishStore
from ..schema import ColoringInterior, load_book

FORMATS = ("paperback", "ebook", "hardcover")


class Jobs:
    """Background subprocesses (build, image-test) with captured logs for the browser to poll."""

    def __init__(self) -> None:
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start(self, title: str, cmd: list[str], book_idx: int | None = None) -> str:
        job_id = uuid.uuid4().hex[:8]
        job = {"id": job_id, "title": title, "cmd": cmd, "started": dt.datetime.now().strftime("%H:%M:%S"), "status": "running", "log": [], "returncode": None,
               "book_idx": book_idx}  # a build job shows that book's progress bar (pages done, thumbnails) above its log
        with self._lock:
            self._jobs[job_id] = job

        def run() -> None:
            try:
                env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
                proc = subprocess.Popen(cmd, cwd=str(project_root()), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", env=env)
                assert proc.stdout is not None
                for line in proc.stdout:
                    job["log"].append(line.rstrip("\n"))
                proc.wait()
                job["returncode"] = proc.returncode
                job["status"] = "done" if proc.returncode == 0 else "failed"
            except Exception as exc:  # noqa: BLE001
                job["log"].append(f"error: {exc}")
                job["status"] = "failed"

        threading.Thread(target=run, daemon=True).start()
        return job_id

    def get(self, job_id: str) -> dict | None:
        return self._jobs.get(job_id)

    def all(self) -> list[dict]:
        return sorted(self._jobs.values(), key=lambda j: j["started"], reverse=True)


def discover_books(dirs: list[Path]) -> list[dict]:
    out: list[dict] = []
    seen: set[Path] = set()
    for d in dirs:
        candidates = [d / "book.yaml"] if (d / "book.yaml").is_file() else sorted(d.glob("*/book.yaml"))
        for y in candidates:
            y = y.resolve()
            if y in seen:
                continue
            seen.add(y)
            entry: dict = {"path": str(y), "folder": y.parent.name}
            try:
                book = load_book(y)
                build = book.build_dir
                pre = build / "preflight.json"
                status = None
                if pre.is_file():
                    try:
                        rep = json.loads(pre.read_text(encoding="utf-8"))
                        status = "PASS" if not rep.get("errors") and not [f for f in rep.get("findings", []) if f.get("level") == "error"] else "FAIL"
                    except Exception:  # noqa: BLE001
                        status = "?"
                entry.update(
                    id=book.id, title=book.metadata.full_title, type=book.type, formats=list(book.formats),
                    interior=(build / "interior.pdf").is_file(), cover=(build / "cover_wrap.pdf").is_file(), ebook=any(build.glob("*.epub")),
                    cover_jpg=str(build / "cover_ebook.jpg") if (build / "cover_ebook.jpg").is_file() else None,
                    preflight=status, provider=getattr(book.interior, "source", None) and book.interior.source.provider if isinstance(book.interior, ColoringInterior) else "story",
                    images=book.interior.images if isinstance(book.interior, ColoringInterior) else None,
                    drawings=len(list((book.book_dir / "drawings").glob("*.json"))) if (book.book_dir / "drawings").is_dir() else 0,
                )
            except Exception as exc:  # noqa: BLE001
                entry["error"] = str(exc).splitlines()[0][:200]
            out.append(entry)
    return out


def _license_status() -> dict:
    try:
        from .. import license as lic
    except Exception:  # noqa: BLE001
        return {"available": False}
    try:
        return {"available": True, **lic.status()}
    except Exception as exc:  # noqa: BLE001
        return {"available": True, "valid": False, "error": str(exc)}


def _spawn_console(args: list[str]) -> str:
    """Open a console window running `python -m kdp_studio <args>` so the human-in-the-loop prompts stay visible."""
    cmd = [sys.executable, "-m", "kdp_studio", *args]
    if sys.platform.startswith("win"):
        subprocess.Popen(["cmd", "/c", "start", "kdp publish", "cmd", "/k", *cmd], cwd=str(project_root()))
    else:
        subprocess.Popen(["x-terminal-emulator", "-e", *cmd], cwd=str(project_root()))
    return " ".join(cmd)


def _pick_folder() -> str | None:
    """Native folder dialog on this machine (the UI runs locally) through tkinter; None when cancelled."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    try:
        return filedialog.askdirectory(title="Chọn thư mục chứa book.yaml (hoặc thư mục cha chứa nhiều sách)", mustexist=True) or None
    finally:
        root.destroy()


def _open_in_file_manager(folder: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(folder))  # noqa: S606 - a local folder the user chose
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(folder)])
    else:
        subprocess.Popen(["xdg-open", str(folder)])


def create_app(book_dirs: list[Path] | None = None) -> Flask:
    app = Flask(__name__, template_folder=str(Path(__file__).parent / "templates"))
    dirs = book_dirs or [p for p in (project_root() / "examples", project_root() / "books") if p.is_dir()]
    dirs_file = data_path("state", "book_dirs.json")  # folders added from the UI, remembered across restarts
    extra_dirs: list[str] = []
    if dirs_file.is_file():
        try:
            extra_dirs = [d for d in json.loads(dirs_file.read_text(encoding="utf-8")) if isinstance(d, str)]
        except ValueError:
            extra_dirs = []
    for d in extra_dirs:
        if Path(d).is_dir() and Path(d) not in dirs:
            dirs.append(Path(d))

    def save_dirs() -> None:
        dirs_file.parent.mkdir(parents=True, exist_ok=True)
        dirs_file.write_text(json.dumps(extra_dirs, indent=2, ensure_ascii=False), encoding="utf-8")

    jobs = Jobs()
    app.extensions["jobs"] = jobs  # tests and other code can start or inspect jobs
    store_path = data_path("publishing", "publish.sqlite")
    runs_dir = data_path("publishing", "runs")
    app.config["BOOK_DIRS"] = dirs
    app.config["BOOKS_ROOT"] = project_root() / "books"  # new books created from the UI land here

    def store() -> PublishStore:
        return PublishStore(store_path)

    def books() -> list[dict]:
        return discover_books(dirs)

    def book_at(idx: int) -> tuple[dict, object]:
        items = books()
        if idx < 0 or idx >= len(items) or "error" in items[idx]:
            abort(404)
        return items[idx], load_book(items[idx]["path"])

    @app.context_processor
    def inject() -> dict:
        """Sidebar and top bar: clock, license, running jobs, this week's KDP quota and how many keys are set."""
        try:
            s = store()
            try:
                nav_quota = quota_status(s)
            finally:
                s.close()
        except Exception:  # noqa: BLE001 - the shell must render even if the store is unavailable
            nav_quota = {}
        return {"now": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "license": _license_status(), "running_jobs": sum(1 for j in jobs.all() if j["status"] == "running"),
                "nav_quota": nav_quota, "keys_present": key_status()}

    @app.get("/")
    def index():
        s = store()
        try:
            quota = quota_status(s)
            titles = {(t["book_id"], t["fmt"]): t for t in s.titles()}
            queued = s.queue_list("queued")
        finally:
            s.close()
        items = books()
        resolved = [(d, str(d.resolve())) for d in dirs]
        counts = {str(d): sum(1 for b in items if str(Path(b["path"]).resolve()).startswith(r + os.sep)) for d, r in resolved}
        return render_template("index.html", books=items, quota=quota, titles=titles, keys=key_status(), queued=len(queued), jobs=jobs.all()[:5], dirs=dirs,
                               extra_dirs=set(extra_dirs), dir_counts=counts, message=request.args.get("m"))

    def _add_book_dir(raw: str):
        raw = raw.strip().strip('"')
        if not raw:
            return redirect(url_for("index", m="Chưa nhập đường dẫn thư mục") + "#dirs")
        p = Path(raw).expanduser()
        if p.is_file() and p.name == "book.yaml":
            p = p.parent
        if not p.is_dir():
            return redirect(url_for("index", m=f"Không thấy thư mục {raw}") + "#dirs")
        found = discover_books([p])
        if not found:
            return redirect(url_for("index", m=f"{p} không có book.yaml (trực tiếp hoặc trong thư mục con)") + "#dirs")
        key = str(p.resolve())
        if key not in extra_dirs and p.resolve() not in [d.resolve() for d in dirs]:
            extra_dirs.append(key)
            dirs.append(Path(key))
            save_dirs()
        bad = [b for b in found if b.get("error")]
        return redirect(url_for("index", m=f"Đã thêm {p}: {len(found)} sách" + (f", {len(bad)} lỗi book.yaml" if bad else "")) + "#dirs")

    @app.post("/books/add-dir")
    def add_dir():
        return _add_book_dir(request.form.get("path", ""))

    @app.post("/books/pick-dir")
    def pick_dir():
        try:
            chosen = _pick_folder()
        except Exception as exc:  # noqa: BLE001
            return redirect(url_for("index", m=f"Không mở được hộp thoại chọn thư mục ({str(exc)[:80]}); gõ đường dẫn vào ô bên cạnh") + "#dirs")
        return _add_book_dir(chosen) if chosen else redirect(url_for("index") + "#dirs")

    @app.post("/books/remove-dir")
    def remove_dir():
        raw = request.form.get("path", "").strip()
        key = str(Path(raw).resolve()) if raw else ""
        if key in extra_dirs:
            extra_dirs.remove(key)
            dirs[:] = [d for d in dirs if str(d.resolve()) != key]
            save_dirs()
            return redirect(url_for("index", m=f"Đã bỏ {raw} khỏi danh sách (không xoá file nào)") + "#dirs")
        return redirect(url_for("index", m="Thư mục này không bỏ được (mặc định của dự án)") + "#dirs")

    @app.post("/book/<int:idx>/open-folder")
    def open_folder(idx: int):
        entry, _ = book_at(idx)
        folder = Path(entry["path"]).parent
        try:
            _open_in_file_manager(folder)
        except Exception as exc:  # noqa: BLE001
            return redirect(url_for("index", m=f"Không mở được {folder}: {str(exc)[:80]}"))
        return redirect(request.referrer or url_for("book", idx=idx))

    @app.get("/book/<int:idx>")
    def book(idx: int):
        entry, b = book_at(idx)
        fmt = request.args.get("fmt") or b.formats[0]
        s = store()
        try:
            checklist = build_checklist(b, fmt, quota_status(s)[fmt])
            title_rows = [t for t in s.titles() if t["book_id"] == b.id]
        finally:
            s.close()
        art = artifacts_for(b, fmt)
        runs = sorted((p for p in runs_dir.glob(f"*-{b.id}-*") if p.is_dir()), reverse=True)[:5] if runs_dir.is_dir() else []
        return render_template("book.html", idx=idx, e=entry, b=b, fmt=fmt, checklist=checklist, art={k: (str(v) if v else None) for k, v in art.items()}, title_rows=title_rows, runs=[r.name for r in runs],
                               providers=["auto", "placeholder", "spec", "local", "pollinations", "cloudflare", "openai", "google", "stability"], is_coloring=isinstance(b.interior, ColoringInterior))

    @app.post("/book/<int:idx>/build")
    def build(idx: int):
        entry, _ = book_at(idx)
        cmd = [sys.executable, "-X", "utf8", "-m", "kdp_studio", "build", entry["path"]]
        if request.form.get("images"):
            cmd += ["--images", request.form["images"]]
        if request.form.get("reuse_raw"):
            cmd.append("--reuse-raw")
        job_id = jobs.start(f"build {entry['folder']}", cmd, book_idx=idx)
        return redirect(url_for("job", job_id=job_id))

    @app.post("/book/<int:idx>/image-test")
    def image_test(idx: int):
        entry, _ = book_at(idx)
        cmd = [sys.executable, "-X", "utf8", "-m", "kdp_studio", "image-test", entry["path"], "--n", request.form.get("n", "3")]
        if request.form.get("provider"):
            cmd += ["--provider", request.form["provider"]]
        job_id = jobs.start(f"image-test {entry['folder']}", cmd)
        return redirect(url_for("job", job_id=job_id))

    @app.post("/book/<int:idx>/publish")
    def publish_one(idx: int):
        entry, _ = book_at(idx)
        args = ["publish", "run", entry["path"], "--format", request.form.get("fmt", "paperback")]
        if request.form.get("resume_url"):
            args += ["--resume-url", request.form["resume_url"]]
        return render_template("console.html", command=_spawn_console(args), back=url_for("book", idx=idx))

    @app.get("/queue")
    def queue():
        s = store()
        try:
            items = s.queue_list(None if request.args.get("all") else "queued")
            quota = quota_status(s)
        finally:
            s.close()
        return render_template("queue.html", items=items, books=books(), quota=quota, formats=FORMATS)

    @app.post("/queue/add")
    def queue_add():
        selected = request.form.getlist("books")
        fmt = request.form.get("fmt", "paperback")
        priority = int(request.form.get("priority", "5") or 5)
        s = store()
        try:
            for path in selected:
                try:
                    b = load_book(path)
                except Exception:  # noqa: BLE001
                    continue
                if fmt in b.formats:
                    s.queue_add(str(Path(path).resolve()), fmt, priority=priority, book_id=b.id)
        finally:
            s.close()
        return redirect(url_for("queue"))

    @app.post("/queue/remove/<int:item_id>")
    def queue_remove(item_id: int):
        s = store()
        try:
            s.queue_remove(item_id)
        finally:
            s.close()
        return redirect(url_for("queue"))

    @app.post("/queue/run-next")
    def queue_run_next():
        return render_template("console.html", command=_spawn_console(["publish", "next"]), back=url_for("queue"))

    @app.get("/runs")
    def runs():
        rows = []
        if runs_dir.is_dir():
            for p in sorted((d for d in runs_dir.iterdir() if d.is_dir()), reverse=True)[:40]:
                flow = p / "flow.json"
                info = {"name": p.name, "status": "-", "filled": 0, "unfilled": 0, "shots": sorted(x.name for x in (p / "screenshots").glob("*.png")) if (p / "screenshots").is_dir() else []}
                if flow.is_file():
                    try:
                        d = json.loads(flow.read_text(encoding="utf-8"))
                        info.update(status=d.get("status"), filled=len(d.get("filled", [])), unfilled=len(d.get("unfilled", [])), notes=d.get("notes", [])[-2:])
                    except Exception:  # noqa: BLE001
                        pass
                rows.append(info)
        return render_template("runs.html", rows=rows)

    @app.get("/runs/<name>/<path:fname>")
    def run_file(name: str, fname: str):
        p = (runs_dir / name / fname).resolve()
        if not str(p).startswith(str(runs_dir.resolve())) or not p.is_file():
            abort(404)
        return send_file(str(p))

    @app.get("/file")
    def file_view():
        p = Path(request.args.get("p", "")).resolve()
        if not p.is_file() or p.suffix.lower() not in {".png", ".jpg", ".jpeg", ".pdf", ".md", ".json", ".txt"}:
            abort(404)
        allowed = [project_root().resolve(), *(d.resolve() for d in dirs)]
        if not any(str(p).startswith(str(a)) for a in allowed):
            abort(403)
        return send_file(str(p))

    @app.get("/jobs/<job_id>")
    def job(job_id: str):
        j = jobs.get(job_id)
        if j is None:
            abort(404)
        return render_template("job.html", job=j, idx=j.get("book_idx"))

    @app.get("/jobs/<job_id>/log")
    def job_log(job_id: str):
        j = jobs.get(job_id)
        if j is None:
            abort(404)
        return {"status": j["status"], "log": j["log"][-400:], "returncode": j["returncode"]}

    # ---------------------------------------------------------------- settings: API keys
    @app.get("/settings")
    def settings():
        from ..interior.failover import ProviderState, default_chain

        state = ProviderState().summary()
        return render_template("settings.html", providers=keymod.status_table(), env_file=str(keymod.env_path()), message=request.args.get("m"),
                               chain=default_chain(), chain_var=keymod.CHAIN_VAR, chain_setting=keymod.chain_setting(), state=state, state_by_id={s["id"]: s for s in state})

    @app.post("/settings/save")
    def settings_save():
        written = keymod.save_env({v: request.form.get(v, "") for v in keymod.all_var_names() if v in request.form})
        cleared = keymod.remove_env([keymod.CHAIN_VAR]) if keymod.CHAIN_VAR in request.form and not request.form.get(keymod.CHAIN_VAR, "").strip() else []
        msg = ("Đã lưu: " + ", ".join(written)) if written else ("Đã bỏ chuỗi tùy chỉnh, dùng chuỗi tự động" if cleared else "Không có key mới để lưu")
        return redirect(url_for("settings", m=msg))

    @app.post("/settings/check/<provider>")
    def settings_check(provider: str):
        try:
            n = int(request.args.get("n", 1))
        except ValueError:
            n = 1
        return keymod.check(provider, n)

    @app.post("/settings/unblock")
    def settings_unblock():
        from ..interior.failover import ProviderState

        pid = request.form.get("profile") or None
        ProviderState().clear(pid)
        return redirect(url_for("settings", m=f"Đã mở khóa {pid or 'tất cả tài khoản'}"))

    @app.post("/settings/remove")
    def settings_remove():
        prov = keymod.provider_by_id(request.form.get("provider", ""))
        n = int(request.form.get("n", "0") or 0)
        if prov is None or n < 2:
            abort(400)
        removed = keymod.remove_env([keymod.var_name(v, n) for v in prov["vars"]])
        return redirect(url_for("settings", m=("Đã xoá: " + ", ".join(removed)) if removed else "Không có gì để xoá"))

    # ---------------------------------------------------------------- create a new coloring book
    @app.get("/create")
    def create_form():
        from ..interior.failover import default_chain

        default = "auto" if default_chain() else "local"  # auto = every configured account, then the GPU; nothing configured -> the GPU alone
        return render_template("create.html", providers=["auto", "cloudflare", "local", "spec", "placeholder", "pollinations", "openai", "google", "stability"], default_provider=default, error=None)

    @app.post("/create")
    def create_book():
        from ..bookgen import new_coloring_book

        f = request.form
        try:
            path = new_coloring_book(
                root=app.config["BOOKS_ROOT"], folder=f.get("folder", ""), title=f.get("title", ""), subtitle=f.get("subtitle") or None, author=f.get("author", ""),
                theme=f.get("theme", ""), audience=f.get("audience") or "adults", images=int(f.get("images") or 30), trim=f.get("trim") or "8.5x11",
                price=float(f.get("price") or 9.99), provider=f.get("provider") or "local",
                keywords=[k.strip() for k in (f.get("keywords") or "").split(",") if k.strip()],
                subjects=[ln.strip() for ln in (f.get("subjects") or "").splitlines() if ln.strip()],
            )
        except Exception as exc:  # noqa: BLE001
            return render_template("create.html", providers=["auto", "local", "spec", "placeholder", "cloudflare", "pollinations", "openai", "google", "stability"], default_provider=f.get("provider") or "local", error=str(exc))
        if path.parent.parent not in dirs:
            dirs.append(path.parent.parent)
        for i, b in enumerate(books()):
            if Path(b["path"]).resolve() == path.resolve():
                return redirect(url_for("book", idx=i))
        return redirect(url_for("index"))

    @app.post("/create/suggest")
    def create_suggest():
        """Complete the rest of the create form around what was typed (Claude -> Cloudflare Workers AI -> offline library)."""
        from ..suggest import suggest

        data = request.get_json(silent=True) or request.form.to_dict()
        overwrite = str(data.get("overwrite", "")).lower() in ("1", "true", "on", "yes")
        try:
            return suggest(data, overwrite=overwrite)
        except Exception as exc:  # noqa: BLE001
            return {"error": str(exc)[:300]}, 500

    # ---------------------------------------------------------------- build progress (works for builds started anywhere)
    @app.get("/book/<int:idx>/progress")
    def progress(idx: int):
        _, b = book_at(idx)
        build = b.build_dir
        total = None
        if (build / "prompts.json").is_file():
            try:
                total = len(json.loads((build / "prompts.json").read_text(encoding="utf-8")))
            except Exception:  # noqa: BLE001
                total = None
        if total is None and isinstance(b.interior, ColoringInterior):
            total = b.interior.images
        # prompts.json is rewritten when a build starts: only files newer than it belong to the current build
        since = (build / "prompts.json").stat().st_mtime - 1 if (build / "prompts.json").is_file() else 0
        art = sorted((p for p in (build / "art").glob("*.png") if p.stat().st_mtime >= since), key=lambda p: p.stat().st_mtime) if (build / "art").is_dir() else []
        raw = [p for p in (build / "raw").glob("*.png") if p.stat().st_mtime >= since] if (build / "raw").is_dir() else []
        seconds = None
        if len(art) >= 2:
            seconds = round((art[-1].stat().st_mtime - art[0].stat().st_mtime) / (len(art) - 1), 1)
        manifest = (build / "interior_manifest.json").is_file()
        pdf = build / "interior.pdf"
        finished = manifest and pdf.is_file() and pdf.stat().st_mtime >= since and (not art or pdf.stat().st_mtime >= art[-1].stat().st_mtime)
        return {
            "total": total, "done": len(art), "attempts": len(raw), "retries": max(0, len(raw) - len(art)), "seconds_per_page": seconds,
            "finished": bool(finished), "pdf": url_for("file_view", p=str(pdf)) if pdf.is_file() else None,
            "cover": url_for("file_view", p=str(build / "cover_wrap.pdf")) if (build / "cover_wrap.pdf").is_file() else None,
            "thumbs": [url_for("file_view", p=str(p)) for p in art[-12:]],
            "updated": dt.datetime.fromtimestamp(art[-1].stat().st_mtime).strftime("%H:%M:%S") if art else None,
        }

    @app.get("/license")
    def license_page():
        info = _license_status()
        machine = None
        if info.get("available"):
            from .. import license as lic

            machine = lic.machine_id()
        return render_template("license.html", info=info, machine=machine, message=request.args.get("m"))

    @app.post("/license/activate")
    def license_activate():
        try:
            from .. import license as lic

            res = lic.activate(request.form.get("token", "").strip())
            msg = f"License active for {res.get('licensee')} until {res.get('expires', 'no expiry')}"
        except Exception as exc:  # noqa: BLE001
            msg = f"Activation failed: {exc}"
        return redirect(url_for("license_page", m=msg))

    return app


def serve(host: str = "127.0.0.1", port: int = 8765, book_dirs: list[Path] | None = None, open_browser: bool = True) -> int:
    app = create_app(book_dirs)
    url = f"http://{host}:{port}/"
    print(f"kdp-studio UI on {url}  (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=port, debug=False, use_reloader=False)
    return 0
