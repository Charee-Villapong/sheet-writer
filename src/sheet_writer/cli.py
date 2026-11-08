"""sheet-writer の CLI。

使い方:
    sheet-writer append --config <path> --target <名前> --row '<JSON配列>' [--row ...]
    sheet-writer check  --config <path> --target <名前> [--fix]

終了コード: 正常 0 / 違反あり・検証失敗などの異常 1 / 引数・設定の誤り 2。
"""

from __future__ import annotations

import argparse
import json
import sys

from sheet_writer.checker import check_sheet, fix_sheet
from sheet_writer.config import load_config
from sheet_writer.errors import VerificationError
from sheet_writer.gateway import CliGateway
from sheet_writer.writer import append_rows


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sheet-writer",
        description="見切れ防止書式を機械的に担保する Sheets 書き込み tool",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    append_parser = subparsers.add_parser("append", help="行を追加する")
    append_parser.add_argument("--config", required=True)
    append_parser.add_argument("--target", required=True)
    append_parser.add_argument(
        "--row",
        action="append",
        default=[],
        help="追加する行（JSON 配列）。複数行は繰り返し指定する",
    )

    check_parser = subparsers.add_parser("check", help="違反を検査する")
    check_parser.add_argument("--config", required=True)
    check_parser.add_argument("--target", required=True)
    check_parser.add_argument(
        "--fix",
        action="store_true",
        help="書式のみを自動修正する（値・数式には触らない）",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        print(f"設定を読み込めません: {exc}", file=sys.stderr)
        return 2
    target = config.targets.get(args.target)
    if target is None:
        print(f"対象が設定にありません: {args.target}", file=sys.stderr)
        return 2

    gateway = CliGateway()

    if args.command == "check":
        if args.fix:
            fixed = fix_sheet(gateway, target, config.measures)
            for violation in fixed:
                print(
                    f"修正: {violation.kind} {violation.location}: {violation.detail}"
                )
            print(f"書式の自動修正が完了しました（{len(fixed)} 件）")
            return 0
        violations = check_sheet(gateway, target, config.measures)
        for violation in violations:
            print(
                f"違反: {violation.kind} {violation.location}: "
                f"expected={violation.expected} actual={violation.actual} "
                f"({violation.detail})"
            )
        if violations:
            print(f"{len(violations)} 件の違反があります")
            return 1
        print("違反はありません")
        return 0

    rows: list[list[str]] = []
    for raw in args.row:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            print(f"--row の JSON が不正です: {raw}", file=sys.stderr)
            return 2
        if not isinstance(parsed, list):
            print(f"--row は JSON 配列で指定してください: {raw}", file=sys.stderr)
            return 2
        rows.append([str(cell) for cell in parsed])

    try:
        result = append_rows(gateway, target, rows, config.measures)
    except VerificationError as exc:
        print(f"書き込み後の検証に失敗しました: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"引数が不正です: {exc}", file=sys.stderr)
        return 2
    print(
        "追加しました: rows="
        + ",".join(str(r) for r in result.appended_rows)
        + " widths="
        + json.dumps(result.column_widths, ensure_ascii=False)
        + " heights="
        + json.dumps(result.row_heights, ensure_ascii=False)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
