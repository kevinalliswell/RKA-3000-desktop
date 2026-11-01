"""Command-line adapter reusing the same application services as the desktop API."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from rka_desktop import __version__
from rka_desktop.bootstrap import build_container, import_legacy_database, load_config
from rka_desktop.infrastructure.logging_setup import setup_logging
from rka_desktop.infrastructure.paths import AppPaths


def _container(args: argparse.Namespace):
    paths = AppPaths(args.data_dir).ensure()
    config, notes = load_config(paths, legacy_env=args.legacy_env)
    setup_logging(paths.backend_log_file, console=False)
    return build_container(config, paths, notes=notes)


def _wait_task(container, task: dict, timeout: float = 60.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = container.tasks.get(task["id"])
        if current and current["status"] in {"completed", "failed", "cancelled"}:
            return current
        time.sleep(0.05)
    raise SystemExit("任务超时")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rka3000", description=f"RKA-3000 业务命令行 v{__version__}")
    parser.add_argument("--data-dir", type=Path, help="用户数据目录")
    parser.add_argument("--legacy-env", type=Path, help="首次运行时导入的旧 .env")
    sub = parser.add_subparsers(dest="command", required=True)

    api = sub.add_parser("api", help="启动本地 JSON API（桌面壳使用）")
    api.add_argument("--port", type=int, default=0)
    api.add_argument("--exit-on-stdin-eof", action="store_true")

    sub.add_parser("paths", help="显示数据目录、数据库、日志位置")

    legacy = sub.add_parser("import-legacy-db", help="把旧版 data/rka.db 复制到新的用户数据目录")
    legacy.add_argument("database", type=Path)

    recipes = sub.add_parser("recipes", help="列出配方或导入/导出配方 JSON")
    recipes.add_argument("action", choices=["list", "export", "import"])
    recipes.add_argument("--id", type=int)
    recipes.add_argument("--file", type=Path)

    export = sub.add_parser("export", help="导出实验数据到用户数据目录的 exports/")
    export.add_argument("experiment_id", type=int)
    export.add_argument("--kind", choices=["measurements_csv", "measurements_xlsx", "summary_csv"], default="measurements_csv")

    kinetics = sub.add_parser("kinetics", help="计算失重法还原度并输出 JSON")
    kinetics.add_argument("experiment_id", type=int)
    kinetics.add_argument("--m0", type=float)
    kinetics.add_argument("--tfe", type=float)
    kinetics.add_argument("--feo", type=float, default=0.0)
    kinetics.add_argument("--report", action="store_true", help="同时生成 Excel 报告")

    args = parser.parse_args(argv)

    if args.command == "api":
        from rka_desktop.adapters.api.server import run_server

        return run_server(port=args.port, data_dir=args.data_dir, exit_on_stdin_eof=args.exit_on_stdin_eof,
                          legacy_env=args.legacy_env)

    if args.command == "import-legacy-db":
        paths = AppPaths(args.data_dir).ensure()
        print(json.dumps(import_legacy_database(paths, args.database), ensure_ascii=False, indent=2))
        return 0

    container = _container(args)
    try:
        if args.command == "paths":
            print(json.dumps(container.health(), ensure_ascii=False, indent=2))
        elif args.command == "recipes":
            if args.action == "list":
                print(json.dumps(container.recipes.list_recipes(), ensure_ascii=False, indent=2))
            elif args.action == "export":
                if args.id is None:
                    parser.error("export 需要 --id")
                document = container.recipes.export_recipe(args.id)
                text = json.dumps(document, ensure_ascii=False, indent=2)
                if args.file:
                    args.file.write_text(text, encoding="utf-8")
                else:
                    print(text)
            else:
                if args.file is None:
                    parser.error("import 需要 --file")
                document = json.loads(args.file.read_text(encoding="utf-8"))
                print(json.dumps(container.recipes.import_recipe(document), ensure_ascii=False, indent=2))
        elif args.command == "export":
            task = _wait_task(container, container.history.start_export(args.kind, args.experiment_id))
            print(json.dumps(task, ensure_ascii=False, indent=2))
            return 0 if task["status"] == "completed" else 2
        elif args.command == "kinetics":
            payload = None
            if args.m0 is not None or args.tfe is not None:
                payload = {"initial_mass_g": args.m0, "tfe_pct": args.tfe, "feo_pct": args.feo}
            result = container.analysis.compute(args.experiment_id, payload)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            if args.report:
                task = _wait_task(container, container.analysis.start_report(args.experiment_id, payload))
                print(json.dumps(task, ensure_ascii=False, indent=2), file=sys.stderr)
                return 0 if task["status"] == "completed" else 2
        return 0
    finally:
        container.close()


if __name__ == "__main__":
    raise SystemExit(main())
