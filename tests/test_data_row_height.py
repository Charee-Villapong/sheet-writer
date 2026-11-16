"""data_row_height_px: 追加データ行の高さ固定（設定・writer・検証）。

仕様:
- Target.data_row_height_px は任意項目（正の整数）。未設定（None）なら
  従来動作: 追加行の高さは折り返し行数から計算し、固定はしない。
- 設定がある場合、writer は追加行の高さを計算値ではなく設定値にそろえ、
  updateDimensionProperties（ROWS, pixelSize=設定値）を追加した行範囲に
  だけ送る。
- 読み戻し検証で追加行の pixelSize（rowMetadata 由来）が設定値と一致
  しなければ VerificationError にして失敗させる（黙って成功にしない）。
- 値が正の整数でない（0・負数・真偽値・文字列・小数）設定は ValueError。
"""

import json

import pytest
from fake_gateway import FakeGateway, make_state

from sheet_writer.config import ColumnPolicy, Target, load_config
from sheet_writer.errors import VerificationError
from sheet_writer.writer import append_rows

FIXED_PX = 21
# B 列（wrap 300px）に "あ"*30 を入れると計算高さは 42 になる入力
LONG_ROW = ["あいうえお", "あ" * 30, "12345"]


def make_fixed_target(height=FIXED_PX):
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="テストタブ",
        columns={
            "A": ColumnPolicy(mode="fit"),
            "B": ColumnPolicy(mode="wrap", width_px=300),
            "C": ColumnPolicy(mode="fit"),
        },
        data_row_height_px=height,
    )


def basic_gateway(**fake_kwargs):
    """ヘッダー（38px）+ データ2行（26px）のシート。列幅 A=50, B=100, C=80。"""
    values = [
        ["名前", "メモ", "数量"],
        ["abc", "x", "10"],
        ["def", "y", "20"],
    ]
    state = make_state(
        values,
        column_widths=[50, 100, 80],
        row_heights=[38, 26, 26],
    )
    return FakeGateway(state, **fake_kwargs)


def row_dimension_requests(gateway):
    """送信された ROWS の updateDimensionProperties を (startIndex, pixelSize) で返す。"""
    return [
        (
            req["updateDimensionProperties"]["range"]["startIndex"],
            req["updateDimensionProperties"]["properties"]["pixelSize"],
        )
        for req in gateway.batch_requests
        if "updateDimensionProperties" in req
        and req["updateDimensionProperties"]["range"]["dimension"] == "ROWS"
    ]


class TestTargetField:
    def test_default_is_none(self):
        target = Target(spreadsheet_id="dummy-id", tab="タブ")
        assert target.data_row_height_px is None

    def test_accepts_positive_int(self):
        target = Target(spreadsheet_id="dummy-id", tab="タブ", data_row_height_px=21)
        assert target.data_row_height_px == 21

    @pytest.mark.parametrize("bad", [0, -1, True, False, "21", 21.5, [21]])
    def test_invalid_value_raises(self, bad):
        with pytest.raises(ValueError):
            Target(spreadsheet_id="dummy-id", tab="タブ", data_row_height_px=bad)


class TestLoadConfig:
    def _write_config(self, tmp_path, targets):
        path = tmp_path / "config.local.json"
        path.write_text(json.dumps({"targets": targets}), encoding="utf-8")
        return path

    def _entry(self, **overrides):
        entry = {"spreadsheet_id": "dummy-id", "tab": "タブ"}
        entry.update(overrides)
        return entry

    def test_reads_data_row_height_px(self, tmp_path):
        path = self._write_config(tmp_path, {"t": self._entry(data_row_height_px=21)})
        config = load_config(path)
        assert config.targets["t"].data_row_height_px == 21

    def test_absent_means_none(self, tmp_path):
        path = self._write_config(tmp_path, {"t": self._entry()})
        config = load_config(path)
        assert config.targets["t"].data_row_height_px is None

    def test_null_means_none(self, tmp_path):
        path = self._write_config(tmp_path, {"t": self._entry(data_row_height_px=None)})
        config = load_config(path)
        assert config.targets["t"].data_row_height_px is None

    @pytest.mark.parametrize("bad", [0, -21, True, "21", 21.5])
    def test_invalid_value_in_json_raises_value_error(self, tmp_path, bad):
        path = self._write_config(tmp_path, {"t": self._entry(data_row_height_px=bad)})
        with pytest.raises(ValueError):
            load_config(path)


class TestWriterFixedHeight:
    def test_fixed_height_is_sent_for_appended_row_only(self, m):
        gateway = basic_gateway()
        result = append_rows(gateway, make_fixed_target(), [LONG_ROW], m)
        # 計算値（42）ではなく設定値（21）が、追加行（index 3）にだけ飛ぶ
        assert row_dimension_requests(gateway) == [(3, FIXED_PX)]
        assert result.row_heights == {4: FIXED_PX}
        assert gateway.state.row_heights[3] == FIXED_PX
        # 既存行の高さは変えない
        assert gateway.state.row_heights[:3] == [38, 26, 26]

    def test_fixed_height_applies_to_each_appended_row(self, m):
        gateway = basic_gateway()
        result = append_rows(
            gateway, make_fixed_target(), [LONG_ROW, ["ab", "x", "1"]], m
        )
        assert row_dimension_requests(gateway) == [(3, FIXED_PX), (4, FIXED_PX)]
        assert result.row_heights == {4: FIXED_PX, 5: FIXED_PX}
        assert gateway.state.row_heights[3:] == [FIXED_PX, FIXED_PX]

    def test_mismatched_readback_height_fails_verification(self, m):
        # 行高の変更を黙って捨てる Fake → 読み戻しが設定値と一致せず失敗する
        gateway = basic_gateway(ignore_row_heights=True)
        with pytest.raises(VerificationError) as excinfo:
            append_rows(gateway, make_fixed_target(), [LONG_ROW], m)
        assert "高さ" in str(excinfo.value)

    def test_without_setting_no_fixed_height_request(self, m, make_target):
        # 設定なしでは固定値（21）のリクエストは飛ばず、従来の計算高さ（42）
        gateway = basic_gateway()
        target = make_target(
            {
                "A": ColumnPolicy(mode="fit"),
                "B": ColumnPolicy(mode="wrap", width_px=300),
                "C": ColumnPolicy(mode="fit"),
            }
        )
        assert target.data_row_height_px is None
        result = append_rows(gateway, target, [LONG_ROW], m)
        assert row_dimension_requests(gateway) == [(3, 42)]
        assert result.row_heights == {4: 42}
        assert gateway.state.row_heights[3] == 42
