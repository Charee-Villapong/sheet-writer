"""writer.append_rows の振る舞いを FakeGateway で固定する。

固定する仕様:
- 列幅は「ヘッダー（太字で計測）＋既存全データ行＋追加行」の最長値から計算する
- 列幅は現在より縮めない
- fit 列は必要幅まで拡大、wrap 列は max(現在幅, ポリシー幅 or 既定300)
- wrap 列の追加セルには WRAP を設定する
- 追加行の高さは最終列幅での最大行数から決める
- 追加行の書式は上の行から継承し、交互色なら同パリティ行の書式を使う
- 書き込み後に読み戻して検証し、不一致なら VerificationError
"""

import pytest

from fake_gateway import FakeGateway, make_state
from sheet_writer.config import ColumnPolicy
from sheet_writer.errors import VerificationError
from sheet_writer.writer import append_rows

WHITE = {"red": 1.0, "green": 1.0, "blue": 1.0}
ALT_GREEN = {"red": 0.917, "green": 0.957, "blue": 0.925}  # #EAF4EC 相当
NUMBER_FORMAT = {"type": "NUMBER", "pattern": "#,##0"}


def data_format(bg, align, number_format=None):
    fmt = {"backgroundColor": bg, "horizontalAlignment": align}
    if number_format is not None:
        fmt["numberFormat"] = number_format
    return fmt


def basic_gateway(**fake_kwargs):
    """ヘッダー + データ2行（同背景）のシート。

    列: A=名前（fit） / B=メモ（wrap 300） / C=数量（未指定 = fit）
    現在幅: A=50, B=100, C=80
    """
    values = [
        ["名前", "メモ", "数量"],
        ["abc", "x", "10"],
        ["def", "y", "20"],
    ]
    formats = [
        [{"textFormat": {"bold": True}} for _ in range(3)],
        [
            data_format(WHITE, "LEFT"),
            data_format(WHITE, "LEFT"),
            data_format(WHITE, "RIGHT", NUMBER_FORMAT),
        ],
        [
            data_format(WHITE, "LEFT"),
            data_format(WHITE, "LEFT"),
            data_format(WHITE, "RIGHT", NUMBER_FORMAT),
        ],
    ]
    state = make_state(
        values,
        column_widths=[50, 100, 80],
        row_heights=[38, 26, 26],
        cell_formats=formats,
    )
    return FakeGateway(state, **fake_kwargs)


def basic_target(make_target):
    return make_target(
        {
            "A": ColumnPolicy(mode="fit"),
            "B": ColumnPolicy(mode="wrap", width_px=300),
            # C は未指定 → fit 扱い
        }
    )


