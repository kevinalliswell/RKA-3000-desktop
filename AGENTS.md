# Repository Instructions

- Any branch merge must include a README update in the same change set.
- Keep the README aligned with shipped behavior, workflows, and developer setup.
- Layering is enforced by `tests/test_layering.py`: `domain/` has no I/O, `application/` depends only on
  `domain/` and its own `ports.py`, and only `bootstrap.py` wires concrete infrastructure.
- Business rules (recipe limits, step completion, alarm handling, control-mode switching) live in Python.
  Svelte and Rust never re-implement them; the Rust shell only manages the sidecar and the IPC allow-list.
- Bump versions with `python scripts/release.py bump <version>` and verify with `python scripts/check_version.py`.
