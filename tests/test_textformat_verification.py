"""R1: writer の書き込み後検証は textFormat のサブキーも突き合わせる。

仕様:
- 追加行が継承する textFormat のサブキー（bold・italic・fontSize・
  fontFamily）も検証対象にする。
- 意図した textFormat と実状態が異なれば VerificationError。
- Fake の ignore_text_format（textFormat だけ適用されない状況）で検証する。
"""

import pytest
from fake_gateway import FakeGateway, make_state

from sheet_writer.config import ColumnPolicy
from sheet_writer.errors import VerificationError
from sheet_writer.writer import append_rows

TEXT_FORMAT = {
    "bold": True,
    "italic": True,
    "fontSize": 11,
    "fontFamily": "Arial",
}


def gateway(**fake_kwargs):
    """データ行が textFormat を持つシート（test_writer.py の基本形）。"""
    values = [
        ["名前", "メモ", "数量"],
        ["abc", "x", "10"],
        ["def", "y", "20"],
    ]
    data_row = [
        {"textFormat": dict(TEXT_FORMAT), "horizontalAlignment": "LEFT"},
        {"textFormat": dict(TEXT_FORMAT), "horizontalAlignment": "LEFT"},
        {"textFormat": dict(TEXT_FORMAT), "horizontalAlignment": "RIGHT"},
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


def target(make_target):
    return make_target(
        {
            "A": ColumnPolicy(mode="fit"),
            "B": ColumnPolicy(mode="wrap", width_px=300),
            "C": ColumnPolicy(mode="fit"),
        }
    )


class TestTextFormatVerification:
    def test_text_format_is_inherited_and_verified(self, m, make_target):
        gw = gateway()
        result = append_rows(gw, target(make_target), [["あいうえお", "短い", "1"]], m)
        assert result.appended_rows == [4]
        for cell in gw.state.cell_formats[3]:
            assert cell["textFormat"] == TEXT_FORMAT

    def test_ignored_text_format_raises_verification_error(self, m, make_target):
        # textFormat だけが適用されない状況では、検証で必ず失敗する
        gw = gateway(ignore_text_format=True)
        with pytest.raises(VerificationError):
            append_rows(gw, target(make_target), [["あいうえお", "短い", "1"]], m)
