"""検査役: 既存シートの見切れ違反を検出し、書式のみを自動修正する。

検出する違反は5種:
- ``width``: fit 列で必要幅 > 現在幅。wrap 列も設定幅 > 現在幅なら対象
  （無条件: 現在幅が既定幅 100px の列や幅未設定の列も対象で、
  未設定は既定 100px として扱う）
- ``wrap``: 内容が列幅に収まらないのに WRAP が未設定
- ``row_height``: 推定必要行高 > 現在の行高
- ``background``: ``background_rule`` 有効時、データ行のセルに背景色が
  設定されている（ヘッダー行は対象外、白の明示設定も違反）
- ``checkbox``: ``checkbox_columns`` で列挙した列について、データ行の
  セルに真偽値が入っているのに BOOLEAN の入力規則がない
  （ヘッダー行・空セル・真偽値でないセルは対象外）

``fix_sheet`` は書式（列幅の拡大・WRAP 設定・行高の拡大）と入力規則
（チェックボックスの BOOLEAN 設定）のみを直す。値・数式には絶対に
触らない。
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

# 背景色とみなす userEnteredFormat のキー
_BACKGROUND_KEYS = ("backgroundColor", "backgroundColorStyle")

# チェックボックスとみなす入力規則（dataValidation の condition.type）
_CHECKBOX_RULE_TYPE = "BOOLEAN"


def _set_checkbox_request(sheet_id: int, row: int, col: int) -> dict:
    """チェックボックスの入力規則を設定するリクエスト。

    対象セルの dataValidation を BOOLEAN 条件で置き換えるだけであり、
    値・書式には触らない。
    """
    return {
        "setDataValidation": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row,
                "endRowIndex": row + 1,
                "startColumnIndex": col,
                "endColumnIndex": col + 1,
            },
            "rule": {
                "condition": {"type": _CHECKBOX_RULE_TYPE},
                "showCustomUi": True,
            },
        }
    }


def _clear_background_request(sheet_id: int, row: int, col: int) -> dict:
    """背景色の除去リクエスト。

    フィールドマスクに両キーを挙げ、cell には含めないことで、実 API の
    「マスクにあって cell に無いフィールドは削除される」意味論で除去する。
    他の書式キーには触らない。
    """
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row,
                "endRowIndex": row + 1,
                "startColumnIndex": col,
                "endColumnIndex": col + 1,
            },
            "cell": {"userEnteredFormat": {}},
            "fields": (
                "userEnteredFormat.backgroundColor,"
                "userEnteredFormat.backgroundColorStyle"
            ),
        }
    }


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


def _entered(state: SheetState, row: int, col: int) -> dict:
    entered_values = getattr(state, "entered_values", None) or []
    if row < len(entered_values) and col < len(entered_values[row]):
        cell = entered_values[row][col]
        return cell if isinstance(cell, dict) else {}
    return {}


def _validation_type(state: SheetState, row: int, col: int) -> str | None:
    """セルの入力規則の condition.type。規則がなければ None。"""
    validations = getattr(state, "data_validations", None) or []
    if row < len(validations) and col < len(validations[row]):
        validation = validations[row][col]
        if isinstance(validation, dict):
            condition = validation.get("condition")
            if isinstance(condition, dict):
                rule_type = condition.get("type")
                if isinstance(rule_type, str):
                    return rule_type
    return None


def _has_boolean_value(state: SheetState, row: int, col: int) -> bool:
    """セルに真偽値が入っているか。

    boolValue の入力があるか、表示値が "TRUE" / "FALSE" のいずれか。
    文字列として打たれた "FALSE" も、チェックボックス列では真偽値の
    つもりの入力であり、入力規則の欠落は同じ不整合として扱う。
    """
    if "boolValue" in _entered(state, row, col):
        return True
    return _cell(state, row, col) in ("TRUE", "FALSE")


def _n_cols(state: SheetState) -> int:
    return max([len(row) for row in state.values] + [len(state.column_widths)] + [0])


def _scope_row_count(state: SheetState, target: Target) -> int:
    """検査対象の行数（ヘッダー行を含む）。

    ``append_anchor_column`` 設定時は「anchor 列に値のある最終行」までを
    対象とし、それより下の行（他列に事前設定値のみの行など）は対象外。
    未設定時は全行が対象。
    """
    if not target.append_anchor_column:
        return len(state.values)
    anchor_col = column_index(target.append_anchor_column)
    last = 0
    for row in range(len(state.values)):
        if _cell(state, row, anchor_col) != "":
            last = row + 1
    return last


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
    n_rows = _scope_row_count(state, target)
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
        if policy.mode == "wrap":
            policy_width = policy.width_px or m.default_wrap_width_px
            actual_width = _width(state, col)
            # 無条件に判定する: 既定幅 100px の列・幅未設定（既定扱い）の
            # 列も、設定幅未満なら幅違反にする
            if actual_width < policy_width:
                violations.append(
                    Violation(
                        kind="width",
                        location=letter,
                        expected=policy_width,
                        actual=actual_width,
                        detail=(
                            f"列 {letter} の幅 {actual_width}px が"
                            f"設定幅 {policy_width}px 未満"
                        ),
                    )
                )
            continue
        if policy.mode != "fit":
            continue
        data_texts = [_cell(state, r, col) for r in range(1, n_rows)]
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

    for row in range(1, n_rows):
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

    if target.background_rule:
        for row in range(1, n_rows):
            for col in range(n_cols):
                fmt = _format(state, row, col)
                found = next((key for key in _BACKGROUND_KEYS if key in fmt), None)
                if found is None:
                    continue
                letter = column_letter(col)
                violations.append(
                    Violation(
                        kind="background",
                        location=f"{letter}{row + 1}",
                        expected="未設定",
                        actual=fmt[found],
                        detail=(
                            f"セル {letter}{row + 1} に背景色（{found}）が"
                            "設定されている"
                        ),
                    )
                )

    for letter in target.checkbox_columns:
        col = column_index(letter)
        for row in range(1, n_rows):
            if not _has_boolean_value(state, row, col):
                continue
            actual_type = _validation_type(state, row, col)
            if actual_type == _CHECKBOX_RULE_TYPE:
                continue
            violations.append(
                Violation(
                    kind="checkbox",
                    location=f"{letter}{row + 1}",
                    expected=_CHECKBOX_RULE_TYPE,
                    actual=actual_type or "未設定",
                    detail=(
                        f"セル {letter}{row + 1} に真偽値が入っているが"
                        "チェックボックス（BOOLEAN）の入力規則がない"
                    ),
                )
            )

    for row in range(1, n_rows):
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
    """違反を書式と入力規則のみで修正し、修正した違反を返す。

    値・数式には触らない。
    """
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
        elif violation.kind == "background":
            letter = "".join(ch for ch in str(violation.location) if ch.isalpha())
            number = "".join(ch for ch in str(violation.location) if ch.isdigit())
            col = column_index(letter)
            row = int(number) - 1
            requests.append(_clear_background_request(sheet_id, row, col))
        elif violation.kind == "checkbox":
            letter = "".join(ch for ch in str(violation.location) if ch.isalpha())
            number = "".join(ch for ch in str(violation.location) if ch.isdigit())
            col = column_index(letter)
            row = int(number) - 1
            requests.append(_set_checkbox_request(sheet_id, row, col))

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
