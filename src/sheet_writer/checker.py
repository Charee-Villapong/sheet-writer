"""検査役: 既存シートの見切れ違反を検出し、書式のみを自動修正する。

検出する違反は3種:
- ``width``: fit 列で必要幅 > 現在幅
- ``wrap``: 内容が列幅に収まらないのに WRAP が未設定
- ``row_height``: 推定必要行高 > 現在の行高

``fix_sheet`` は書式（列幅の拡大・WRAP 設定・行高の拡大）のみを直す。
値・数式には絶対に触らない。
"""

from __future__ import annotations

from dataclasses import dataclass

from sheet_writer import measures as mz
from sheet_writer.config import Measures, Target
from sheet_writer.gateway import SheetsGateway, SheetState
from sheet_writer.writer import (
    _dimension_request,
    _format_request,
    _policy_for,
    column_index,
    column_letter,
)

_DEFAULT_WIDTH_PX = 100
_DEFAULT_HEIGHT_PX = 21


@dataclass
class Violation:
    kind: str
    location: str
    expected: object
    actual: object
    detail: str = ""


def _width(state: SheetState, col: int) -> int:
    if col < len(state.column_widths) and state.column_widths[col] is not None:
        return int(state.column_widths[col])
    return _DEFAULT_WIDTH_PX


def _height(state: SheetState, row: int) -> int:
    if row < len(state.row_heights) and state.row_heights[row] is not None:
        return int(state.row_heights[row])
    return _DEFAULT_HEIGHT_PX


def _cell(state: SheetState, row: int, col: int) -> str:
    if row < len(state.values) and col < len(state.values[row]):
        return state.values[row][col]
    return ""


def _format(state: SheetState, row: int, col: int) -> dict:
    if row < len(state.cell_formats) and col < len(state.cell_formats[row]):
        return state.cell_formats[row][col]
    return {}


def _n_cols(state: SheetState) -> int:
    return max([len(row) for row in state.values] + [len(state.column_widths)] + [0])


def _display_lines(state: SheetState, row: int, col: int, m: Measures) -> int:
    """表示行数の推定。WRAP 有効時は折り返し行数、無効時は改行数だけ数える。"""
    text = _cell(state, row, col)
    if text == "":
        return 1
    if _format(state, row, col).get("wrapStrategy") == "WRAP":
        return mz.cell_lines(text, _width(state, col), m=m)
    return text.count("\n") + 1


def _segment_overflows(state: SheetState, row: int, col: int, m: Measures) -> bool:
    text = _cell(state, row, col)
    if text == "":
        return False
    usable = max(_width(state, col) - m.padding_px, 1)
    return any(mz.text_width_px(segment, m=m) > usable for segment in text.split("\n"))


def check_sheet(gateway: SheetsGateway, target: Target, m: Measures) -> list[Violation]:
    """違反を検出する。読み取りのみで、状態は一切変更しない。"""
    state = gateway.get_state(target.spreadsheet_id, target.tab)
    n_cols = _n_cols(state)
    violations: list[Violation] = []

    if state.values:
        actual_header_height = _height(state, 0)
        if actual_header_height < m.header_height_px:
            violations.append(
                Violation(
                    kind="row_height",
                    location="1行目",
                    expected=m.header_height_px,
                    actual=actual_header_height,
                    detail=(
                        f"1行目（ヘッダー）の行高 {actual_header_height}px が"
                        f"担保値 {m.header_height_px}px 未満"
                    ),
                )
            )

    header = state.values[0] if state.values else []
    for col in range(n_cols):
        letter = column_letter(col)
        policy = _policy_for(target, letter)
        if policy.mode != "fit":
            continue
        data_texts = [_cell(state, r, col) for r in range(1, len(state.values))]
        needed = max(
            mz.needed_width_px(
                [header[col] if col < len(header) else ""], bold=True, m=m
            ),
            mz.needed_width_px(data_texts, m=m),
        )
        actual = _width(state, col)
        if needed > actual:
            violations.append(
                Violation(
                    kind="width",
                    location=letter,
                    expected=needed,
                    actual=actual,
                    detail=f"列 {letter} の必要幅 {needed}px が現在幅 {actual}px を超過",
                )
            )

    for row in range(1, len(state.values)):
        for col in range(n_cols):
            if not _segment_overflows(state, row, col, m):
                continue
            strategy = _format(state, row, col).get("wrapStrategy")
            if strategy != "WRAP":
                letter = column_letter(col)
                violations.append(
                    Violation(
                        kind="wrap",
                        location=f"{letter}{row + 1}",
                        expected="WRAP",
                        actual=strategy or "未設定",
                        detail=(
                            f"セル {letter}{row + 1} の内容が列幅に収まらないが"
                            "折り返しが未設定"
                        ),
                    )
                )

    for row in range(1, len(state.values)):
        if not any(_cell(state, row, col) != "" for col in range(n_cols)):
            continue  # 内容のない行は見切れの対象外（グリッドの残り行など）
        lines = max(
            (_display_lines(state, row, col, m) for col in range(n_cols)),
            default=1,
        )
        needed_height = mz.row_height_px(lines, m)
        actual_height = _height(state, row)
        if needed_height > actual_height:
            violations.append(
                Violation(
                    kind="row_height",
                    location=f"{row + 1}行目",
                    expected=needed_height,
                    actual=actual_height,
                    detail=(
                        f"{row + 1}行目の推定必要行高 {needed_height}px が"
                        f"現在の {actual_height}px を超過"
                    ),
                )
            )

    return violations


def fix_sheet(gateway: SheetsGateway, target: Target, m: Measures) -> list[Violation]:
    """違反を書式のみで修正し、修正した違反を返す。値・数式には触らない。"""
    violations = check_sheet(gateway, target, m)
    if not violations:
        return []

    state = gateway.get_state(target.spreadsheet_id, target.tab)
    sheet_id = state.sheet_id
    requests: list[dict] = []

    grown_columns: set[int] = set()
    for violation in violations:
        if violation.kind == "width":
            col = column_index(str(violation.location))
            if col not in grown_columns:
                requests.append(
                    _dimension_request(
                        sheet_id, "COLUMNS", col, int(violation.expected)
                    )
                )
                grown_columns.add(col)
        elif violation.kind == "wrap":
            letter = "".join(ch for ch in str(violation.location) if ch.isalpha())
            number = "".join(ch for ch in str(violation.location) if ch.isdigit())
            col = column_index(letter)
            row = int(number) - 1
            policy = _policy_for(target, letter)
            if policy.mode == "wrap" and col not in grown_columns:
                final = max(
                    _width(state, col),
                    policy.width_px or m.default_wrap_width_px,
                )
                if final > _width(state, col):
                    requests.append(_dimension_request(sheet_id, "COLUMNS", col, final))
                grown_columns.add(col)
            requests.append(
                _format_request(sheet_id, row, col, {"wrapStrategy": "WRAP"})
            )

    if requests:
        gateway.batch_update(target.spreadsheet_id, requests)

    # 幅・折り返しの修正後に残る行高不足を、最終状態で再計算して直す
    remaining = check_sheet(gateway, target, m)
    height_requests: list[dict] = []
    fixed_rows: set[int] = set()
    for violation in remaining:
        if violation.kind != "row_height":
            continue
        number = "".join(ch for ch in str(violation.location) if ch.isdigit())
        row = int(number) - 1
        if row in fixed_rows:
            continue
        height_requests.append(
            _dimension_request(sheet_id, "ROWS", row, int(violation.expected))
        )
        fixed_rows.add(row)
    if height_requests:
        gateway.batch_update(target.spreadsheet_id, height_requests)

    return violations
