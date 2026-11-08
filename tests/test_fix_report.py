"""R3: fix_sheet の戻り値は、実際に修正した違反の全件を含む。

仕様:
- fix_sheet の戻り値（＝ CLI --fix の報告件数）は修正した違反の全件。
- 特に「折り返し違反＋行高違反が併存するケース」で、両方とも
  戻り値に含まれる（片方だけ報告して終わらない）。
- 現行で満たせば特性テストとして通過してよい。
"""

from collections import Counter

from fake_gateway import FakeGateway, make_state
from sheet_writer.checker import check_sheet, fix_sheet
from sheet_writer.config import ColumnPolicy


def kinds(violations):
    return Counter(v.kind for v in violations)


def combined_gateway():
    """wrap 違反（B2）と row_height 違反（B3）が併存するシート。

    - B2: "あ"*20 が幅100に収まらないのに WRAP 未設定 → wrap 違反
    - B3: 改行2行のセルに WRAP 設定済みだが行高 26 < 必要 42
      → row_height 違反
    """
    state = make_state(
        [
            ["名前", "メモ"],
            ["abc", "あ" * 20],
            ["def", "1行目\n2行目"],
        ],
        column_widths=[100, 100],
        row_heights=[38, 26, 26],
        cell_formats=[
            [{}, {}],
            [{}, {}],
            [{}, {"wrapStrategy": "WRAP"}],
        ],
    )
    return FakeGateway(state)


def combined_target(make_target):
    return make_target(
        {
            "A": ColumnPolicy(mode="fit"),
            "B": ColumnPolicy(mode="wrap", width_px=300),
        }
    )


class TestFixReportCompleteness:
    def test_precheck_has_both_wrap_and_row_height(self, m, make_target):
        gateway = combined_gateway()
        found = check_sheet(gateway, combined_target(make_target), m)
        assert kinds(found) == Counter({"wrap": 1, "row_height": 1})

    def test_fix_returns_both_kinds(self, m, make_target):
        gateway = combined_gateway()
        fixed = fix_sheet(gateway, combined_target(make_target), m)
        fixed_kinds = kinds(fixed)
        assert fixed_kinds["wrap"] == 1
        assert fixed_kinds["row_height"] == 1

    def test_fix_returns_every_violation_found_by_check(self, m, make_target):
        gateway = combined_gateway()
        target = combined_target(make_target)
        found = check_sheet(gateway, target, m)
        fixed = fix_sheet(gateway, target, m)
        # 件数も種別構成も、事前 check で見つかった違反と一致する
        assert len(fixed) == len(found)
        assert kinds(fixed) == kinds(found)
        # 修正後は違反が残っていない
        assert check_sheet(gateway, target, m) == []
