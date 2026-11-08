"""config のデフォルト値と load_config の解釈を固定する。

JSON 形式は config.example.json と同形:
{"measures": {...}, "targets": {"<名前>": {"spreadsheet_id": ..., "tab": ...,
"columns": {"A": {"mode": "fit"}, "B": {"mode": "wrap", "width_px": 300}}}}}
"""

import json

import pytest

from sheet_writer.config import ColumnPolicy, Measures, Target, load_config


def write_config(tmp_path, payload):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


class TestMeasuresDefaults:
    def test_defaults_match_spec(self):
        m = Measures()
        assert m.fullwidth_px == 11.5
        assert m.halfwidth_px == 6.3
        assert m.bold_fullwidth_px == 12.0
        assert m.bold_halfwidth_px == 6.6
        assert m.padding_px == 20
        assert m.row_base_px == 10
        assert m.line_height_px == 16
        assert m.min_row_height_px == 26
        assert m.header_height_px == 38
        assert m.default_wrap_width_px == 300


class TestColumnPolicyAndTarget:
    def test_fit_policy_has_no_width(self):
        policy = ColumnPolicy(mode="fit")
        assert policy.mode == "fit"
        assert policy.width_px is None

    def test_wrap_policy_keeps_width(self):
        policy = ColumnPolicy(mode="wrap", width_px=300)
        assert policy.mode == "wrap"
        assert policy.width_px == 300

    def test_target_fields(self):
        target = Target(
            spreadsheet_id="dummy-spreadsheet-id-0001",
            tab="タブ",
            columns={"A": ColumnPolicy(mode="fit")},
        )
        assert target.spreadsheet_id == "dummy-spreadsheet-id-0001"
        assert target.tab == "タブ"
        assert target.columns["A"].mode == "fit"


class TestLoadConfig:
    def test_full_config_like_example(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "measures": {
                    "fullwidth_px": 10.0,
                    "halfwidth_px": 5.0,
                    "bold_fullwidth_px": 10.5,
                    "bold_halfwidth_px": 5.5,
                    "padding_px": 16,
                    "row_base_px": 8,
                    "line_height_px": 14,
                    "min_row_height_px": 24,
                    "header_height_px": 36,
                    "default_wrap_width_px": 280,
                },
                "targets": {
                    "example-target": {
                        "spreadsheet_id": "dummy-spreadsheet-id-0001",
                        "tab": "タブ1",
                        "columns": {
                            "A": {"mode": "fit"},
                            "B": {"mode": "wrap", "width_px": 300},
                        },
                    }
                },
            },
        )
        config = load_config(path)
        assert config.measures.fullwidth_px == 10.0
        assert config.measures.default_wrap_width_px == 280
        target = config.targets["example-target"]
        assert target.spreadsheet_id == "dummy-spreadsheet-id-0001"
        assert target.tab == "タブ1"
        assert target.columns["A"] == ColumnPolicy(mode="fit")
        assert target.columns["B"] == ColumnPolicy(mode="wrap", width_px=300)

    def test_measures_omitted_uses_defaults(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "targets": {
                    "t": {
                        "spreadsheet_id": "dummy-spreadsheet-id-0001",
                        "tab": "タブ",
                        "columns": {},
                    }
                }
            },
        )
        config = load_config(path)
        assert config.measures == Measures()

    def test_measures_partial_override_keeps_other_defaults(self, tmp_path):
        path = write_config(tmp_path, {"measures": {"fullwidth_px": 10.0},
                                       "targets": {}})
        config = load_config(path)
        assert config.measures.fullwidth_px == 10.0
        assert config.measures.halfwidth_px == 6.3
        assert config.measures.padding_px == 20

    def test_wrap_without_width_px_has_none(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "targets": {
                    "t": {
                        "spreadsheet_id": "dummy-spreadsheet-id-0001",
                        "tab": "タブ",
                        "columns": {"B": {"mode": "wrap"}},
                    }
                }
            },
        )
        config = load_config(path)
        assert config.targets["t"].columns["B"].width_px is None

    def test_target_without_columns_is_empty(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "targets": {
                    "t": {
                        "spreadsheet_id": "dummy-spreadsheet-id-0001",
                        "tab": "タブ",
                    }
                }
            },
        )
        config = load_config(path)
        assert config.targets["t"].columns == {}

    def test_invalid_mode_raises_value_error(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "targets": {
                    "t": {
                        "spreadsheet_id": "dummy-spreadsheet-id-0001",
                        "tab": "タブ",
                        "columns": {"A": {"mode": "stretch"}},
                    }
                }
            },
        )
        with pytest.raises(ValueError):
            load_config(path)

    def test_missing_file_raises_os_error(self, tmp_path):
        with pytest.raises(OSError):
            load_config(tmp_path / "does-not-exist.json")

    def test_invalid_json_raises_value_error(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            load_config(path)

    def test_multiple_targets(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "targets": {
                    "one": {
                        "spreadsheet_id": "dummy-spreadsheet-id-0001",
                        "tab": "タブ1",
                        "columns": {},
                    },
                    "two": {
                        "spreadsheet_id": "dummy-spreadsheet-id-0002",
                        "tab": "タブ2",
                        "columns": {},
                    },
                }
            },
        )
        config = load_config(path)
        assert set(config.targets) == {"one", "two"}
        assert config.targets["two"].tab == "タブ2"
