"""R4: wrap 列についても列幅不足を width 違反にする。

仕様:
- checker は wrap モード列についても、設定の width_px より現在の
  列幅が狭ければ kind="width" の違反にする（expected=設定幅）。
- fix で設定幅まで拡大される。
- 設定幅以上なら違反なし。fit 列の従来判定は不変。
- R4 は無条件に適用する（仕様変更）: 現在幅が既定幅 100px の列や、
  幅メタデータ未設定（None → 既定100扱い）の列も「未設定とみなして
  対象外」にはしない。明示的に 100px に設定された wrap 列が永久に
  すり抜ける穴を塞ぐため。
"""

from fake_gateway import FakeGateway, make_state

from sheet_writer.checker import check_sheet, fix_sheet
from sheet_writer.config import ColumnPolicy


def gateway_with_wrap_width(current_width):
    """内容は短く（wrap / row_height 違反は出ない）、列幅だけが論点のシート。"""
    state = make_state(
        [["名前", "メモ"], ["abc", "x"]],
        column_widths=[100, current_width],
        row_heights=[38, 26],
    )
    return FakeGateway(state)


def wrap_target(make_target, width_px=300):
    return make_target(
        {
            "A": ColumnPolicy(mode="fit"),
            "B": ColumnPolicy(mode="wrap", width_px=width_px),
        }
    )


def width_violations(violations):
    return [v for v in violations if v.kind == "width"]


class TestWrapColumnWidthViolation:
    def test_narrower_than_policy_is_width_violation(self, m, make_target):
        gateway = gateway_with_wrap_width(200)
        violations = check_sheet(gateway, wrap_target(make_target), m)
        width = width_violations(violations)
        assert len(width) == 1
        assert width[0].location == "B"
        assert width[0].expected == 300
        assert width[0].actual == 200

    def test_expected_follows_configured_width(self, m, make_target):
        gateway = gateway_with_wrap_width(200)
        violations = check_sheet(gateway, wrap_target(make_target, width_px=250), m)
        width = width_violations(violations)
        assert len(width) == 1
        assert width[0].expected == 250
        assert width[0].actual == 200

    def test_exactly_policy_width_is_clean(self, m, make_target):
        gateway = gateway_with_wrap_width(300)
        assert check_sheet(gateway, wrap_target(make_target), m) == []

    def test_wider_than_policy_is_clean(self, m, make_target):
        gateway = gateway_with_wrap_width(450)
        assert check_sheet(gateway, wrap_target(make_target), m) == []

    def test_fix_expands_wrap_column_to_policy_width(self, m, make_target):
        gateway = gateway_with_wrap_width(200)
        target = wrap_target(make_target)
        fixed = fix_sheet(gateway, target, m)
        assert len(width_violations(fixed)) == 1
        assert gateway.state.column_widths[1] == 300
        assert check_sheet(gateway, target, m) == []

    def test_fix_does_not_shrink_wide_wrap_column(self, m, make_target):
        # A 列（fit）の違反だけを直す状況でも、B の広い幅は縮めない
        state = make_state(
            [["名前", "メモ"], ["あ" * 10, "x"]],
            column_widths=[50, 450],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        fix_sheet(gateway, wrap_target(make_target), m)
        assert gateway.state.column_widths[0] == 135
        assert gateway.state.column_widths[1] == 450


class TestWrapWidthUnconditional:
    """R4 無条件化: 既定幅・未設定の列も対象外にしない。"""

    def test_current_width_100_is_width_violation(self, m, make_target):
        # 明示的に 100px に設定された wrap 列も、設定幅未満なら違反
        gateway = gateway_with_wrap_width(100)
        violations = check_sheet(gateway, wrap_target(make_target), m)
        width = width_violations(violations)
        assert len(width) == 1
        assert width[0].location == "B"
        assert width[0].expected == 300
        assert width[0].actual == 100

    def test_unset_width_is_width_violation_with_default_actual(self, m, make_target):
        # 幅メタデータ未設定（None）は既定100扱いで、actual=100 の違反
        gateway = gateway_with_wrap_width(None)
        violations = check_sheet(gateway, wrap_target(make_target), m)
        width = width_violations(violations)
        assert len(width) == 1
        assert width[0].location == "B"
        assert width[0].expected == 300
        assert width[0].actual == 100

    def test_unset_width_expected_follows_configured_width(self, m, make_target):
        gateway = gateway_with_wrap_width(None)
        violations = check_sheet(gateway, wrap_target(make_target, width_px=250), m)
        width = width_violations(violations)
        assert len(width) == 1
        assert width[0].expected == 250
        assert width[0].actual == 100

    def test_fix_expands_from_100(self, m, make_target):
        gateway = gateway_with_wrap_width(100)
        target = wrap_target(make_target)
        fixed = fix_sheet(gateway, target, m)
        assert len(width_violations(fixed)) == 1
        assert gateway.state.column_widths[1] == 300
        assert check_sheet(gateway, target, m) == []

    def test_fix_expands_from_unset(self, m, make_target):
        gateway = gateway_with_wrap_width(None)
        target = wrap_target(make_target)
        fixed = fix_sheet(gateway, target, m)
        assert len(width_violations(fixed)) == 1
        assert gateway.state.column_widths[1] == 300
        assert check_sheet(gateway, target, m) == []
