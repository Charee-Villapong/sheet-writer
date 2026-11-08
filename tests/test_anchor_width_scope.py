"""仕様（writer・関連）: 列幅計算の対象データ行も anchor 最終行までに揃える。

anchor 設定時、checker の検査範囲は anchor 最終行までに限定される
（test_anchor_checker.py）。writer の列幅計算も同じ範囲に揃える:
範囲外（事前設定行）の非 anchor 列に長い値があっても、追加時の
列幅がそれに引っ張られない。

状態の数え方:
- 1行目: ヘッダー
- 2〜4行目: データ3行（B=タスク名あり、C は短い値）
- 5〜8行目: 事前設定行（B は空、C に "あ"*50 の長い値）
よって anchor="B" での追加先は5行目。C の必要幅は範囲内だけなら
最大でヘッダーの44px程度だが、事前設定行まで数えると595pxになる。
"""

from fake_gateway import FakeGateway, make_state

from sheet_writer.config import ColumnPolicy, Target
from sheet_writer.writer import append_rows

COLUMNS = {
    "A": ColumnPolicy(mode="fit"),
    "B": ColumnPolicy(mode="wrap", width_px=300),
    "C": ColumnPolicy(mode="fit"),
}

NEW_ROW = ["", "新しいタスク", "短い"]


def make_gateway():
    values = [
        ["チェック", "タスク", "メモ"],
        ["FALSE", "タスク1", "短い"],
        ["FALSE", "タスク2", "短い"],
        ["FALSE", "タスク3", "短い"],
        ["FALSE", "", "あ" * 50],
        ["FALSE", "", "あ" * 50],
        ["FALSE", "", "あ" * 50],
        ["FALSE", "", "あ" * 50],
    ]
    state = make_state(
        values,
        column_widths=[100, 300, 100],
        row_heights=[38, 26, 26, 26, 21, 21, 21, 21],
    )
    return FakeGateway(state)


def anchor_target():
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="テストタブ",
        columns=dict(COLUMNS),
        append_anchor_column="B",
    )


def plain_target():
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="テストタブ",
        columns=dict(COLUMNS),
    )


class TestWriterWidthScopeWithAnchor:
    def test_preset_long_value_does_not_expand_column(self, m):
        gateway = make_gateway()
        result = append_rows(gateway, anchor_target(), [NEW_ROW], m)
        assert result.appended_rows == [5]
        # 事前設定行の長い値（必要幅595）に引っ張られず、現在幅のまま
        assert result.column_widths["C"] == 100
        assert gateway.state.column_widths[2] == 100

    def test_without_anchor_long_value_expands_column(self, m):
        # 特性固定: anchor 未設定では全行が列幅計算の対象になり、
        # 事前設定行の長い値まで広がる（従来動作）
        gateway = make_gateway()
        result = append_rows(gateway, plain_target(), [NEW_ROW], m)
        assert result.appended_rows == [9]
        assert result.column_widths["C"] == 595
        assert gateway.state.column_widths[2] == 595
