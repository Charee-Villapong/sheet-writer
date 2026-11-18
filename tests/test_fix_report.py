"""R3: fix_sheet の戻り値は、実際に修正した違反の全件を含む。

仕様:
- fix_sheet の戻り値（＝ CLI --fix の報告件数）は「修正リクエストを
  送り、最終の再検査で解消を確認できた違反」の全件。
- 折り返し違反の修正で新たに現れた行高違反も、実際に直したものは
  戻り値に含まれる（事前 check の顔ぶれと一致するとは限らない）。
- 逆に、幅修正などで自然解消した行高違反（修正リクエストを送って
  いないもの）は戻り値に含めない。また、gateway が修正を無視して
  解消しなかった違反も「直した」とは報告しない。
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
    # B の設定幅は gateway の現在幅100に一致させる。主題は wrap と
    # row_height の件数であり、R4 無条件化の width 違反を持ち込まない
    # ためのフィクスチャ中立化（現在幅を300へ上げると B2 が収まって
    # wrap 違反自体が消えるため、設定幅側を合わせる）
    return make_target(
        {
            "A": ColumnPolicy(mode="fit"),
            "B": ColumnPolicy(mode="wrap", width_px=100),
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
        # 行高は B3（3行目）に加え、B2 への WRAP 設定で折り返し行数が
        # 増えて再検査で新たに現れた 2行目分も、実際に直したので含む
        assert fixed_kinds["row_height"] == 2
        locations = {v.location for v in fixed if v.kind == "row_height"}
        assert locations == {"2行目", "3行目"}

    def test_fix_returns_every_actually_fixed_violation(self, m, make_target):
        gateway = combined_gateway()
        target = combined_target(make_target)
        found = check_sheet(gateway, target, m)
        fixed = fix_sheet(gateway, target, m)
        # 事前 check で見つかった違反は、直ったものは全て含まれる
        fixed_keys = {(v.kind, v.location) for v in fixed}
        for violation in found:
            assert (violation.kind, violation.location) in fixed_keys
        # 戻り値は「実際に直した全件」: wrap 1件 + 行高 2件
        assert len(fixed) == 3
        # 修正後は違反が残っていない
        assert check_sheet(gateway, target, m) == []


class TestFixReportAccuracy:
    def test_incidentally_resolved_row_height_is_not_reported(self, m, make_target):
        # B 列（wrap・設定幅300）が現在幅100のため width 違反があり、
        # WRAP 済みセルの折り返しで row_height 違反も併存する。
        # 幅を300へ広げると1行に収まって行高違反は自然解消するが、
        # 行高の修正リクエストは送っていないので戻り値に含めない
        state = make_state(
            [["名前", "メモ"], ["abc", "あ" * 20]],
            column_widths=[100, 100],
            row_heights=[38, 26],
            cell_formats=[[{}, {}], [{}, {"wrapStrategy": "WRAP"}]],
        )
        gateway = FakeGateway(state)
        target = make_target(
            {
                "A": ColumnPolicy(mode="fit"),
                "B": ColumnPolicy(mode="wrap", width_px=300),
            }
        )
        found = check_sheet(gateway, target, m)
        assert kinds(found) == Counter({"width": 1, "row_height": 1})
        fixed = fix_sheet(gateway, target, m)
        assert kinds(fixed) == Counter({"width": 1})
        # 行高は触っていない（自然解消）ことも状態から確認する
        assert gateway.state.row_heights[1] == 26
        assert check_sheet(gateway, target, m) == []

    def test_unresolved_violation_is_not_reported(self, m, make_target):
        # gateway が行高の修正を無視する場合は、解消していないので
        # 「直した」とは報告しない
        state = make_state(
            [["名前", "メモ"], ["abc", "あ" * 20]],
            column_widths=[100, 100],
            row_heights=[38, 26],
            cell_formats=[[{}, {}], [{}, {"wrapStrategy": "WRAP"}]],
        )
        gateway = FakeGateway(state, ignore_row_heights=True)
        target = make_target(
            {
                "A": ColumnPolicy(mode="fit"),
                "B": ColumnPolicy(mode="wrap", width_px=100),
            }
        )
        found = check_sheet(gateway, target, m)
        assert kinds(found) == Counter({"row_height": 1})
        fixed = fix_sheet(gateway, target, m)
        assert fixed == []
        # 違反自体は残ったままである
        assert kinds(check_sheet(gateway, target, m)) == Counter({"row_height": 1})
