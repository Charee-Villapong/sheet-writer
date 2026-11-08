"""仕様1（本題）: 背景色チェック — checker / writer / Fake の意味論。

checker（check_sheet / fix_sheet）:
- background_rule が有効なターゲットでのみ、データ行（2行目以降）の
  セルに背景色が設定されていたら違反にする。ヘッダー行は対象外。
- 「背景色が設定されている」とは userEnteredFormat に backgroundColor
  または backgroundColorStyle のキーがあること。白の明示設定
  （red=green=blue=1）も違反。未設定（キーなし）は正常。
- 違反はセル単位: kind="background"、location は "B3" のようなセル番地、
  expected="未設定"。
- 値が空のセルでも、データ行の範囲内なら背景があれば違反。
- fix では違反セルの塗りを除去し、再検査で違反ゼロになる。除去は
  repeatCell のフィールドマスクで backgroundColor と
  backgroundColorStyle の両方を対象にする。

writer（append_rows）:
- background_rule 有効時: 追加行の書式継承で背景色を持ち込まない。
  他の書式キー（配置・数値書式・wrap 等）の継承は従来どおり。
- 追加行のセルに背景色が残っていたら VerificationError。
- ルール無効時: 従来どおり背景を継承する。
"""

import pytest
from fake_gateway import DUMMY_SHEET_ID, FakeGateway, make_state

from sheet_writer.checker import check_sheet, fix_sheet
from sheet_writer.config import ColumnPolicy, Target
from sheet_writer.errors import VerificationError
from sheet_writer.writer import append_rows

WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
PALE = {"red": 0.9, "green": 0.95, "blue": 0.9}
STYLE_WHITE = {"rgbColor": {"red": 1.0, "green": 1.0, "blue": 1.0}}
NUMBER_FORMAT = {"type": "NUMBER", "pattern": "#,##0"}

COLUMNS = {
    "A": ColumnPolicy(mode="fit"),
    "B": ColumnPolicy(mode="wrap", width_px=300),
}


def bg_target(background_rule=True, columns=None):
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="テストタブ",
        columns=columns if columns is not None else dict(COLUMNS),
        background_rule=background_rule,
    )


def background_violations(violations):
    return [v for v in violations if v.kind == "background"]


def clean_gateway_with_formats(formats, values=None, **fake_kwargs):
    """背景以外はクリーンなシート（幅・高さ・WRAP の違反が出ない寸法）。"""
    if values is None:
        values = [["名前", "メモ"], ["abc", "x"], ["def", "y"]]
    state = make_state(
        values,
        column_widths=[100, 300],
        row_heights=[38] + [26] * (len(values) - 1),
        cell_formats=formats,
    )
    return FakeGateway(state, **fake_kwargs)


# ---------------------------------------------------------------------------
# checker: 検出
# ---------------------------------------------------------------------------


class TestCheckerDetectsBackground:
    def test_background_color_on_data_cell(self, m):
        gateway = clean_gateway_with_formats(
            [[{}, {}], [{"backgroundColor": PALE}, {}], [{}, {}]]
        )
        violations = check_sheet(gateway, bg_target(), m)
        bg = background_violations(violations)
        assert len(bg) == 1
        assert bg[0].location == "A2"
        assert bg[0].expected == "未設定"

    def test_background_color_style_key_also_counts(self, m):
        gateway = clean_gateway_with_formats(
            [[{}, {}], [{}, {"backgroundColorStyle": STYLE_WHITE}], [{}, {}]]
        )
        bg = background_violations(check_sheet(gateway, bg_target(), m))
        assert len(bg) == 1
        assert bg[0].location == "B2"
        assert bg[0].expected == "未設定"

    def test_explicit_white_is_a_violation(self, m):
        # 白（red=green=blue=1）の明示設定も「設定されている」ので違反
        gateway = clean_gateway_with_formats(
            [[{}, {}], [{}, {}], [{}, {"backgroundColor": WHITE}]]
        )
        bg = background_violations(check_sheet(gateway, bg_target(), m))
        assert len(bg) == 1
        assert bg[0].location == "B3"

    def test_header_row_is_exempt(self, m):
        gateway = clean_gateway_with_formats(
            [
                [{"backgroundColor": PALE}, {"backgroundColorStyle": STYLE_WHITE}],
                [{}, {}],
                [{}, {}],
            ]
        )
        assert check_sheet(gateway, bg_target(), m) == []

    def test_empty_value_cell_with_background_is_a_violation(self, m):
        gateway = clean_gateway_with_formats(
            [[{}, {}], [{}, {"backgroundColor": PALE}], [{}, {}]],
            values=[["名前", "メモ"], ["abc", ""], ["def", "y"]],
        )
        bg = background_violations(check_sheet(gateway, bg_target(), m))
        assert len(bg) == 1
        assert bg[0].location == "B2"

    def test_each_cell_reported_separately(self, m):
        gateway = clean_gateway_with_formats(
            [
                [{}, {}],
                [{"backgroundColor": PALE}, {"backgroundColor": PALE}],
                [{}, {"backgroundColorStyle": STYLE_WHITE}],
            ]
        )
        bg = background_violations(check_sheet(gateway, bg_target(), m))
        assert sorted(v.location for v in bg) == ["A2", "B2", "B3"]
        assert all(v.expected == "未設定" for v in bg)

    def test_no_background_is_clean(self, m):
        gateway = clean_gateway_with_formats([[{}, {}], [{}, {}], [{}, {}]])
        assert check_sheet(gateway, bg_target(), m) == []

    def test_other_format_keys_are_not_background(self, m):
        gateway = clean_gateway_with_formats(
            [
                [{}, {}],
                [
                    {"horizontalAlignment": "CENTER"},
                    {"wrapStrategy": "WRAP", "numberFormat": NUMBER_FORMAT},
                ],
                [{}, {}],
            ]
        )
        assert check_sheet(gateway, bg_target(), m) == []

    def test_rule_disabled_target_ignores_background(self, m):
        gateway = clean_gateway_with_formats(
            [
                [{}, {}],
                [{"backgroundColor": PALE}, {"backgroundColorStyle": STYLE_WHITE}],
                [{}, {}],
            ]
        )
        assert check_sheet(gateway, bg_target(background_rule=False), m) == []


