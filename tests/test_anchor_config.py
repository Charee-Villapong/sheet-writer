"""仕様（設定契約）: Target.append_anchor_column と load_config の解釈。

- ターゲット設定に "append_anchor_column": "B" を追加できる（任意）。
- Target に append_anchor_column: str | None = None フィールドが入る
  （未指定・未設定なら None で、従来動作になる）。
- load_config がこのキーを読み取る。
- この列が「データの末尾」を決める列（末尾判定列）になる。writer /
  checker での使い方は test_anchor_writer.py / test_anchor_checker.py。
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


class TestTargetAppendAnchorColumnField:
    def test_default_is_none(self):
        target = Target(
            spreadsheet_id="dummy-spreadsheet-id-0001",
            tab="タブ",
            columns={"A": ColumnPolicy(mode="fit")},
        )
        assert target.append_anchor_column is None

    def test_explicit_column_letter(self):
        target = Target(
            spreadsheet_id="dummy-spreadsheet-id-0001",
            tab="タブ",
            columns={"A": ColumnPolicy(mode="fit")},
            append_anchor_column="B",
        )
        assert target.append_anchor_column == "B"

    def test_explicit_none(self):
        target = Target(
            spreadsheet_id="dummy-spreadsheet-id-0001",
            tab="タブ",
            columns={"A": ColumnPolicy(mode="fit")},
            append_anchor_column=None,
        )
        assert target.append_anchor_column is None


class TestLoadConfigAppendAnchorColumn:
    def test_column_letter_is_loaded(self, tmp_path):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(append_anchor_column="B")}}
        )
        config = load_config(path)
        assert config.targets["t"].append_anchor_column == "B"

    def test_other_column_letter_is_loaded(self, tmp_path):
        path = write_config(
            tmp_path, {"targets": {"t": target_payload(append_anchor_column="C")}}
        )
        config = load_config(path)
        assert config.targets["t"].append_anchor_column == "C"

    def test_omitted_defaults_to_none(self, tmp_path):
        path = write_config(tmp_path, {"targets": {"t": target_payload()}})
        config = load_config(path)
        assert config.targets["t"].append_anchor_column is None

    def test_per_target_independence(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "targets": {
                    "anchored": target_payload(append_anchor_column="B"),
                    "plain": target_payload(),
                }
            },
        )
        config = load_config(path)
        assert config.targets["anchored"].append_anchor_column == "B"
        assert config.targets["plain"].append_anchor_column is None
