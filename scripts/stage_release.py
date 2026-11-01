"""Stage the portable directory, portable ZIP, NSIS installer and SHA256SUMS.txt."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    name = f"RKA3000-desktop_{version}_windows-x64"
    release = ROOT / "src-tauri" / "target" / "release"
    portable = ROOT / "build" / "portable" / name
    assets = ROOT / "dist" / "release"
    if portable.exists() or assets.exists():
        raise SystemExit("build/portable and dist/release must not exist: clean them so old assets are never mixed in.")
    portable.mkdir(parents=True)
    assets.mkdir(parents=True)
    shutil.copy2(release / "rka3000-desktop.exe", portable)
    shutil.copy2(ROOT / "src-tauri/binaries/rka3000-backend-x86_64-pc-windows-msvc.exe", portable / "rka3000-backend.exe")
    shutil.copytree(ROOT / "build/notices", portable / "notices")
    for source in ["LICENSE", "README.md", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"]:
        shutil.copy2(ROOT / source, portable)
    (portable / "START-HERE.txt").write_text(
        f"RKA-3000 实验系统 / RKA-3000 experiment system {version}\n\n"
        "解压整个 ZIP 后运行 rka3000-desktop.exe；rka3000-backend.exe 必须与主程序同目录。\n"
        "Extract the whole ZIP, then run rka3000-desktop.exe. Keep rka3000-backend.exe next to it.\n"
        "无需安装 Python / Node.js / Rust。需要 Windows 10/11 x64 和 Microsoft Edge WebView2 Runtime。\n"
        "Python, Node.js and Rust are not required. Windows 10/11 x64 and WebView2 Runtime are.\n"
        "WebView2: https://developer.microsoft.com/microsoft-edge/webview2/\n"
        "用户数据、配置与日志 / user data, config and logs: %LOCALAPPDATA%\\RKA3000\\\n"
        "本程序未签名 / The application is unsigned. See README.md.\n",
        encoding="utf-8")
    with zipfile.ZipFile(assets / f"{name}_portable.zip", "w", zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(portable.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(portable.parent))
    installers = list((release / "bundle" / "nsis").glob("*-setup.exe"))
    if len(installers) != 1:
        raise SystemExit(f"Expected exactly one NSIS installer, got {installers}")
    shutil.copy2(installers[0], assets / f"{name}_setup.exe")
    checksums = []
    for file in sorted(assets.iterdir()):
        with file.open("rb") as stream:
            checksums.append(f"{hashlib.file_digest(stream, 'sha256').hexdigest()}  {file.name}")
    (assets / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(f"Release assets: {assets}")
    print(f"Portable executable: {portable / 'rka3000-desktop.exe'}")


if __name__ == "__main__":
    main()