# ---------------------------------------------------------------------------
# checker: fix
# ---------------------------------------------------------------------------


class TestFixRemovesBackground:
    def test_fix_clears_color_and_style_and_recheck_is_clean(self, m):
        gateway = clean_gateway_with_formats(
            [
                [{"backgroundColor": PALE}, {}],
                [{"backgroundColor": PALE}, {"backgroundColorStyle": STYLE_WHITE}],
                [{}, {}],
            ]
        )
        fixed = fix_sheet(gateway, bg_target(), m)
        assert sorted(v.location for v in background_violations(fixed)) == [
            "A2",
            "B2",
        ]
        state = gateway.state
        # ヘッダー行の背景は対象外なので残る
        assert state.cell_formats[0][0] == {"backgroundColor": PALE}
        # データ行の塗りは両キーとも除去される
        for row in state.cell_formats[1:]:
            for cell in row:
                assert "backgroundColor" not in cell
                assert "backgroundColorStyle" not in cell
        assert check_sheet(gateway, bg_target(), m) == []

    def test_fix_preserves_other_format_keys(self, m):
        gateway = clean_gateway_with_formats(
            [
                [{}, {}],
                [
                    {"backgroundColor": PALE, "horizontalAlignment": "CENTER"},
                    {
                        "backgroundColor": PALE,
                        "wrapStrategy": "WRAP",
                        "numberFormat": NUMBER_FORMAT,
                    },
                ],
                [{}, {}],
            ]
        )
        fix_sheet(gateway, bg_target(), m)
        state = gateway.state
        assert state.cell_formats[1][0] == {"horizontalAlignment": "CENTER"}
        assert state.cell_formats[1][1] == {
            "wrapStrategy": "WRAP",
            "numberFormat": NUMBER_FORMAT,
        }
        # 値は一切変わっていない
        assert state.values == [["名前", "メモ"], ["abc", "x"], ["def", "y"]]

    def test_fix_uses_field_mask_covering_both_background_keys(self, m):
        gateway = clean_gateway_with_formats(
            [[{}, {}], [{"backgroundColor": PALE}, {}], [{}, {}]]
        )
        fix_sheet(gateway, bg_target(), m)
        fields_sent = " ".join(
            str(req["repeatCell"].get("fields", ""))
            for req in gateway.batch_requests
            if "repeatCell" in req
        )
        # 除去は repeatCell のフィールドマスクで両キーを対象にする
        assert "backgroundColor" in fields_sent
        assert "backgroundColorStyle" in fields_sent

    def test_fix_with_rule_disabled_changes_nothing(self, m):
        gateway = clean_gateway_with_formats(
            [[{}, {}], [{"backgroundColor": PALE}, {}], [{}, {}]]
        )
        before = gateway.state
        assert fix_sheet(gateway, bg_target(background_rule=False), m) == []
        assert gateway.state == before


# ---------------------------------------------------------------------------
# Fake のフィールドマスク意味論（テスト基盤の担保）
# ---------------------------------------------------------------------------


