"""M3: ヘッダー行 38px を担保対象にする（先行テスト）。

仕様（QA 必須対応 M3）:
- Measures.header_height_px = 38 が担保値。ヘッダー行（1行目）の
  高さは 38px を下限として担保する（列幅と同じ「縮めない」原則:
  既に 38 より大きい場合は縮めない）。
- writer（append）: 追加時にヘッダー高が 38 未満なら 38 へ引き上げ、
  読み戻し検証でもヘッダー高を確認する。
- checker: ヘッダー高 < 38 を row_height 違反（expected=38）として
  検出し、fix で 38 に直す。ヘッダー高が 38 以上のシートでは
  ヘッダーに関する違反を出さない。
"""

import pytest

from fake_gateway import FakeGateway, make_state
from sheet_writer.checker import check_sheet, fix_sheet
from sheet_writer.config import ColumnPolicy
from sheet_writer.errors import VerificationError
from sheet_writer.writer import append_rows

HEADER_PX = 38


def header_violations(violations):
    """ヘッダー行（1行目）に関する row_height 違反を取り出す。"""
    return [
        v
        for v in violations
        if v.kind == "row_height" and "1" in str(v.location)
    ]


# ---------------------------------------------------------------------------
# writer（append）
# ---------------------------------------------------------------------------


def writer_gateway(header_height, **fake_kwargs):
    """ヘッダー高だけを差し替えた基本シート（test_writer.py の基本形）。"""
    values = [
        ["名前", "メモ", "数量"],
        ["abc", "x", "10"],
        ["def", "y", "20"],
    ]
    state = make_state(
        values,
        column_widths=[50, 100, 80],
        row_heights=[header_height, 26, 26],
    )
    return FakeGateway(state, **fake_kwargs)


def writer_target(make_target):
    return make_target(
        {
            "A": ColumnPolicy(mode="fit"),
            "B": ColumnPolicy(mode="wrap", width_px=300),
            "C": ColumnPolicy(mode="fit"),
        }
    )


class IgnoreHeaderHeightGateway(FakeGateway):
    """ヘッダー行（1行目）の高さ変更リクエストだけを黙って捨てる Fake。

    writer がヘッダー高を担保し、読み戻し検証でも確認しているかを
    検証するために使う（他の行の高さ変更は通常どおり反映する）。
    """

    def batch_update(self, spreadsheet_id, requests):
        filtered = []
        for req in requests:
            body = req.get("updateDimensionProperties")
            if body:
                rng = body.get("range", {})
                if rng.get("dimension") == "ROWS" and rng.get("startIndex", 0) == 0:
                    continue  # ヘッダー行の高さ変更を無視する
            filtered.append(req)
        super().batch_update(spreadsheet_id, filtered)


class TestWriterHeaderHeight:
    @pytest.mark.parametrize("low_height", [20, 30, 37])
    def test_low_header_is_raised_to_38_on_append(self, m, make_target, low_height):
        gateway = writer_gateway(low_height)
        result = append_rows(
            gateway, writer_target(make_target), [["ab", "x", "1"]], m
        )
        assert result.appended_rows == [4]
        assert gateway.state.row_heights[0] == HEADER_PX

    def test_header_raise_is_sent_as_dimension_request(self, m, make_target):
        gateway = writer_gateway(20)
        append_rows(gateway, writer_target(make_target), [["ab", "x", "1"]], m)
        header_requests = [
            req["updateDimensionProperties"]
            for req in gateway.batch_requests
            if "updateDimensionProperties" in req
            and req["updateDimensionProperties"]["range"]["dimension"] == "ROWS"
            and req["updateDimensionProperties"]["range"].get("startIndex", 0) == 0
        ]
        assert any(
            req["properties"]["pixelSize"] == HEADER_PX for req in header_requests
        )

    def test_header_above_38_is_not_shrunk(self, m, make_target):
        gateway = writer_gateway(50)
        append_rows(gateway, writer_target(make_target), [["ab", "x", "1"]], m)
        assert gateway.state.row_heights[0] == 50

    def test_header_exactly_38_stays(self, m, make_target):
        gateway = writer_gateway(38)
        append_rows(gateway, writer_target(make_target), [["ab", "x", "1"]], m)
        assert gateway.state.row_heights[0] == 38

    def test_ignored_header_raise_fails_verification(self, m, make_target):
        # ヘッダー高の引き上げが反映されなければ、読み戻し検証で失敗する
        state = make_state(
            [["名前", "メモ", "数量"], ["abc", "x", "10"], ["def", "y", "20"]],
            column_widths=[50, 100, 80],
            row_heights=[20, 26, 26],
        )
        gateway = IgnoreHeaderHeightGateway(state)
        with pytest.raises(VerificationError):
            append_rows(gateway, writer_target(make_target), [["ab", "x", "1"]], m)


# ---------------------------------------------------------------------------
# checker（check / fix）
# ---------------------------------------------------------------------------


def checker_gateway(header_height):
    """ヘッダー高以外はクリーンなシート。"""
    state = make_state(
        [["名前", "メモ"], ["abc", "x"]],
        column_widths=[100, 300],
        row_heights=[header_height, 26],
    )
    return FakeGateway(state)


def checker_target(make_target):
    return make_target(
        {"A": ColumnPolicy(mode="fit"), "B": ColumnPolicy(mode="wrap", width_px=300)}
    )


class TestCheckerHeaderHeight:
    @pytest.mark.parametrize("low_height", [20, 30, 37])
    def test_low_header_is_row_height_violation(self, m, make_target, low_height):
        gateway = checker_gateway(low_height)
        violations = check_sheet(gateway, checker_target(make_target), m)
        header = header_violations(violations)
        assert len(header) == 1
        assert header[0].expected == HEADER_PX
        assert header[0].actual == low_height

    @pytest.mark.parametrize("ok_height", [38, 50])
    def test_header_at_or_above_38_is_clean(self, m, make_target, ok_height):
        gateway = checker_gateway(ok_height)
        assert check_sheet(gateway, checker_target(make_target), m) == []

    def test_fix_raises_low_header_to_38(self, m, make_target):
        gateway = checker_gateway(20)
        fixed = fix_sheet(gateway, checker_target(make_target), m)
        assert "row_height" in [v.kind for v in fixed]
        assert gateway.state.row_heights[0] == HEADER_PX
        # 修正後は違反が残っていない
        assert check_sheet(gateway, checker_target(make_target), m) == []

    def test_fix_does_not_shrink_tall_header(self, m, make_target):
        # 列幅違反の修正があっても、38 より大きいヘッダー高は縮めない
        state = make_state(
            [["名前", "メモ"], ["あ" * 10, "x"]],
            column_widths=[50, 300],
            row_heights=[50, 26],
        )
        gateway = FakeGateway(state)
        target = make_target(
            {"A": ColumnPolicy(mode="fit"), "B": ColumnPolicy(mode="fit")}
        )
        fix_sheet(gateway, target, m)
        assert gateway.state.column_widths[0] > 50  # 幅違反は直っている
        assert gateway.state.row_heights[0] == 50


class TestMeasuresGuaranteeValue:
    def test_header_height_measure_is_38(self, m):
        # 担保値の正本は Measures.header_height_px = 38
        assert m.header_height_px == HEADER_PX
