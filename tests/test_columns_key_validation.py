"""仕様（設定契約）: Target.columns のキーは大文字の列名のみ許可する。

- append_anchor_column / checkbox_columns と同じく ``^[A-Z]+$`` で
  検証する。小文字（例: "a"）は column_index で 32（AG列）に化けて
  意図しない列を処理してしまうため、設定の時点で ValueError にする。
- load_config 経由でも同じ検証が効く（ValueError を漏らさない）。
"""

import json

import pytest

from sheet_writer.config import ColumnPolicy, Target, load_config


def write_config(tmp_path, payload):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def target_payload(columns):
    return {
        "spreadsheet_id": "dummy-spreadsheet-id-0001",
        "tab": "タブ",
        "columns": columns,
    }


class TestTargetColumnsKeyValidation:
    def test_uppercase_keys_accepted(self):
        target = Target(
            spreadsheet_id="dummy",
            tab="タブ",
            columns={
                "A": ColumnPolicy(mode="fit"),
                "BC": ColumnPolicy(mode="wrap", width_px=120),
            },
        )
        assert set(target.columns) == {"A", "BC"}

    def test_lowercase_key_rejected(self):
        with pytest.raises(ValueError):
            Target(
                spreadsheet_id="dummy",
                tab="タブ",
                columns={"a": ColumnPolicy(mode="fit")},
            )

    def test_mixed_case_key_rejected(self):
        with pytest.raises(ValueError):
            Target(
                spreadsheet_id="dummy",
                tab="タブ",
                columns={"Ab": ColumnPolicy(mode="fit")},
            )

    def test_key_with_digits_rejected(self):
        with pytest.raises(ValueError):
            Target(
                spreadsheet_id="dummy",
                tab="タブ",
                columns={"A1": ColumnPolicy(mode="fit")},
            )


class TestLoadConfigColumnsKeyValidation:
    def test_lowercase_key_rejected(self, tmp_path):
        path = write_config(
            tmp_path,
            {"targets": {"t": target_payload({"a": {"mode": "fit"}})}},
        )
        with pytest.raises(ValueError):
            load_config(path)

    def test_uppercase_keys_accepted(self, tmp_path):
        path = write_config(
            tmp_path,
            {"targets": {"t": target_payload({"AB": {"mode": "fit"}})}},
        )
        config = load_config(path)
        assert set(config.targets["t"].columns) == {"AB"}
