"""仕様1（設定契約）: Target.background_rule と load_config の解釈。

- Target に background_rule: bool = False フィールドが入る（任意・既定 false）。
- ターゲット設定（JSON）のエントリに "background_rule": true を追加でき、
  load_config がこのキーを読み取る。
"""

import json

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


class TestTargetBackgroundRuleField:
    def test_default_is_false(self):
        target = Target(
            spreadsheet_id="dummy-spreadsheet-id-0001",
            tab="タブ",
            columns={"A": ColumnPolicy(mode="fit")},
        )
        assert target.background_rule is False

    def test_explicit_true(self):
        target = Target(
            spreadsheet_id="dummy-spreadsheet-id-0001",
            tab="タブ",
            columns={"A": ColumnPolicy(mode="fit")},
            background_rule=True,
        )
        assert target.background_rule is True

    def test_explicit_false(self):
        target = Target(
            spreadsheet_id="dummy-spreadsheet-id-0001",
            tab="タブ",
            columns={"A": ColumnPolicy(mode="fit")},
            background_rule=False,
        )
        assert target.background_rule is False


class TestLoadConfigBackgroundRule:
    def test_true_is_loaded(self, tmp_path):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(background_rule=True)}}
        )
        config = load_config(path)
        assert config.targets["t"].background_rule is True

    def test_false_is_loaded(self, tmp_path):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(background_rule=False)}}
        )
        config = load_config(path)
        assert config.targets["t"].background_rule is False

    def test_omitted_defaults_to_false(self, tmp_path):
        path = write_config(tmp_path, {"targets": {"t": target_payload()}})
        config = load_config(path)
        assert config.targets["t"].background_rule is False

    def test_per_target_independence(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "targets": {
                    "on": target_payload(background_rule=True),
                    "off": target_payload(),
                }
            },
        )
        config = load_config(path)
        assert config.targets["on"].background_rule is True
        assert config.targets["off"].background_rule is False
