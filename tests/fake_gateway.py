"""writer / checker のテスト用インメモリ FakeGateway。

SheetsGateway プロトコルと同じ4メソッドを持ち、`batch_update` の
リクエスト（updateDimensionProperties / repeatCell）を解釈して
保持している SheetState を実際に書き換える。これにより writer の
「書き込み後に読み戻して検証する」振る舞いまで含めて検証できる。

検証失敗系のテストのために、変更の一部を無視するモードを持つ:
- ignore_column_widths: 列幅の変更を黙って捨てる
- ignore_repeat_cell: 書式（WRAP 等）の変更を黙って捨てる
- drop_appended_values: append しても値を保持しない
- ignore_background_clear: repeatCell のフィールドマスクによる背景色の
  除去（マスクに挙がっているのに cell に無いフィールドの削除）を無視する
- keep_appended_background: append した行に上の行の背景色を持ち込ませ、
  かつ背景色の除去を無視する（実 API の append 書式継承で背景が
  付いてしまう状況の再現）
- ignore_text_format: repeatCell の textFormat だけを黙って捨てる
  （他の書式キーは通常どおり反映する）

append の配置は実 API のテーブル検出を模す:
- 範囲（range_a1）が全列範囲（例 "タブ!A:B" / "タブ!B:B"）なら、
  その列範囲の中で値（空でないセル）のある最終行をテーブルの末尾とし、
  新規行はその直後に挿入される（既存行は下へずれる。INSERT_ROWS 相当）。
- 範囲が開始行を持つ有界範囲／単一セル（例 "タブ!A21:C21" / "タブ!A21"）
  なら、その開始行へ挿入される。
- 書き込み自体は従来どおり常に A 列から行う（範囲はテーブル検出の
  対象列と開始位置を決めるためにだけ使う）。

update_values は実 API の values update を模す:
- 指定範囲への直接書き込み（行の挿入・シフトはしない）。範囲より
  下の行はそのまま残る。
"""

import copy
import re

from sheet_writer.gateway import SheetState

DUMMY_SHEET_ID = 7


def column_letter(index0):
    """0始まりの列インデックスを列文字（A, B, ...）に変換する。"""
    letter = ""
    index0 += 1
    while index0:
        index0, rem = divmod(index0 - 1, 26)
        letter = chr(ord("A") + rem) + letter
    return letter


def _column_index(letter):
    """列文字（A, B, ...）を0始まりのインデックスに変換する。"""
    index = 0
    for ch in letter:
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


def _entered_for(value):
    """実 API に倣った userEnteredValue の合成。"""
    if value == "":
        return {}
    if isinstance(value, str) and value.startswith("="):
        return {"formulaValue": value}
    return {"stringValue": value}


def _entered_for_row(row):
    return [_entered_for(value) for value in row]


def _synth_entered(values):
    return [_entered_for_row(row) for row in values]


def make_state(values, column_widths=None, row_heights=None, cell_formats=None):
    """values を中心に、寸法・書式の既定値を補った SheetState を作る。"""
    n_cols = max((len(row) for row in values), default=0)
    padded_values = [list(row) + [""] * (n_cols - len(row)) for row in values]
    if cell_formats is None:
        formats = [[{} for _ in range(n_cols)] for _ in padded_values]
    else:
        formats = [
            [
                copy.deepcopy(cell_formats[r][c]) if c < len(cell_formats[r]) else {}
                for c in range(n_cols)
            ]
            for r in range(len(padded_values))
        ]
    return SheetState(
        sheet_id=DUMMY_SHEET_ID,
        values=padded_values,
        column_widths=(
            list(column_widths) if column_widths is not None else [100] * n_cols
        ),
        row_heights=(
            list(row_heights) if row_heights is not None else [26] * len(padded_values)
        ),
        cell_formats=formats,
        entered_values=_synth_entered(padded_values),
    )


def _merge(dst, src):
    """userEnteredFormat のマージ（ネストした dict は再帰的に合成する）。"""
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _merge(dst[key], value)
        else:
            dst[key] = copy.deepcopy(value)


