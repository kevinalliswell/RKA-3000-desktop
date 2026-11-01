"""Freeze the Python backend with PyInstaller for the Windows x64 Tauri sidecar.

Produces build/backend/rka3000-backend.exe and copies it to
src-tauri/binaries/rka3000-backend-x86_64-pc-windows-msvc.exe (the name Tauri's externalBin
expects). Also collects licence texts into build/notices/.
"""

from __future__ import annotations

import importlib.metadata
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_TRIPLE = "x86_64-pc-windows-msvc"


def freeze(*, allow_non_windows: bool = False) -> Path:
    if not allow_non_windows and (sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}):
        raise SystemExit("The release sidecar requires Windows x64 Python; pass --allow-non-windows for local experiments.")
    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Use Python 3.12 for release builds (see requirements/build.txt).")
    dist = ROOT / "build" / "backend"
    if dist.exists():
        shutil.rmtree(dist)  # never mix old assets into a new build
    subprocess.run([
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--onefile", "--console", "--noupx", "--name", "rka3000-backend",
        "--distpath", str(dist),
        "--workpath", str(ROOT / "build" / "pyinstaller"),
        "--specpath", str(ROOT / "build"),
        "--paths", str(ROOT / "src"),
        "--collect-submodules", "rka_desktop",
        "--collect-data", "rka_desktop.infrastructure.comm._vendor",
        "--hidden-import", "pymodbus.client",
        "--hidden-import", "openpyxl.chart",
        "--exclude-module", "PySide6", "--exclude-module", "PyQt5", "--exclude-module", "PyQt6",
        "--exclude-module", "tkinter", "--exclude-module", "pandas", "--exclude-module", "numpy",
        "--exclude-module", "pytest", "--exclude-module", "ruff",
        str(ROOT / "scripts" / "backend_entry.py"),
    ], cwd=ROOT, check=True)
    exe = dist / ("rka3000-backend.exe" if sys.platform == "win32" else "rka3000-backend")
    binaries = ROOT / "src-tauri" / "binaries"
    binaries.mkdir(exist_ok=True)
    suffix = ".exe" if sys.platform == "win32" else ""
    triple = TARGET_TRIPLE if sys.platform == "win32" else _host_triple()
    target = binaries / f"rka3000-backend-{triple}{suffix}"
    shutil.copy2(exe, target)
    print(f"sidecar: {target}")
    return target


def _host_triple() -> str:
    machine = platform.machine().lower()
    arch = "aarch64" if machine in {"arm64", "aarch64"} else "x86_64"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def collect_notices() -> None:
    notices = ROOT / "build" / "notices"
    if notices.exists():
        shutil.rmtree(notices)
    notices.mkdir(parents=True)
    vendor = ROOT / "src/rka_desktop/infrastructure/comm/_vendor"
    for source, name in [
        (ROOT / "LICENSE", "APPLICATION-LICENSE.txt"),
        (ROOT / "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"),
        (vendor / "VENDOR.md", "VENDOR.md"),
    ]:
        shutil.copy2(source, notices / name)
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.is_file():
        shutil.copy2(python_license, notices / "PYTHON-LICENSE.txt")
    for dist_name in ("pyserial", "pymodbus", "openpyxl", "et_xmlfile", "pyinstaller"):
        try:
            distribution = importlib.metadata.distribution(dist_name)
        except importlib.metadata.PackageNotFoundError:
            continue
        for file in distribution.files or []:
            lower = file.name.lower()
            if lower.startswith(("license", "licence", "copying", "notice")):
                target = notices / f"{dist_name.upper()}-{file.name}"
                shutil.copy2(distribution.locate_file(file), target)
        version = distribution.version
        (notices / f"{dist_name}-VERSION.txt").write_text(f"{dist_name} {version}\n", encoding="utf-8")
    with (notices / "python-build-requirements.txt").open("w", encoding="utf-8") as output:
        subprocess.run([sys.executable, "-m", "pip", "freeze"], check=True, stdout=output)
    print(f"notices: {notices}")


def main() -> None:
    allow = "--allow-non-windows" in sys.argv
    freeze(allow_non_windows=allow)
    collect_notices()


if __name__ == "__main__":
    main()
