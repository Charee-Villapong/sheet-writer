"""checker（check_sheet / fix_sheet）の振る舞いを FakeGateway で固定する。

固定する仕様:
- fit 列で必要幅 > 現在幅なら width 違反
- 内容が列幅に収まらないのに WRAP 未設定なら wrap 違反
- 推定必要行高 > 現在行高なら row_height 違反
- check は読み取りのみ（状態を変えない）
- fix は書式のみ（列幅拡大・WRAP・行高拡大）を直し、値・数式には絶対に触らない
"""

import copy

from fake_gateway import FakeGateway, make_state

from sheet_writer.checker import check_sheet, fix_sheet
from sheet_writer.config import ColumnPolicy


def kinds(violations):
    return [v.kind for v in violations]


def width_violation_sheet():
    """列 A（fit）が不足: データ "あ"*10 の必要幅 135 > 現在幅 50。"""
    state = make_state(
        [["名前", "メモ"], ["あ" * 10, "x"]],
        column_widths=[50, 200],
        row_heights=[38, 26],
    )
    return FakeGateway(state)


def wrap_target(make_target):
    return make_target(
        {"A": ColumnPolicy(mode="fit"), "B": ColumnPolicy(mode="wrap", width_px=300)}
    )


def fit_target(make_target):
    return make_target({"A": ColumnPolicy(mode="fit"), "B": ColumnPolicy(mode="fit")})


