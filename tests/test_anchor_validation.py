"""仕様（必須3）: append_anchor_column の検証・設定の厳格化・writer の防御。

- Target 生成時（__post_init__、ColumnPolicy の流儀）に anchor を
  検証する: ^[A-Z]+$ に一致しない値（"b"・"1"・" B"・""・整数 123
  など）は ValueError。"B"・"AA" は正常。load_config 経由でも同じく
  ValueError で、CLI では終了コード2になる。
- 設定の厳格化（同旨）: ターゲットエントリの未知キーは ValueError。
  background_rule に文字列など bool でない値が来たら ValueError。
- writer の防御: anchor 列に値のある行が1つも無い状態（ヘッダー
  すら無い）で append すると、何も書かずに ValueError で止まる
  （gateway への書き込み呼び出しが一切発生せず、状態も変わらない）。
"""

import json

import pytest
from fake_gateway import FakeGateway, make_state

import sheet_writer.cli as cli_module
from sheet_writer.config import ColumnPolicy, Target, load_config
from sheet_writer.writer import append_rows

COLUMNS = {
    "A": ColumnPolicy(mode="fit"),
    "B": ColumnPolicy(mode="wrap", width_px=300),
}


def target_with_anchor(anchor):
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="タブ",
        columns=dict(COLUMNS),
        append_anchor_column=anchor,
    )


def write_config(tmp_path, payload):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def target_payload(**overrides):
    payload = {
        "spreadsheet_id": "dummy-spreadsheet-id-0001",
        "tab": "タブ",
        "columns": {"A": {"mode": "fit"}},
    }
    payload.update(overrides)
    return payload


class TestTargetAnchorValidation:
    @pytest.mark.parametrize("anchor", ["B", "AA", "Z", "ABC"])
    def test_valid_column_letters_are_accepted(self, anchor):
        target = target_with_anchor(anchor)
        assert target.append_anchor_column == anchor

    @pytest.mark.parametrize(
        "anchor", ["b", "aa", "1", " B", "B ", "", "B1", "1B", 123]
    )
    def test_invalid_anchor_raises_value_error(self, anchor):
        with pytest.raises(ValueError):
            target_with_anchor(anchor)


class TestLoadConfigAnchorValidation:
    @pytest.mark.parametrize("anchor", ["b", "1", " B", "", 123])
    def test_invalid_anchor_raises_value_error(self, tmp_path, anchor):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(append_anchor_column=anchor)}}
        )
        with pytest.raises(ValueError):
            load_config(path)

    def test_double_letter_anchor_is_loaded(self, tmp_path):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(append_anchor_column="AA")}}
        )
        config = load_config(path)
        assert config.targets["t"].append_anchor_column == "AA"

    def test_invalid_anchor_exits_2_without_traceback(self, tmp_path, capsys):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(append_anchor_column="b")}}
        )
        rc = cli_module.main(["check", "--config", str(path), "--target", "t"])
        assert rc == 2
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert combined.strip() != ""
        assert "Traceback" not in combined


class TestLoadConfigStrictness:
    def test_unknown_target_key_raises_value_error(self, tmp_path):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(unknown_extra_key=True)}}
        )
        with pytest.raises(ValueError):
            load_config(path)

    @pytest.mark.parametrize("bad_value", ["true", "yes", 1, 0])
    def test_non_bool_background_rule_raises_value_error(self, tmp_path, bad_value):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(background_rule=bad_value)}}
        )
        with pytest.raises(ValueError):
            load_config(path)


class TestWriterAnchorDefense:
    def _gateway(self, values):
        state = make_state(
            values,
            column_widths=[100, 300],
            row_heights=[38] + [26] * (len(values) - 1),
        )
        return FakeGateway(state)

    def _assert_nothing_written(self, gateway, before):
        assert gateway.append_calls == []
        assert gateway.update_calls == []
        assert gateway.batch_requests == []
        assert gateway.state == before

    def test_completely_empty_sheet_raises_without_writing(self, m):
        gateway = self._gateway([["", ""], ["", ""], ["", ""]])
        before = gateway.state
        with pytest.raises(ValueError):
            append_rows(gateway, target_with_anchor("B"), [["x", "y"]], m)
        self._assert_nothing_written(gateway, before)

    def test_anchor_column_all_empty_raises_without_writing(self, m):
        # A 列にはヘッダー・データがあるが、anchor 列 B はヘッダー
        # すら無く全行空。この場合も anchor の末尾が定まらないため、
        # 何も書かずに ValueError で止まる
        gateway = self._gateway([["見出し", ""], ["データ1", ""], ["データ2", ""]])
        before = gateway.state
        with pytest.raises(ValueError):
            append_rows(gateway, target_with_anchor("B"), [["x", "y"]], m)
        self._assert_nothing_written(gateway, before)
