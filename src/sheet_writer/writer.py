"""書き込み tool: 行追加と書式の機械的担保。

列幅・折り返し・行高・上の行からの書式継承を計算して適用し、書き込み後に
読み戻して検証する。検証で意図と実状態が一致しなければ
:class:`~sheet_writer.errors.VerificationError` を送出し、黙って成功にしない。
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass
from datetime import date, datetime

from sheet_writer import measures as mz
from sheet_writer.config import ColumnPolicy, Measures, Target
from sheet_writer.errors import VerificationError
from sheet_writer.gateway import SheetsGateway, SheetState

# 継承してよい書式キー（API の出力専用キーは送り返さない）
_INHERIT_KEYS = (
    "backgroundColor",
    "horizontalAlignment",
    "verticalAlignment",
    "numberFormat",
    "wrapStrategy",
)
_TEXT_FORMAT_KEYS = ("bold", "italic", "fontSize", "fontFamily")
# 検証で突き合わせる書式キー
_VERIFY_FORMAT_KEYS = (
    "backgroundColor",
    "horizontalAlignment",
    "verticalAlignment",
    "numberFormat",
    "wrapStrategy",
)

# Sheets のシリアル値の起点（1899-12-30）
_SERIAL_EPOCH = date(1899, 12, 30)
_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
)
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d")
_TIME_FORMATS = ("%H:%M:%S", "%H:%M")


def _serial_value(text: str) -> float | None:
    """日付・日時・時刻文字列を Sheets のシリアル値へ変換する。"""
    for fmt in _DATETIME_FORMATS:
        try:
            parsed_dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        seconds = parsed_dt.hour * 3600 + parsed_dt.minute * 60 + parsed_dt.second
        return (parsed_dt.date() - _SERIAL_EPOCH).days + seconds / 86400
    for fmt in _DATE_FORMATS:
        try:
            parsed_dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        return float((parsed_dt.date() - _SERIAL_EPOCH).days)
    for fmt in _TIME_FORMATS:
        try:
            parsed_dt = datetime.strptime(text, fmt)
        except ValueError:
            continue
        seconds = parsed_dt.hour * 3600 + parsed_dt.minute * 60 + parsed_dt.second
        return seconds / 86400
    return None


def _number_value_matches(expected: str, number_value: object) -> bool:
    try:
        actual_number = float(number_value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    try:
        expected_number = float(expected.replace(",", ""))
    except ValueError:
        expected_number = None
    if expected_number is not None:
        return math.isclose(expected_number, actual_number, rel_tol=1e-9, abs_tol=1e-9)
    serial = _serial_value(expected)
    if serial is not None:
        return math.isclose(serial, actual_number, rel_tol=0.0, abs_tol=1e-7)
    return False


def _entered_value_matches(expected: str, entered: dict) -> bool:
    """userEnteredValue が書き込み文字列と同じ値を表すかを判定する。"""
    if not entered:
        return False
    if "formulaValue" in entered:
        return entered["formulaValue"] == expected
    if "stringValue" in entered:
        return entered["stringValue"] == expected
    if "boolValue" in entered:
        bool_text = "TRUE" if entered["boolValue"] else "FALSE"
        return expected.upper() == bool_text
    if "numberValue" in entered:
        return _number_value_matches(expected, entered["numberValue"])
    return False


def _entered_at(state: SheetState, row: int, col: int) -> dict:
    entered_values = getattr(state, "entered_values", None) or []
    if row < len(entered_values) and col < len(entered_values[row]):
        cell = entered_values[row][col]
        return cell if isinstance(cell, dict) else {}
    return {}


def column_letter(index0: int) -> str:
    letter = ""
    index0 += 1
    while index0:
        index0, rem = divmod(index0 - 1, 26)
        letter = chr(ord("A") + rem) + letter
    return letter


def column_index(letter: str) -> int:
    index = 0
    for ch in letter:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


@dataclass
class AppendResult:
    appended_rows: list[int]
    column_widths: dict[str, int]
    row_heights: dict[int, int]


def _policy_for(target: Target, letter: str) -> ColumnPolicy:
    return target.columns.get(letter, ColumnPolicy(mode="fit"))


def _current_width(state: SheetState, col: int) -> int:
    if col < len(state.column_widths):
        width = state.column_widths[col]
        if width is not None:
            return width
    return 0


def compute_column_widths(
    state: SheetState,
    target: Target,
    new_rows: list[list[str]],
    m: Measures,
    n_cols: int,
) -> dict[str, int]:
    """最終列幅を求める。ヘッダーは太字で計測し、現在より縮めることはしない。"""
    widths: dict[str, int] = {}
    header = state.values[0] if state.values else []
    data_rows = list(state.values[1:]) + [list(row) for row in new_rows]
    for col in range(n_cols):
        letter = column_letter(col)
        policy = _policy_for(target, letter)
        current = _current_width(state, col)
        if policy.mode == "wrap":
            policy_width = policy.width_px or m.default_wrap_width_px
            widths[letter] = max(current, policy_width)
        else:
            header_text = header[col] if col < len(header) else ""
            data_texts = [row[col] if col < len(row) else "" for row in data_rows]
            needed = max(
                mz.needed_width_px([header_text], bold=True, m=m),
                mz.needed_width_px(data_texts, m=m),
            )
            widths[letter] = max(current, needed)
    return widths


def _inherit_format(fmt: dict) -> dict:
    """上の行の userEnteredFormat から、設定可能なキーだけを引き継ぐ。"""
    inherited: dict = {}
    for key in _INHERIT_KEYS:
        if key in fmt:
            inherited[key] = copy.deepcopy(fmt[key])
    text_format = fmt.get("textFormat")
    if isinstance(text_format, dict):
        kept = {
            key: copy.deepcopy(text_format[key])
            for key in _TEXT_FORMAT_KEYS
            if key in text_format
        }
        if kept:
            inherited["textFormat"] = kept
    return inherited


def _backgrounds(formats: list[list[dict]], row: int, n_cols: int) -> list:
    if row < 0 or row >= len(formats):
        return [None] * n_cols
    return [
        formats[row][col].get("backgroundColor") if col < len(formats[row]) else None
        for col in range(n_cols)
    ]


def _dimension_request(
    sheet_id: int, dimension: str, index: int, pixel_size: int
) -> dict:
    return {
        "updateDimensionProperties": {
            "range": {
                "sheetId": sheet_id,
                "dimension": dimension,
                "startIndex": index,
                "endIndex": index + 1,
            },
            "properties": {"pixelSize": pixel_size},
            "fields": "pixelSize",
        }
    }


def _format_request(sheet_id: int, row: int, col: int, fmt: dict) -> dict:
    fields = "userEnteredFormat(" + ",".join(fmt.keys()) + ")"
    return {
        "repeatCell": {
            "range": {
                "sheetId": sheet_id,
                "startRowIndex": row,
                "endRowIndex": row + 1,
                "startColumnIndex": col,
                "endColumnIndex": col + 1,
            },
            "cell": {"userEnteredFormat": fmt},
            "fields": fields,
        }
    }


def _parse_start_row(updated_range: str, fallback: int) -> int:
    match = re.search(r"![A-Z]+\$?(\d+)", updated_range or "")
    return int(match.group(1)) if match else fallback


def append_rows(
    gateway: SheetsGateway,
    target: Target,
    rows: list[list[str]],
    m: Measures,
) -> AppendResult:
    """行を追加し、書式を機械的に揃え、読み戻し検証まで行う。"""
    if not rows:
        raise ValueError("rows must not be empty")
    rows = [list(row) for row in rows]

    state = gateway.get_state(target.spreadsheet_id, target.tab)
    sheet_id = state.sheet_id
    n_cols = max(
        [len(row) for row in state.values]
        + [len(row) for row in rows]
        + [len(state.column_widths)]
        + [0]
    )
    widths = compute_column_widths(state, target, rows, m, n_cols)
    last_letter = column_letter(n_cols - 1) if n_cols else "A"
    updated_range = gateway.append_values(
        target.spreadsheet_id, f"{target.tab}!A:{last_letter}", rows
    )
    start_row = _parse_start_row(updated_range, fallback=len(state.values) + 1)
    appended_rows = [start_row + i for i in range(len(rows))]

    # 作業用の書式グリッド（既存＋追加行ぶんを空で用意）
    total_rows = max(len(state.values), start_row - 1 + len(rows))
    working: list[list[dict]] = []
    for r in range(total_rows):
        row_formats = []
        for c in range(n_cols):
            if r < len(state.cell_formats) and c < len(state.cell_formats[r]):
                row_formats.append(copy.deepcopy(state.cell_formats[r][c]))
            else:
                row_formats.append({})
        working.append(row_formats)

    requests: list[dict] = []
    for col in range(n_cols):
        requests.append(
            _dimension_request(sheet_id, "COLUMNS", col, widths[column_letter(col)])
        )

    intended_formats: dict[tuple[int, int], dict] = {}
    for i, row in enumerate(rows):
        row_index = start_row - 1 + i  # 0始まり
        # 継承元: 直近2行の背景色が異なれば交互色とみなし、同パリティの行を使う
        source = row_index - 1
        if row_index - 2 >= 1 and _backgrounds(
            working, row_index - 1, n_cols
        ) != _backgrounds(working, row_index - 2, n_cols):
            source = row_index - 2
        if source < 1:
            source = -1  # データ行が無い場合は継承しない
        for col in range(n_cols):
            fmt = _inherit_format(working[source][col]) if source >= 0 else {}
            policy = _policy_for(target, column_letter(col))
            if policy.mode == "wrap":
                fmt["wrapStrategy"] = "WRAP"
            working[row_index][col] = fmt
            intended_formats[(row_index, col)] = fmt
            if fmt:
                requests.append(_format_request(sheet_id, row_index, col, fmt))

    intended_heights: dict[int, int] = {}
    for i, row in enumerate(rows):
        row_index = start_row - 1 + i
        lines = 1
        for col in range(n_cols):
            text = row[col] if col < len(row) else ""
            lines = max(
                lines,
                mz.cell_lines(text, widths[column_letter(col)], m=m),
            )
        height = mz.row_height_px(lines, m)
        intended_heights[start_row + i] = height
        requests.append(_dimension_request(sheet_id, "ROWS", row_index, height))

    if requests:
        gateway.batch_update(target.spreadsheet_id, requests)

    _verify(
        gateway,
        target,
        rows,
        start_row,
        widths,
        intended_heights,
        intended_formats,
        n_cols,
    )
    return AppendResult(
        appended_rows=appended_rows,
        column_widths=widths,
        row_heights=intended_heights,
    )


def _verify(
    gateway: SheetsGateway,
    target: Target,
    rows: list[list[str]],
    start_row: int,
    widths: dict[str, int],
    intended_heights: dict[int, int],
    intended_formats: dict[tuple[int, int], dict],
    n_cols: int,
) -> None:
    after = gateway.get_state(target.spreadsheet_id, target.tab)
    problems: list[str] = []

    for col in range(n_cols):
        letter = column_letter(col)
        actual = after.column_widths[col] if col < len(after.column_widths) else None
        if actual != widths[letter]:
            problems.append(
                f"列 {letter} の幅が意図と不一致: "
                f"expected={widths[letter]} actual={actual}"
            )

    for i, row in enumerate(rows):
        row_number = start_row + i
        row_index = row_number - 1
        actual_values = after.values[row_index] if row_index < len(after.values) else []
        padded = [
            actual_values[c] if c < len(actual_values) else "" for c in range(n_cols)
        ]
        expected = [row[c] if c < len(row) else "" for c in range(n_cols)]
        values_match = all(
            padded[c] == expected[c]
            or _entered_value_matches(expected[c], _entered_at(after, row_index, c))
            for c in range(n_cols)
        )
        if not values_match:
            problems.append(
                f"行 {row_number} の値が意図と不一致: "
                f"expected={expected} actual={padded}"
            )
        actual_height = (
            after.row_heights[row_index] if row_index < len(after.row_heights) else None
        )
        if actual_height != intended_heights[row_number]:
            problems.append(
                f"行 {row_number} の高さが意図と不一致: "
                f"expected={intended_heights[row_number]} actual={actual_height}"
            )
        for col in range(n_cols):
            intended = intended_formats.get((row_index, col), {})
            actual_fmt = {}
            if row_index < len(after.cell_formats) and col < len(
                after.cell_formats[row_index]
            ):
                actual_fmt = after.cell_formats[row_index][col]
            for key in _VERIFY_FORMAT_KEYS:
                if key in intended and actual_fmt.get(key) != intended[key]:
                    problems.append(
                        f"セル {column_letter(col)}{row_number} の書式 {key} が"
                        f"意図と不一致: expected={intended[key]} "
                        f"actual={actual_fmt.get(key)}"
                    )

    if problems:
        raise VerificationError(" / ".join(problems))
