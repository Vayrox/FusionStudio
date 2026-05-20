"""
FusionStudio launcher.

Double-click entrypoint: starts the FastAPI server, waits until /healthz
responds, then opens the dashboard in the default browser. Keeps running
until the console window is closed (or Ctrl+C).

Used both for normal `python fusion_studio.py` and for the PyInstaller
.exe build (see build_exe.bat).
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import uvicorn


HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"


def _is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def _exe_dir() -> Path:
    """Directory of the .exe (frozen) or the script (dev)."""
    if _is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _bundle_dir() -> Path:
    """Directory of bundled read-only resources at runtime."""
    if _is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def _data_dir() -> Path:
    """Persistent user-data directory.

    Frozen build (.exe): uses ``<exe folder>/data/`` so it lives alongside the
    application — portable and visible inside the project folder. The build
    script (build.py) preserves this directory across PyInstaller rebuilds.

    Dev mode (running from the repo): keeps the legacy flat layout (output/,
    pokemon_refs/, .env right at the repo root) so the existing workflow
    isn't disrupted.
    """
    if not _is_frozen():
        return Path(__file__).resolve().parent
    return _exe_dir() / "data"


def _migrate_legacy_data(data_dir: Path) -> None:
    """Move user data from older layouts into the canonical location.

    Three legacy locations are checked, in order of precedence:
      1) %APPDATA%\\FusionStudio\\        (intermediate persistent build)
      2) <exe_dir>/<name>                  (very first persistent build, flat)

    Runs at most once per machine for each — afterwards the source dirs no
    longer exist so subsequent runs short-circuit.
    """
    if not _is_frozen():
        return
    sources: list[Path] = []
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            sources.append(Path(appdata) / "FusionStudio")
    else:
        sources.append(Path.home() / ".fusionstudio")
    sources.append(_exe_dir())

    moved_any = False
    for src_root in sources:
        if not src_root.exists() or src_root == data_dir:
            continue
        for name in (".env", "output", "pokemon_refs", ".state", "assets"):
            src = src_root / name
            dst = data_dir / name
            if not src.exists():
                continue
            # Skip if destination already has user content.
            if dst.exists():
                if dst.is_dir() and any(dst.iterdir()):
                    continue
                if dst.is_file():
                    continue
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
                if dst.exists():
                    # Empty dir created by _ensure_data_dirs — remove and replace.
                    try:
                        dst.rmdir()
                    except OSError:
                        pass
                shutil.move(str(src), str(dst))
                print(f"[fusion-studio] Migrated {name} from {src_root}")
                moved_any = True
            except Exception as exc:  # noqa: BLE001
                print(f"[fusion-studio] Could not migrate {name} from {src_root}: {exc}")
    if moved_any:
        print(f"[fusion-studio] All user data is now in {data_dir}")


def _ensure_data_dirs(root: Path) -> None:
    """Create persistent folders and seed first-run files."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "output").mkdir(parents=True, exist_ok=True)
    (root / "pokemon_refs").mkdir(parents=True, exist_ok=True)
    (root / ".state").mkdir(parents=True, exist_ok=True)

    # Seed .env from .env.example if missing (so config.update() can write to it).
    env_path = root / ".env"
    env_example = _bundle_dir() / ".env.example"
    if not env_path.exists() and env_example.exists():
        shutil.copy2(env_example, env_path)

    # If user has not placed signature_background.png, copy the bundled one
    # (if any) so first-run pipelines have something to work with.
    sig_dst = root / "assets" / "signature_background.png"
    sig_src = _bundle_dir() / "assets" / "signature_background.png"
    if not sig_dst.exists() and sig_src.exists():
        shutil.copy2(sig_src, sig_dst)


def _wait_for_server(timeout_s: float = 30.0) -> bool:
    """Poll /healthz until it responds or timeout. Returns True on success."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{URL}/healthz", timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except (URLError, ConnectionError, OSError):
            pass
        time.sleep(0.25)
    return False


def _open_browser_when_ready() -> None:
    if _wait_for_server():
        try:
            webbrowser.open(URL, new=2)
        except Exception as exc:  # noqa: BLE001
            print(f"[fusion-studio] Could not auto-open browser: {exc}")
            print(f"[fusion-studio] Open manually: {URL}")
    else:
        print(f"[fusion-studio] Server did not become ready in time. Open manually: {URL}")


def main() -> int:
    data_dir = _data_dir()
    _migrate_legacy_data(data_dir)
    _ensure_data_dirs(data_dir)

    # Tell config.py where writable storage lives. Read by backend/config.py.
    os.environ["FUSIONSTUDIO_DATA_DIR"] = str(data_dir)
    os.environ["FUSIONSTUDIO_BUNDLE_DIR"] = str(_bundle_dir())

    # Import AFTER setting env vars so config.py picks them up.
    from backend.server import app  # noqa: E402

    print("=" * 60)
    print(" FusionStudio")
    print(f" Server:        {URL}")
    print(f" Data folder:   {data_dir}")
    print("=" * 60)
    print(" Browser will open automatically once the server is ready.")
    print(" Settings, jobs and outputs persist across .exe updates.")
    print(" Close this window (or press Ctrl+C) to stop the server.")
    print()

    # Open the browser in a background thread once /healthz responds.
    threading.Thread(target=_open_browser_when_ready, daemon=True).start()

    # Run uvicorn in the foreground (blocks until shutdown).
    config = uvicorn.Config(
        app,
        host=HOST,
        port=PORT,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