class TestBasicAppend:
    def test_appended_row_number_and_values(self, m, make_target):
        gateway = basic_gateway()
        result = append_rows(
            gateway, basic_target(make_target), [["あいうえお", "あ" * 30, "12345"]], m
        )
        assert result.appended_rows == [4]
        assert gateway.state.values[3] == ["あいうえお", "あ" * 30, "12345"]

    def test_column_widths_fit_wrap_and_unspecified(self, m, make_target):
        gateway = basic_gateway()
        result = append_rows(
            gateway, basic_target(make_target), [["あいうえお", "あ" * 30, "12345"]], m
        )
        # A(fit): 最長は追加行 "あいうえお" = 57.5+20 → 78
        # B(wrap): max(現在100, ポリシー300) = 300
        # C(未指定=fit): 最長は追加行 "12345" = 51.5+20 → 52 だが現在80を縮めない
        assert result.column_widths == {"A": 78, "B": 300, "C": 80}
        assert gateway.state.column_widths == [78, 300, 80]

    def test_width_change_is_sent_as_dimension_request(self, m, make_target):
        gateway = basic_gateway()
        append_rows(
            gateway, basic_target(make_target), [["あいうえお", "あ" * 30, "12345"]], m
        )
        column_requests = [
            req["updateDimensionProperties"]
            for req in gateway.batch_requests
            if "updateDimensionProperties" in req
            and req["updateDimensionProperties"]["range"]["dimension"] == "COLUMNS"
        ]
        sent = {
            (req["range"]["startIndex"], req["properties"]["pixelSize"])
            for req in column_requests
        }
        assert (0, 78) in sent  # 列 A → 78px
        assert (1, 300) in sent  # 列 B → 300px

    def test_wrap_is_set_only_on_wrap_column(self, m, make_target):
        gateway = basic_gateway()
        append_rows(
            gateway, basic_target(make_target), [["あいうえお", "あ" * 30, "12345"]], m
        )
        new_formats = gateway.state.cell_formats[3]
        assert new_formats[1]["wrapStrategy"] == "WRAP"
        assert new_formats[0].get("wrapStrategy") != "WRAP"
        assert new_formats[2].get("wrapStrategy") != "WRAP"

    def test_row_height_from_wrapped_lines(self, m, make_target):
        gateway = basic_gateway()
        result = append_rows(
            gateway, basic_target(make_target), [["あいうえお", "あ" * 30, "12345"]], m
        )
        # B の追加セルは 300px 幅で 2 行（345px / 280px）→ 高さ 42
        assert result.row_heights == {4: 42}
        assert gateway.state.row_heights[3] == 42

    def test_single_line_row_gets_min_height(self, m, make_target):
        gateway = basic_gateway()
        result = append_rows(gateway, basic_target(make_target), [["ab", "x", "1"]], m)
        assert result.row_heights == {4: 26}
        assert gateway.state.row_heights[3] == 26

    def test_format_inherited_from_row_above(self, m, make_target):
        gateway = basic_gateway()
        append_rows(
            gateway, basic_target(make_target), [["あいうえお", "あ" * 30, "12345"]], m
        )
        new_formats = gateway.state.cell_formats[3]
        assert new_formats[0]["backgroundColor"] == WHITE
        assert new_formats[0]["horizontalAlignment"] == "LEFT"
        assert new_formats[2]["backgroundColor"] == WHITE
        assert new_formats[2]["horizontalAlignment"] == "RIGHT"
        assert new_formats[2]["numberFormat"] == NUMBER_FORMAT


