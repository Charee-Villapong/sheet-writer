"""仕様（本題）: 縦位置（verticalAlignment）ルール — checker / writer。

本人の指示（2026-11-09）: セルの縦位置は全部「上揃え」に統一し、
sheet-writer のコード側で再発防止する。背景色ルールと同格の
「書式ルール」として、ターゲット設定の vertical_alignment で
opt-in する（値そのものは設定側が決める。TOP 決め打ちにしない）。

checker（check_sheet / fix_sheet）:
- vertical_alignment が設定されたターゲットでのみ検査する。
- 対象は検査範囲（ヘッダー行を含む）の全セル。背景色ルールと違い
  ヘッダー行も対象（「全部上揃え」が本人の指定）。
- セルの実効 verticalAlignment が設定値と異なる（未設定を含む）ら
  違反: kind="vertical_alignment"、location は "B2" のような番地、
  expected は設定値、actual は実効値（未設定なら "未設定"）。
- fix では repeatCell で設定値に揃え、値には触らない。再検査で
  違反ゼロになる。

writer（append_rows）:
- ルール有効時: 追加行の verticalAlignment は継承元の値ではなく
  設定値に強制する（上の行が BOTTOM でも設定値が入る）。
- ルール無効時: 従来どおり上の行から継承する。
"""

from fake_gateway import FakeGateway, make_state

from sheet_writer.checker import check_sheet, fix_sheet
from sheet_writer.config import ColumnPolicy, Target
from sheet_writer.writer import append_rows

TOP = {"verticalAlignment": "TOP"}
BOTTOM = {"verticalAlignment": "BOTTOM"}

COLUMNS = {
    "A": ColumnPolicy(mode="fit"),
    "B": ColumnPolicy(mode="wrap", width_px=300),
}

VALUES = [["見出し", "メモ"], ["abc", "x"], ["def", "y"]]


def va_target(vertical_alignment="TOP", **kwargs):
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="テストタブ",
        columns=dict(COLUMNS),
        vertical_alignment=vertical_alignment,
        **kwargs,
    )


def va_violations(violations):
    return [v for v in violations if v.kind == "vertical_alignment"]


def clean_gateway(formats, values=None, row_heights=None):
    if values is None:
        values = VALUES
    state = make_state(
        values,
        column_widths=[100, 300],
        row_heights=row_heights or [38] + [26] * (len(values) - 1),
        cell_formats=formats,
    )
    return FakeGateway(state)


def all_top(rows, cols=2):
    return [[dict(TOP) for _ in range(cols)] for _ in range(rows)]


class TestCheckerDetectsVerticalAlignment:
    def test_all_matching_is_clean(self, m):
        gateway = clean_gateway(all_top(3))
        assert check_sheet(gateway, va_target(), m) == []

    def test_bottom_data_cell_is_a_violation(self, m):
        formats = all_top(3)
        formats[1][1] = dict(BOTTOM)
        violations = va_violations(
            check_sheet(gateway=clean_gateway(formats), target=va_target(), m=m)
        )
        assert len(violations) == 1
        assert violations[0].location == "B2"
        assert violations[0].expected == "TOP"
        assert violations[0].actual == "BOTTOM"

    def test_unset_cell_is_a_violation(self, m):
        formats = all_top(3)
        formats[2][0] = {}
        violations = va_violations(check_sheet(clean_gateway(formats), va_target(), m))
        assert len(violations) == 1
        assert violations[0].location == "A3"
        assert violations[0].actual == "未設定"

    def test_header_row_is_in_scope(self, m):
        # 背景色ルールと違い、ヘッダー行も「全部」の対象
        formats = all_top(3)
        formats[0][0] = dict(BOTTOM)
        violations = va_violations(check_sheet(clean_gateway(formats), va_target(), m))
        assert [v.location for v in violations] == ["A1"]

    def test_configured_value_is_compared_not_hardcoded_top(self, m):
        gateway = clean_gateway(all_top(3))
        violations = va_violations(
            check_sheet(gateway, va_target(vertical_alignment="MIDDLE"), m)
        )
        assert len(violations) == 6
        assert {v.expected for v in violations} == {"MIDDLE"}

    def test_rule_disabled_means_no_vertical_violations(self, m):
        formats = [[dict(BOTTOM), dict(BOTTOM)] for _ in range(3)]
        gateway = clean_gateway(formats)
        assert check_sheet(gateway, va_target(vertical_alignment=None), m) == []

    def test_grid_columns_beyond_data_and_config_are_out_of_scope(self, m):
        # グリッド幅（column_widths）がデータ幅・設定列より広くても、
        # データも設定もない列の空セルは違反にしない
        state = make_state(
            VALUES,
            column_widths=[100, 300, 100, 100, 100],
            row_heights=[38, 26, 26],
            cell_formats=all_top(3),
        )
        gateway = FakeGateway(state)
        assert check_sheet(gateway, va_target(), m) == []

    def test_anchor_scope_excludes_rows_below_anchor(self, m):
        values = VALUES + [["ghi", ""]]
        formats = all_top(4)
        formats[3][0] = dict(BOTTOM)  # anchor B 列が空の行は検査範囲外
        gateway = clean_gateway(formats, values=values)
        target = va_target(append_anchor_column="B")
        assert va_violations(check_sheet(gateway, target, m)) == []


class TestCheckerFix:
    def test_fix_aligns_and_preserves_values(self, m):
        formats = all_top(3)
        formats[0][1] = dict(BOTTOM)
        formats[1][1] = {}
        gateway = clean_gateway(formats)
        fixed = fix_sheet(gateway, va_target(), m)
        assert {v.location for v in va_violations(fixed)} == {"B1", "B2"}
        assert va_violations(check_sheet(gateway, va_target(), m)) == []
        state = gateway.get_state("dummy-spreadsheet-id-0001", "テストタブ")
        assert state.values == VALUES  # 値には触らない
        assert state.cell_formats[0][1]["verticalAlignment"] == "TOP"
        assert state.cell_formats[1][1]["verticalAlignment"] == "TOP"


class TestWriterForcesVerticalAlignment:
    def _gateway(self):
        values = [["見出し", "メモ"], ["abc", "x"]]
        formats = [[{}, {}], [dict(BOTTOM), dict(BOTTOM)]]
        state = make_state(
            values,
            column_widths=[100, 300],
            row_heights=[38, 26],
            cell_formats=formats,
        )
        return FakeGateway(state)

    def test_rule_on_forces_configured_value_over_inheritance(self, m):
        gateway = self._gateway()
        append_rows(gateway, va_target(), [["def", "y"]], m)
        state = gateway.get_state("dummy-spreadsheet-id-0001", "テストタブ")
        assert state.cell_formats[2][0]["verticalAlignment"] == "TOP"
        assert state.cell_formats[2][1]["verticalAlignment"] == "TOP"

    def test_rule_off_inherits_as_before(self, m):
        gateway = self._gateway()
        append_rows(gateway, va_target(vertical_alignment=None), [["def", "y"]], m)
        state = gateway.get_state("dummy-spreadsheet-id-0001", "テストタブ")
        assert state.cell_formats[2][0]["verticalAlignment"] == "BOTTOM"
        assert state.cell_formats[2][1]["verticalAlignment"] == "BOTTOM"