class FakeGateway:
    """状態を保持し batch_update を解釈するインメモリ実装。"""

    def __init__(
        self,
        state,
        *,
        ignore_column_widths=False,
        ignore_repeat_cell=False,
        drop_appended_values=False,
        ignore_background_clear=False,
        keep_appended_background=False,
        ignore_text_format=False,
    ):
        self._state = copy.deepcopy(state)
        if not getattr(self._state, "entered_values", None):
            self._state.entered_values = _synth_entered(self._state.values)
        self.ignore_column_widths = ignore_column_widths
        self.ignore_repeat_cell = ignore_repeat_cell
        self.drop_appended_values = drop_appended_values
        self.ignore_background_clear = ignore_background_clear
        self.keep_appended_background = keep_appended_background
        self.ignore_text_format = ignore_text_format
        # 検証用に、受け取ったリクエストと append 呼び出しを記録する
        self.batch_requests = []
        self.append_calls = []
        self.update_calls = []

    # -- 状態へのアクセス（テスト側の確認用） -------------------------
    @property
    def state(self):
        return copy.deepcopy(self._state)

    # -- SheetsGateway プロトコル --------------------------------------
    def get_values(self, spreadsheet_id, range_a1):
        return copy.deepcopy(self._state.values)

    def _append_start_row(self, range_a1):
        """実 API のテーブル検出を模して、追加開始行（1始まり）を決める。"""
        range_part = range_a1.rsplit("!", 1)[-1] if "!" in range_a1 else range_a1
        range_part = range_part.strip().strip("'")
        bounded = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_part)
        if bounded:
            # 開始行つきの有界範囲は、その開始行への追加として扱う
            return int(bounded.group(2))
        single = re.fullmatch(r"([A-Z]+)(\d+)", range_part)
        if single:
            return int(single.group(2))
        open_ended = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)", range_part)
        full_columns = re.fullmatch(r"([A-Z]+):([A-Z]+)", range_part)
        if open_ended or full_columns:
            match = open_ended or full_columns
            col_start = _column_index(match.group(1))
            if open_ended:
                first_row = int(open_ended.group(2))
                col_end = _column_index(open_ended.group(3))
            else:
                first_row = 1
                col_end = _column_index(full_columns.group(2))
            last = 0
            for idx, row in enumerate(self._state.values):
                row_number = idx + 1
                if row_number < first_row:
                    continue
                if any(
                    c < len(row) and row[c] not in ("", None)
                    for c in range(col_start, col_end + 1)
                ):
                    last = row_number
            return last + 1 if last else first_row
        # 解釈できない範囲は従来どおり物理末尾の直後
        return len(self._state.values) + 1

    def append_values(self, spreadsheet_id, range_a1, values):
        self.append_calls.append((spreadsheet_id, range_a1, copy.deepcopy(values)))
        start_row = self._append_start_row(range_a1)  # 1始まり
        end_row = start_row + len(values) - 1
        # keep_appended_background 用: 追加位置の上の行の背景を覚えておく
        source_formats = None
        if self.keep_appended_background and self._state.cell_formats:
            above = start_row - 2  # 0始まりで「追加位置の1つ上」
            if 0 <= above < len(self._state.cell_formats):
                source_formats = copy.deepcopy(self._state.cell_formats[above])
        if not self.drop_appended_values:
            n_cols = max(
                [len(row) for row in self._state.values]
                + [len(row) for row in values]
                + [0]
            )
            for row in self._state.values:
                row.extend([""] * (n_cols - len(row)))
            for fmt_row in self._state.cell_formats:
                fmt_row.extend({} for _ in range(n_cols - len(fmt_row)))
            if not getattr(self._state, "entered_values", None):
                self._state.entered_values = _synth_entered(self._state.values)
            for entered_row in self._state.entered_values:
                entered_row.extend({} for _ in range(n_cols - len(entered_row)))
            while len(self._state.entered_values) < len(self._state.values):
                self._state.entered_values.append([{} for _ in range(n_cols)])
            while len(self._state.column_widths) < n_cols:
                self._state.column_widths.append(None)
            new_value_rows = []
            new_format_rows = []
            new_entered_rows = []
            for row in values:
                padded = list(row) + [""] * (n_cols - len(row))
                new_value_rows.append(padded)
                new_formats = [{} for _ in range(n_cols)]
                if source_formats is not None:
                    # 実 API の append は上の行の書式を引き継ぐため、
                    # 背景色も持ち込まれる状況を再現する
                    for c in range(min(n_cols, len(source_formats))):
                        for key in ("backgroundColor", "backgroundColorStyle"):
                            if key in source_formats[c]:
                                new_formats[c][key] = copy.deepcopy(
                                    source_formats[c][key]
                                )
                new_format_rows.append(new_formats)
                new_entered_rows.append(_entered_for_row(padded))
            insert_at = start_row - 1  # 0始まり
            # 追加位置が物理末尾より先なら、間を空行で埋めてから追加する
            while len(self._state.values) < insert_at:
                self._state.values.append([""] * n_cols)
                self._state.cell_formats.append([{} for _ in range(n_cols)])
                self._state.row_heights.append(None)
                self._state.entered_values.append([{} for _ in range(n_cols)])
            self._state.values[insert_at:insert_at] = new_value_rows
            self._state.cell_formats[insert_at:insert_at] = new_format_rows
            self._state.row_heights[insert_at:insert_at] = [None] * len(values)
            self._state.entered_values[insert_at:insert_at] = new_entered_rows
        tab = range_a1.split("!")[0] if "!" in range_a1 else "Sheet1"
        last_col = column_letter(max((len(r) for r in values), default=1) - 1)
        return f"{tab}!A{start_row}:{last_col}{end_row}"

    def update_values(self, spreadsheet_id, range_a1, values):
        """values update の模倣: 範囲へ直接書き込む（挿入・シフトなし）。"""
        self.update_calls.append((spreadsheet_id, range_a1, copy.deepcopy(values)))
        range_part = range_a1.rsplit("!", 1)[-1] if "!" in range_a1 else range_a1
        range_part = range_part.strip().strip("'")
        match = re.fullmatch(r"([A-Z]+)(\d+)(?::([A-Z]+)(\d+))?", range_part)
        if match:
            start_col = _column_index(match.group(1))
            start_row = int(match.group(2))
        else:
            start_col = 0
            start_row = len(self._state.values) + 1
        n_cols = max(
            [len(row) for row in self._state.values]
            + [start_col + len(row) for row in values]
            + [0]
        )
        if not getattr(self._state, "entered_values", None):
            self._state.entered_values = _synth_entered(self._state.values)
        end_row = start_row - 1 + len(values)
        while len(self._state.values) < end_row:
            self._state.values.append([""] * n_cols)
            self._state.cell_formats.append([{} for _ in range(n_cols)])
            self._state.row_heights.append(None)
            self._state.entered_values.append([{} for _ in range(n_cols)])
        for row in self._state.values:
            row.extend([""] * (n_cols - len(row)))
        for fmt_row in self._state.cell_formats:
            fmt_row.extend({} for _ in range(n_cols - len(fmt_row)))
        for entered_row in self._state.entered_values:
            entered_row.extend({} for _ in range(n_cols - len(entered_row)))
        while len(self._state.column_widths) < n_cols:
            self._state.column_widths.append(None)
        for i, row in enumerate(values):
            r = start_row - 1 + i
            for c, value in enumerate(row):
                self._state.values[r][start_col + c] = value
                self._state.entered_values[r][start_col + c] = _entered_for(value)
        tab = range_a1.split("!")[0] if "!" in range_a1 else "Sheet1"
        last_col = column_letter(
            start_col + max((len(r) for r in values), default=1) - 1
        )
        return f"{tab}!{column_letter(start_col)}{start_row}:{last_col}{end_row}"

    def get_state(self, spreadsheet_id, tab):
        return copy.deepcopy(self._state)

    def batch_update(self, spreadsheet_id, requests):
        for request in requests:
            self.batch_requests.append(copy.deepcopy(request))
            if "updateDimensionProperties" in request:
                self._apply_dimension(request["updateDimensionProperties"])
            elif "repeatCell" in request:
                self._apply_repeat_cell(request["repeatCell"])

    # -- リクエスト解釈 --------------------------------------------------
    def _apply_dimension(self, body):
        rng = body.get("range", {})
        pixel_size = body.get("properties", {}).get("pixelSize")
        if pixel_size is None:
            return
        start = rng.get("startIndex", 0)
        end = rng.get("endIndex", start + 1)
        if rng.get("dimension") == "COLUMNS":
            if self.ignore_column_widths:
                return
            target = self._state.column_widths
        elif rng.get("dimension") == "ROWS":
            target = self._state.row_heights
        else:
            return
        while len(target) < end:
            target.append(None)
        for idx in range(start, end):
            target[idx] = pixel_size

    def _apply_repeat_cell(self, body):
        if self.ignore_repeat_cell:
            return
        rng = body.get("range", {})
        fmt = body.get("cell", {}).get("userEnteredFormat") or {}
        if self.ignore_text_format and "textFormat" in fmt:
            fmt = {k: v for k, v in fmt.items() if k != "textFormat"}
        # 実 API のフィールドマスク意味論: マスクに挙がっているのに
        # cell に無いフィールドは削除される（背景色の除去はこれで担保する）。
        fields = body.get("fields", "") or ""
        mask_leaves = {
            token.strip().rstrip(")").split(".")[-1].lstrip("(")
            for token in str(fields).split(",")
            if token.strip()
        }
        clear_background = {
            key
            for key in ("backgroundColor", "backgroundColorStyle")
            if key in mask_leaves and key not in fmt
        }
        if self.ignore_background_clear or self.keep_appended_background:
            clear_background = set()
        if not fmt and not clear_background:
            return
        row_start = rng.get("startRowIndex", 0)
        row_end = rng.get("endRowIndex", row_start + 1)
        col_start = rng.get("startColumnIndex", 0)
        col_end = rng.get("endColumnIndex", col_start + 1)
        for r in range(row_start, row_end):
            for c in range(col_start, col_end):
                if r < len(self._state.cell_formats) and c < len(
                    self._state.cell_formats[r]
                ):
                    cell = self._state.cell_formats[r][c]
                    if fmt:
                        _merge(cell, fmt)
                    for key in clear_background:
                        cell.pop(key, None)