class TestWidthCalculationSources:
    def test_existing_longest_row_drives_width(self, m, make_target):
        # 既存データ行の最長値（"あ"*20 = 250）まで広げる。追加行は短い。
        state = make_state(
            [["見出し", "b"], ["あ" * 20, "x"], ["ab", "y"]],
            column_widths=[100, 100],
            row_heights=[38, 26, 26],
        )
        gateway = FakeGateway(state)
        target = make_target(
            {"A": ColumnPolicy(mode="fit"), "B": ColumnPolicy(mode="fit")}
        )
        result = append_rows(gateway, target, [["短", "z"]], m)
        assert result.column_widths["A"] == 250
        assert gateway.state.column_widths[0] == 250

    def test_header_is_measured_bold(self, m, make_target):
        # ヘッダー "あ"*10 は太字計測で 120+20=140（通常計測なら 135）
        state = make_state(
            [["あ" * 10, "b"], ["x", "y"]],
            column_widths=[100, 100],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        target = make_target(
            {"A": ColumnPolicy(mode="fit"), "B": ColumnPolicy(mode="fit")}
        )
        result = append_rows(gateway, target, [["z", "w"]], m)
        assert result.column_widths["A"] == 140

    def test_fit_column_never_shrinks(self, m, make_target):
        state = make_state(
            [["見出し", "b"], ["x", "y"]],
            column_widths=[500, 100],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        target = make_target(
            {"A": ColumnPolicy(mode="fit"), "B": ColumnPolicy(mode="fit")}
        )
        result = append_rows(gateway, target, [["z", "w"]], m)
        assert result.column_widths["A"] == 500
        assert gateway.state.column_widths[0] == 500
        # 縮める方向の列幅リクエストが送られていないこと
        for req in gateway.batch_requests:
            body = req.get("updateDimensionProperties")
            if body and body["range"]["dimension"] == "COLUMNS":
                assert body["properties"]["pixelSize"] >= 100

    def test_wrap_column_uses_default_width_when_policy_has_none(
        self, m, make_target
    ):
        state = make_state(
            [["見出し", "メモ"], ["x", "y"]],
            column_widths=[100, 100],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        target = make_target(
            {"A": ColumnPolicy(mode="fit"), "B": ColumnPolicy(mode="wrap")}
        )
        result = append_rows(gateway, target, [["z", "w"]], m)
        # ポリシー幅なし → Measures の既定 300
        assert result.column_widths["B"] == 300

    def test_wrap_column_never_shrinks_below_current(self, m, make_target):
        state = make_state(
            [["見出し", "メモ"], ["x", "y"]],
            column_widths=[100, 400],
            row_heights=[38, 26],
        )
        gateway = FakeGateway(state)
        target = make_target(
            {
                "A": ColumnPolicy(mode="fit"),
                "B": ColumnPolicy(mode="wrap", width_px=300),
            }
        )
        result = append_rows(gateway, target, [["z", "w"]], m)
        # max(現在400, ポリシー300) = 400
        assert result.column_widths["B"] == 400
        assert gateway.state.column_widths[1] == 400


class TestAlternatingColors:
    def test_same_parity_format_is_used(self, m, make_target):
        # データ行が白 → 緑の交互色。追加行（4行目・偶数）は2行上（2行目）の書式を使う
        values = [
            ["名前", "メモ"],
            ["abc", "x"],
            ["def", "y"],
        ]
        formats = [
            [{"textFormat": {"bold": True}} for _ in range(2)],
            [data_format(WHITE, "LEFT"), data_format(WHITE, "LEFT")],
            [data_format(ALT_GREEN, "CENTER"), data_format(ALT_GREEN, "CENTER")],
        ]
        state = make_state(
            values,
            column_widths=[100, 100],
            row_heights=[38, 26, 26],
            cell_formats=formats,
        )
        gateway = FakeGateway(state)
        target = make_target(
            {"A": ColumnPolicy(mode="fit"), "B": ColumnPolicy(mode="fit")}
        )
        append_rows(gateway, target, [["ghi", "z"]], m)
        new_formats = gateway.state.cell_formats[3]
        assert new_formats[0]["backgroundColor"] == WHITE
        assert new_formats[0]["horizontalAlignment"] == "LEFT"
        assert new_formats[1]["backgroundColor"] == WHITE


class TestMultipleRows:
    def test_two_rows_appended_with_individual_heights(self, m, make_target):
        gateway = basic_gateway()
        result = append_rows(
            gateway,
            basic_target(make_target),
            [["ab", "x", "1"], ["cd", "あ" * 30, "2"]],
            m,
        )
        assert result.appended_rows == [4, 5]
        assert result.row_heights[4] == 26
        assert result.row_heights[5] == 42
        assert gateway.state.values[4] == ["cd", "あ" * 30, "2"]


class TestVerificationAndErrors:
    def test_empty_rows_raise_value_error(self, m, make_target):
        gateway = basic_gateway()
        with pytest.raises(ValueError):
            append_rows(gateway, basic_target(make_target), [], m)

    def test_ignored_width_change_raises_verification_error(self, m, make_target):
        # 列幅の変更を無視する Fake → 読み戻し検証で必ず失敗する
        gateway = basic_gateway(ignore_column_widths=True)
        with pytest.raises(VerificationError) as excinfo:
            append_rows(
                gateway,
                basic_target(make_target),
                [["あいうえお", "あ" * 30, "12345"]],
                m,
            )
        assert str(excinfo.value) != ""

    def test_ignored_wrap_change_raises_verification_error(self, m, make_target):
        # 書式の変更を無視する Fake → WRAP 未設定のままなので検証で失敗する
        gateway = basic_gateway(ignore_repeat_cell=True)
        with pytest.raises(VerificationError):
            append_rows(
                gateway,
                basic_target(make_target),
                [["あいうえお", "あ" * 30, "12345"]],
                m,
            )

    def test_dropped_values_raise_verification_error(self, m, make_target):
        # append したはずの値が残っていない → 検証で失敗する
        gateway = basic_gateway(drop_appended_values=True)
        with pytest.raises(VerificationError):
            append_rows(
                gateway,
                basic_target(make_target),
                [["あいうえお", "あ" * 30, "12345"]],
                m,
            )

    def test_no_verification_error_when_state_matches(self, m, make_target):
        # 正常系では VerificationError が出ず、結果が返る
        gateway = basic_gateway()
        result = append_rows(
            gateway, basic_target(make_target), [["あいうえお", "短い", "1"]], m
        )
        assert result.appended_rows == [4]
