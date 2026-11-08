"""仕様（設定契約）: Target.checkbox_columns と load_config の解釈。

- Target に checkbox_columns フィールドが入る（任意・既定は空＝無効）。
  背景色チェック（background_rule）と同じ opt-in 方式。
- 要素は大文字の列名（``^[A-Z]+$``）で、形式が不正なら Target の
  生成時点で ValueError。
- ターゲット設定（JSON）のエントリに "checkbox_columns": ["A"] を
  追加でき、load_config が読み取る。list でない・要素が文字列でない
  場合は ValueError（設定不備は黙って通さない）。
"""

import json

import pytest

from sheet_writer.config import ColumnPolicy, Target, load_config


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


def make_target(**overrides):
    kwargs = {
        "spreadsheet_id": "dummy-spreadsheet-id-0001",
        "tab": "タブ",
        "columns": {"A": ColumnPolicy(mode="fit")},
    }
    kwargs.update(overrides)
    return Target(**kwargs)


class TestTargetCheckboxColumnsField:
    def test_default_is_empty(self):
        assert make_target().checkbox_columns == ()

    def test_explicit_columns(self):
        target = make_target(checkbox_columns=("A",))
        assert target.checkbox_columns == ("A",)

    def test_multiple_columns(self):
        target = make_target(checkbox_columns=("A", "C"))
        assert target.checkbox_columns == ("A", "C")

    def test_list_is_normalized_to_tuple(self):
        target = make_target(checkbox_columns=["A"])
        assert target.checkbox_columns == ("A",)

    @pytest.mark.parametrize("bad", ["a", "A1", "1", "", "Ａ"])
    def test_invalid_column_name_rejected(self, bad):
        with pytest.raises(ValueError):
            make_target(checkbox_columns=(bad,))

    def test_non_string_element_rejected(self):
        with pytest.raises(ValueError):
            make_target(checkbox_columns=(1,))

    def test_bare_string_is_not_a_column_list(self):
        # "A" のような文字列そのものは列の集合として解釈しない
        with pytest.raises(ValueError):
            make_target(checkbox_columns="A")


class TestLoadConfigCheckboxColumns:
    def test_columns_are_loaded(self, tmp_path):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(checkbox_columns=["A"])}}
        )
        config = load_config(path)
        assert config.targets["t"].checkbox_columns == ("A",)

    def test_omitted_defaults_to_empty(self, tmp_path):
        path = write_config(tmp_path, {"targets": {"t": target_payload()}})
        config = load_config(path)
        assert config.targets["t"].checkbox_columns == ()

    def test_empty_list_is_loaded_as_empty(self, tmp_path):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(checkbox_columns=[])}}
        )
        config = load_config(path)
        assert config.targets["t"].checkbox_columns == ()

    def test_per_target_independence(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "targets": {
                    "on": target_payload(checkbox_columns=["A"]),
                    "off": target_payload(),
                }
            },
        )
        config = load_config(path)
        assert config.targets["on"].checkbox_columns == ("A",)
        assert config.targets["off"].checkbox_columns == ()

    def test_non_list_rejected(self, tmp_path):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(checkbox_columns="A")}}
        )
        with pytest.raises(ValueError):
            load_config(path)

    def test_non_string_element_rejected(self, tmp_path):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(checkbox_columns=[1])}}
        )
        with pytest.raises(ValueError):
            load_config(path)

    def test_invalid_column_name_rejected(self, tmp_path):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(checkbox_columns=["a"])}}
        )
        with pytest.raises(ValueError):
            load_config(path)
