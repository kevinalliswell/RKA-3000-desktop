# Third-party notices

The application licence is in `LICENSE`. Third-party components keep their own licences; exact
dependency versions are recorded in `frontend/package-lock.json`, `src-tauri/Cargo.lock` and the
`notices/python-build-requirements.txt` file shipped with every release.

| Component | Licence / source |
|---|---|
| CPython runtime and standard library | PSF-2.0; `notices/PYTHON-LICENSE.txt` |
| pyserial | BSD-3-Clause; https://github.com/pyserial/pyserial |
| pymodbus | BSD-3-Clause; https://github.com/pymodbus-dev/pymodbus |
| openpyxl, et_xmlfile | MIT; https://foss.heptapod.net/openpyxl/openpyxl |
| PyInstaller bootloader | GPL-2.0-or-later with the distribution exception; https://pyinstaller.org/en/stable/license.html |
| Tauri / wry / tao and Rust dependencies | MIT OR Apache-2.0 and others; full texts in `notices/rust-licenses.html` |
| Svelte, Vite and frontend dependencies | MIT and others; `notices/frontend-licenses.json` |
| Azbil MFC CPL driver (vendored) | MIT; see `src/rka_desktop/infrastructure/comm/_vendor/VENDOR.md` |
| TAIE temperature controller driver (vendored) | Apache-2.0; see `VENDOR.md` |
| Balance serial driver (vendored) | Same-owner authorisation; see `VENDOR.md` |

PyInstaller's distribution exception permits bundling a proprietary application; it does not
change the application's licence. Licence texts found in the installed Python packages are copied
into `notices/` by `scripts/build_backend.py`; Rust and frontend licences by `scripts/collect_notices.py`.