class TestWidthViolation:
    def test_detected_with_expected_and_actual(self, m, make_target):
        gateway = width_violation_sheet()
        violations = check_sheet(gateway, fit_target(make_target), m)
        width = [v for v in violations if v.kind == "width"]
        assert len(width) == 1
        assert width[0].location == "A"
        assert width[0].expected == 135
        assert width[0].actual == 50
        assert isinstance(width[0].detail, str)
        assert width[0].detail != ""

    def test_sufficient_width_is_clean(self, m, make_target):
        state = make_state(
            [["名前", "メモ"], ["あ" * 10, "x"]],
            column_widths=[135, 200],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        # A の内容は 135px 幅に収まる（115px / 115px = 1行）が、
        # B 列 "x" も問題なし。行高も十分。
        violations = check_sheet(gateway, fit_target(make_target), m)
        assert [v for v in violations if v.kind == "width"] == []


class TestWrapViolation:
    def test_detected_for_overflowing_cell_without_wrap(self, m, make_target):
        # 列 B は現在幅 100 のため "あ"*20（230px）が 3 行分はみ出すが WRAP なし
        state = make_state(
            [["名前", "メモ"], ["abc", "あ" * 20]],
            column_widths=[100, 100],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        violations = check_sheet(gateway, wrap_target(make_target), m)
        wrap = [v for v in violations if v.kind == "wrap"]
        assert len(wrap) == 1
        assert wrap[0].location == "B2"

    def test_no_violation_when_wrap_is_set(self, m, make_target):
        state = make_state(
            [["名前", "メモ"], ["abc", "あ" * 20]],
            column_widths=[100, 100],
            row_heights=[38, 58],  # 3 行分の高さも確保済み
            cell_formats=[[{}, {}], [{}, {"wrapStrategy": "WRAP"}]],
        )
        gateway = FakeGateway(state)
        violations = check_sheet(gateway, wrap_target(make_target), m)
        assert violations == []

    def test_short_cell_without_wrap_is_fine(self, m, make_target):
        state = make_state(
            [["名前", "メモ"], ["abc", "x"]],
            column_widths=[100, 100],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        assert check_sheet(gateway, wrap_target(make_target), m) == []


class TestRowHeightViolation:
    def test_detected_when_height_insufficient(self, m, make_target):
        # WRAP 設定済みだが 3 行必要（58px）に対し現在 26px
        state = make_state(
            [["名前", "メモ"], ["abc", "あ" * 20]],
            column_widths=[100, 100],
            row_heights=[38, 26],
            cell_formats=[[{}, {}], [{}, {"wrapStrategy": "WRAP"}]],
        )
        gateway = FakeGateway(state)
        violations = check_sheet(gateway, wrap_target(make_target), m)
        heights = [v for v in violations if v.kind == "row_height"]
        assert len(heights) == 1
        assert heights[0].expected == 58
        assert heights[0].actual == 26
        assert "2" in str(heights[0].location)
        # WRAP は設定済みなので wrap 違反にはならない
        assert [v for v in violations if v.kind == "wrap"] == []

    def test_multiline_cell_needs_height_for_all_lines(self, m, make_target):
        # セル内改行 2 行分: 必要行高 42 > 現在 26
        state = make_state(
            [["名前", "メモ"], ["abc", "1行目\n2行目"]],
            column_widths=[100, 300],
            row_heights=[38, 26],
            cell_formats=[[{}, {}], [{}, {"wrapStrategy": "WRAP"}]],
        )
        gateway = FakeGateway(state)
        violations = check_sheet(gateway, wrap_target(make_target), m)
        heights = [v for v in violations if v.kind == "row_height"]
        assert len(heights) == 1
        assert heights[0].expected == 42


class TestCleanSheet:
    def test_empty_rows_are_not_flagged_for_height(self, m, make_target):
        # 内容のない行は、既定行高（21px）のままでも行高不足にしない。
        # 実地確認で判明した誤検出への対策（実装側で追加したテスト）。
        state = make_state(
            [["名前", "メモ"], ["abc", "x"], ["", ""], ["", ""]],
            column_widths=[100, 300],
            row_heights=[38, 26, 21, 21],
        )
        gateway = FakeGateway(state)
        assert check_sheet(gateway, wrap_target(make_target), m) == []

    def test_no_violations(self, m, make_target):
        state = make_state(
            [["名前", "メモ"], ["abc", "x"]],
            column_widths=[100, 300],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        assert check_sheet(gateway, wrap_target(make_target), m) == []

    def test_header_only_sheet_is_clean(self, m, make_target):
        state = make_state(
            [["名前", "メモ"]],
            column_widths=[100, 300],
            row_heights=[38],
        )
        gateway = FakeGateway(state)
        assert check_sheet(gateway, wrap_target(make_target), m) == []


class TestCheckIsReadOnly:
    def test_state_unchanged_and_no_batch_update(self, m, make_target):
        gateway = width_violation_sheet()
        before = gateway.state
        check_sheet(gateway, fit_target(make_target), m)
        assert gateway.state == before
        assert gateway.batch_requests == []
        assert gateway.append_calls == []


class TestFixSheet:
    def test_fix_width_violation(self, m, make_target):
        gateway = width_violation_sheet()
        fixed = fix_sheet(gateway, fit_target(make_target), m)
        assert "width" in kinds(fixed)
        assert gateway.state.column_widths[0] == 135
        # 修正後は違反が残っていない
        assert check_sheet(gateway, fit_target(make_target), m) == []

    def test_fix_wrap_and_width_for_wrap_column(self, m, make_target):
        state = make_state(
            [["名前", "メモ"], ["abc", "あ" * 20]],
            column_widths=[100, 100],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        fixed = fix_sheet(gateway, wrap_target(make_target), m)
        assert "wrap" in kinds(fixed)
        # wrap 列はポリシー幅 300 まで広がり、WRAP が設定される
        assert gateway.state.column_widths[1] == 300
        assert gateway.state.cell_formats[1][1]["wrapStrategy"] == "WRAP"
        assert check_sheet(gateway, wrap_target(make_target), m) == []

    def test_fix_row_height(self, m, make_target):
        state = make_state(
            [["名前", "メモ"], ["abc", "あ" * 20]],
            column_widths=[100, 100],
            row_heights=[38, 26],
            cell_formats=[[{}, {}], [{}, {"wrapStrategy": "WRAP"}]],
        )
        gateway = FakeGateway(state)
        fixed = fix_sheet(gateway, wrap_target(make_target), m)
        assert "row_height" in kinds(fixed)
        assert gateway.state.row_heights[1] == 58
        assert check_sheet(gateway, wrap_target(make_target), m) == []

    def test_fix_never_touches_values_or_formulas(self, m, make_target):
        values = [
            ["名前", "メモ", "合計"],
            ["あ" * 10, "あ" * 20, "=SUM(A2:A2)"],
        ]
        state = make_state(
            values,
            column_widths=[50, 100, 100],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        before_values = copy.deepcopy(gateway.state.values)
        target = make_target(
            {
                "A": ColumnPolicy(mode="fit"),
                "B": ColumnPolicy(mode="wrap", width_px=300),
                "C": ColumnPolicy(mode="fit"),
            }
        )
        fix_sheet(gateway, target, m)
        # 値・数式は一切変わっていない（数式文字列もそのまま）
        assert gateway.state.values == before_values
        assert gateway.state.values[1][2] == "=SUM(A2:A2)"
        # 値の書き込み経路は使われていない
        assert gateway.append_calls == []
        # batch_update で送られたのは書式系リクエストのみ
        for req in gateway.batch_requests:
            assert set(req.keys()) <= {"updateDimensionProperties", "repeatCell"}

    def test_fix_clean_sheet_returns_empty_and_changes_nothing(self, m, make_target):
        state = make_state(
            [["名前", "メモ"], ["abc", "x"]],
            column_widths=[100, 300],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        before = gateway.state
        assert fix_sheet(gateway, wrap_target(make_target), m) == []
        assert gateway.state == before
        assert gateway.batch_requests == []

    def test_fix_does_not_shrink_existing_width(self, m, make_target):
        # A は十分広い（500）。B の違反だけ直し、A は縮めない。
        state = make_state(
            [["名前", "メモ"], ["abc", "あ" * 20]],
            column_widths=[500, 100],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        fix_sheet(gateway, wrap_target(make_target), m)
        assert gateway.state.column_widths[0] == 500