def clearing_request(row, col):
    """背景除去の repeatCell リクエスト（マスクに両キーを挙げ、cell には
    含めない形。実 API ではマスクにあって cell に無いフィールドは
    削除される）。"""
    return {
        "repeatCell": {
            "range": {
                "sheetId": DUMMY_SHEET_ID,
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


class TestFakeFieldMaskSemantics:
    def test_masked_but_absent_background_fields_are_deleted(self):
        gateway = clean_gateway_with_formats(
            [
                [{}, {}],
                [
                    {
                        "backgroundColor": PALE,
                        "backgroundColorStyle": STYLE_WHITE,
                        "horizontalAlignment": "CENTER",
                    },
                    {},
                ],
                [{}, {}],
            ]
        )
        gateway.batch_update("dummy-spreadsheet-id-0001", [clearing_request(1, 0)])
        assert gateway.state.cell_formats[1][0] == {"horizontalAlignment": "CENTER"}

    def test_background_present_in_cell_is_applied_not_deleted(self):
        gateway = clean_gateway_with_formats([[{}, {}], [{}, {}], [{}, {}]])
        request = clearing_request(1, 0)
        request["repeatCell"]["cell"] = {"userEnteredFormat": {"backgroundColor": PALE}}
        gateway.batch_update("dummy-spreadsheet-id-0001", [request])
        assert gateway.state.cell_formats[1][0]["backgroundColor"] == PALE


# ---------------------------------------------------------------------------
# writer: 追加行への持ち込み防止と検証
# ---------------------------------------------------------------------------


def writer_gateway(**fake_kwargs):
    """ヘッダー + データ2行。データ行は背景・配置・数値書式を持つ。"""
    values = [
        ["名前", "メモ", "数量"],
        ["abc", "x", "10"],
        ["def", "y", "20"],
    ]
    data_row = [
        {"backgroundColor": WHITE, "horizontalAlignment": "LEFT"},
        {"backgroundColor": WHITE, "horizontalAlignment": "LEFT"},
        {
            "backgroundColor": WHITE,
            "horizontalAlignment": "RIGHT",
            "numberFormat": NUMBER_FORMAT,
        },
    ]
    formats = [
        [{"textFormat": {"bold": True}} for _ in range(3)],
        [dict(cell) for cell in data_row],
        [dict(cell) for cell in data_row],
    ]
    state = make_state(
        values,
        column_widths=[50, 100, 80],
        row_heights=[38, 26, 26],
        cell_formats=formats,
    )
    return FakeGateway(state, **fake_kwargs)


def writer_target(background_rule):
    return bg_target(
        background_rule=background_rule,
        columns={
            "A": ColumnPolicy(mode="fit"),
            "B": ColumnPolicy(mode="wrap", width_px=300),
            "C": ColumnPolicy(mode="fit"),
        },
    )


class TestWriterBackgroundRule:
    def test_appended_row_has_no_background_when_rule_on(self, m):
        gateway = writer_gateway()
        append_rows(gateway, writer_target(True), [["あいうえお", "短い", "1"]], m)
        for cell in gateway.state.cell_formats[3]:
            assert "backgroundColor" not in cell
            assert "backgroundColorStyle" not in cell

    def test_appended_row_has_no_background_style_when_rule_on(self, m):
        values = [["名前", "メモ"], ["abc", "x"], ["def", "y"]]
        style_row = [
            {"backgroundColorStyle": STYLE_WHITE, "horizontalAlignment": "LEFT"},
            {"backgroundColorStyle": STYLE_WHITE, "horizontalAlignment": "LEFT"},
        ]
        formats = [
            [{"textFormat": {"bold": True}} for _ in range(2)],
            [dict(cell) for cell in style_row],
            [dict(cell) for cell in style_row],
        ]
        state = make_state(
            values,
            column_widths=[100, 300],
            row_heights=[38, 26, 26],
            cell_formats=formats,
        )
        gateway = FakeGateway(state)
        target = bg_target(background_rule=True)
        append_rows(gateway, target, [["ghi", "z"]], m)
        for cell in gateway.state.cell_formats[3]:
            assert "backgroundColor" not in cell
            assert "backgroundColorStyle" not in cell
        assert gateway.state.cell_formats[3][0]["horizontalAlignment"] == "LEFT"

    def test_other_formats_still_inherited_when_rule_on(self, m):
        gateway = writer_gateway()
        append_rows(
            gateway, writer_target(True), [["あいうえお", "あ" * 30, "12345"]], m
        )
        new_formats = gateway.state.cell_formats[3]
        assert new_formats[0]["horizontalAlignment"] == "LEFT"
        assert new_formats[2]["horizontalAlignment"] == "RIGHT"
        assert new_formats[2]["numberFormat"] == NUMBER_FORMAT
        # wrap 列の WRAP 設定も従来どおり
        assert new_formats[1]["wrapStrategy"] == "WRAP"

    def test_appended_row_keeps_background_when_rule_off(self, m):
        gateway = writer_gateway()
        append_rows(gateway, writer_target(False), [["あいうえお", "短い", "1"]], m)
        for cell in gateway.state.cell_formats[3]:
            assert cell["backgroundColor"] == WHITE

    def test_background_stuck_on_appended_row_raises_verification_error(self, m):
        # append の書式継承で背景が付いてしまい、除去も効かない状況では
        # 黙って成功せず VerificationError になる
        gateway = writer_gateway(keep_appended_background=True)
        with pytest.raises(VerificationError):
            append_rows(gateway, writer_target(True), [["あいうえお", "短い", "1"]], m)

    def test_stuck_background_is_accepted_when_rule_off(self, m):
        gateway = writer_gateway(keep_appended_background=True)
        result = append_rows(
            gateway, writer_target(False), [["あいうえお", "短い", "1"]], m
        )
        assert result.appended_rows == [4]
        assert gateway.state.cell_formats[3][0]["backgroundColor"] == WHITE
