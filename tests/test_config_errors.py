"""R7: 設定ファイルの不備は ValueError / 終了コード2で報告する。

仕様:
- load_config は設定の不備（ターゲットに spreadsheet_id が無い、
  measures に未知のキー、columns の値が dict でない等）で ValueError を
  送出する（KeyError / TypeError を漏らさない）。
- CLI は終了コード 2 でエラーメッセージを出し、トレースバックを
  出さない。
"""

import json

import pytest

import sheet_writer.cli as cli_module
from sheet_writer.config import load_config


def write_config(tmp_path, payload):
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def valid_target(**overrides):
    payload = {
        "spreadsheet_id": "dummy-spreadsheet-id-0001",
        "tab": "タブ",
        "columns": {"A": {"mode": "fit"}},
    }
    payload.update(overrides)
    return payload


class TestLoadConfigRaisesValueError:
    def test_missing_spreadsheet_id(self, tmp_path):
        target = valid_target()
        del target["spreadsheet_id"]
        path = write_config(tmp_path, {"targets": {"t": target}})
        with pytest.raises(ValueError):
            load_config(path)

    def test_missing_tab(self, tmp_path):
        target = valid_target()
        del target["tab"]
        path = write_config(tmp_path, {"targets": {"t": target}})
        with pytest.raises(ValueError):
            load_config(path)

    def test_unknown_measures_key(self, tmp_path):
        path = write_config(
            tmp_path,
            {
                "measures": {"unknown_measure_key": 1},
                "targets": {"t": valid_target()},
            },
        )
        with pytest.raises(ValueError):
            load_config(path)

    def test_columns_value_not_a_dict(self, tmp_path):
        path = write_config(
            tmp_path,
            {"targets": {"t": valid_target(columns={"A": "fit"})}},
        )
        with pytest.raises(ValueError):
            load_config(path)

    def test_columns_not_a_dict(self, tmp_path):
        path = write_config(
            tmp_path,
            {"targets": {"t": valid_target(columns=["A", "B"])}},
        )
        with pytest.raises(ValueError):
            load_config(path)

    def test_measures_not_a_dict(self, tmp_path):
        path = write_config(
            tmp_path, {"measures": 42, "targets": {"t": valid_target()}}
        )
        with pytest.raises(ValueError):
            load_config(path)

    def test_target_not_a_dict(self, tmp_path):
        path = write_config(tmp_path, {"targets": {"t": "not-a-dict"}})
        with pytest.raises(ValueError):
            load_config(path)


class TestCliConfigErrorExitCode:
    @pytest.mark.parametrize(
        "payload",
        [
            # spreadsheet_id が無い
            {"targets": {"t": {"tab": "タブ", "columns": {}}}},
            # measures に未知のキー
            {
                "measures": {"unknown_measure_key": 1},
                "targets": {"t": valid_target()},
            },
            # columns の値が dict でない
            {"targets": {"t": valid_target(columns={"A": "fit"})}},
        ],
    )
    def test_config_error_exits_2_without_traceback(self, tmp_path, capsys, payload):
        path = write_config(tmp_path, payload)
        rc = cli_module.main(["check", "--config", str(path), "--target", "t"])
        assert rc == 2
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        # エラーメッセージは出すが、トレースバックは出さない
        assert combined.strip() != ""
        assert "Traceback" not in combined
