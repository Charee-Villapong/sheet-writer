"""仕様（writer）: anchor 経路のリセット残留を _verify が負側で検証する。

_reset_format_request で消したはずの書式（numberFormat・
backgroundColorStyle・textFormat のサブキー等）が、gateway 側の
削除失敗で残った場合は VerificationError にする。従来は背景色
（background_rule 有効時）しか負側チェックがなく、他のキーの
残留は検証を素通りしていた。

削除失敗は、フィールドマスクの一部を黙って落とす Fake サブクラスで
再現する（マスクに無いキーは Fake の意味論でも削除されない）。
"""

import pytest
from fake_gateway import FakeGateway, make_state

from sheet_writer.config import ColumnPolicy, Target
from sheet_writer.errors import VerificationError
from sheet_writer.writer import append_rows

STYLE_PALE = {"rgbColor": {"red": 0.9, "green": 0.95, "blue": 0.9}}
DATE_FORMAT = {"type": "DATE", "pattern": "yyyy/mm/dd"}

COLUMNS = {
    "A": ColumnPolicy(mode="fit"),
    "B": ColumnPolicy(mode="wrap", width_px=300),
    "C": ColumnPolicy(mode="fit"),
}

NEW_ROW = ["", "新しいタスク", "5"]

DATA_FORMATS = [
    {"horizontalAlignment": "LEFT"},
    {"horizontalAlignment": "LEFT"},
    {"horizontalAlignment": "RIGHT"},
]


class MaskDroppingGateway(FakeGateway):
    """repeatCell のフィールドマスクから指定キーを落とす gateway。

    落としたキーは削除対象から外れるため、書込先セルに元々あった
    そのキーの書式が残留する（実 API で削除が効かなかった状況の再現）。
    """

    def __init__(self, state, drop_keys=(), **kwargs):
        super().__init__(state, **kwargs)
        self._drop_tokens = {f"userEnteredFormat.{key}" for key in drop_keys}

    def _apply_repeat_cell(self, body):
        fields = body.get("fields", "")
        kept = [
            token
            for token in fields.split(",")
            if token.strip() not in self._drop_tokens
        ]
        super()._apply_repeat_cell({**body, "fields": ",".join(kept)})


def anchor_target(background_rule=False):
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="テストタブ",
        columns=dict(COLUMNS),
        append_anchor_column="B",
        background_rule=background_rule,
    )


def preset_gateway(preset_format, gateway_class=FakeGateway, **gateway_kwargs):
    """事前設定行（5〜7行目）の全セルに preset_format を持たせたシート。"""
    values = [
        ["チェック", "タスク", "数量"],
        ["FALSE", "タスク1", "10"],
        ["FALSE", "タスク2", "20"],
        ["FALSE", "タスク3", "30"],
        ["FALSE", "", ""],
        ["FALSE", "", ""],
        ["FALSE", "", ""],
    ]
    formats = [[{"textFormat": {"bold": True}} for _ in range(3)]]
    formats += [[dict(cell) for cell in DATA_FORMATS] for _ in range(3)]
    formats += [[dict(preset_format) for _ in range(3)] for _ in range(3)]
    state = make_state(
        values,
        column_widths=[100, 300, 100],
        row_heights=[38, 26, 26, 26, 21, 21, 21],
        cell_formats=formats,
    )
    return gateway_class(state, **gateway_kwargs)


class TestResidualResetKeysAreCaught:
    def test_number_format_residual_raises(self, m):
        gateway = preset_gateway(
            {"numberFormat": DATE_FORMAT},
            gateway_class=MaskDroppingGateway,
            drop_keys={"numberFormat"},
        )
        with pytest.raises(VerificationError) as excinfo:
            append_rows(gateway, anchor_target(), [NEW_ROW], m)
        assert "numberFormat" in str(excinfo.value)

    def test_background_style_residual_raises_even_without_rule(self, m):
        # background_rule 無効時は従来の背景チェックが働かないが、
        # anchor 経路のリセット対象としては残留を検出する
        gateway = preset_gateway(
            {"backgroundColorStyle": STYLE_PALE},
            gateway_class=MaskDroppingGateway,
            drop_keys={"backgroundColorStyle"},
        )
        with pytest.raises(VerificationError) as excinfo:
            append_rows(gateway, anchor_target(background_rule=False), [NEW_ROW], m)
        assert "backgroundColorStyle" in str(excinfo.value)

    def test_text_format_subkey_residual_raises(self, m):
        # textFormat は親キー（全体削除）とサブキーの両方がマスクに
        # 挙がるため、bold の残留には両方の削除失敗を再現する
        gateway = preset_gateway(
            {"textFormat": {"bold": True}},
            gateway_class=MaskDroppingGateway,
            drop_keys={"textFormat", "textFormat.bold"},
        )
        with pytest.raises(VerificationError) as excinfo:
            append_rows(gateway, anchor_target(), [NEW_ROW], m)
        assert "textFormat.bold" in str(excinfo.value)


class TestClearedResetKeysPass:
    def test_append_succeeds_when_reset_applies(self, m):
        # 削除が効く通常の gateway では、事前設定行にリセット対象の
        # 書式があっても検証を通る
        gateway = preset_gateway(
            {
                "numberFormat": DATE_FORMAT,
                "backgroundColorStyle": STYLE_PALE,
                "textFormat": {"bold": True},
            }
        )
        result = append_rows(gateway, anchor_target(), [NEW_ROW], m)
        assert result.appended_rows == [5]
        new_formats = gateway.state.cell_formats[4]
        for cell in new_formats:
            assert "numberFormat" not in cell
            assert "backgroundColorStyle" not in cell
            assert "textFormat" not in cell
