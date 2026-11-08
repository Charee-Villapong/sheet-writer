"""仕様（設定契約）: Target.vertical_alignment と load_config の解釈。

- Target に vertical_alignment: str | None = None フィールドが入る
  （任意・既定 None＝ルール無効）。
- ターゲット設定（JSON）のエントリに "vertical_alignment": "TOP" を
  追加でき、Target に読み込まれる。
- 値は "TOP" / "MIDDLE" / "BOTTOM" のいずれかでなければならない。
  それ以外（小文字・空文字・真偽値・数値・null 以外の型）は ValueError。
- 未知のキーとして弾かれないこと（known keys に含まれる）。
"""

import json

import pytest

from sheet_writer.config import Target, load_config


def _write_config(tmp_path, targets):
    path = tmp_path / "config.local.json"
    path.write_text(json.dumps({"targets": targets}), encoding="utf-8")
    return path


def _target_entry(**overrides):
    entry = {"spreadsheet_id": "dummy-id", "tab": "タブ"}
    entry.update(overrides)
    return entry


class TestTargetField:
    def test_default_is_none(self):
        target = Target(spreadsheet_id="dummy-id", tab="タブ")
        assert target.vertical_alignment is None

    @pytest.mark.parametrize("value", ["TOP", "MIDDLE", "BOTTOM"])
    def test_accepts_api_enum_values(self, value):
        target = Target(spreadsheet_id="dummy-id", tab="タブ", vertical_alignment=value)
        assert target.vertical_alignment == value

    @pytest.mark.parametrize(
        "bad", ["top", "Top", "", "CENTER", True, 1, ["TOP"], {"v": "TOP"}]
    )
    def test_invalid_value_raises(self, bad):
        with pytest.raises(ValueError):
            Target(spreadsheet_id="dummy-id", tab="タブ", vertical_alignment=bad)


class TestLoadConfig:
    def test_reads_vertical_alignment(self, tmp_path):
        path = _write_config(tmp_path, {"t": _target_entry(vertical_alignment="TOP")})
        config = load_config(path)
        assert config.targets["t"].vertical_alignment == "TOP"

    def test_absent_means_none(self, tmp_path):
        path = _write_config(tmp_path, {"t": _target_entry()})
        config = load_config(path)
        assert config.targets["t"].vertical_alignment is None

    def test_null_means_none(self, tmp_path):
        path = _write_config(tmp_path, {"t": _target_entry(vertical_alignment=None)})
        config = load_config(path)
        assert config.targets["t"].vertical_alignment is None

    @pytest.mark.parametrize("bad", ["top", "", "CENTER", True, 0, ["TOP"]])
    def test_invalid_value_in_json_raises_value_error(self, tmp_path, bad):
        path = _write_config(tmp_path, {"t": _target_entry(vertical_alignment=bad)})
        with pytest.raises(ValueError):
            load_config(path)
