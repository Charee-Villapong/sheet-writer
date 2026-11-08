"""cli.main の終了コードと、サブコマンドの配線を固定する。

CLI が内部で作る CliGateway は、モジュール属性を差し替えて
FakeGateway に置き換える（実接続は行わない）。
"""

import json

import pytest
from fake_gateway import FakeGateway, make_state

import sheet_writer.cli as cli_module
import sheet_writer.gateway as gateway_module
from sheet_writer.config import ColumnPolicy

TARGET_NAME = "ledger"


def write_cli_config(tmp_path):
    payload = {
        "targets": {
            TARGET_NAME: {
                "spreadsheet_id": "dummy-spreadsheet-id-0001",
                "tab": "テストタブ",
                "columns": {
                    "A": {"mode": "fit"},
                    "B": {"mode": "wrap", "width_px": 300},
                },
            }
        }
    }
    path = tmp_path / "config.local.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def clean_gateway():
    state = make_state(
        [["名前", "メモ"], ["abc", "x"]],
        column_widths=[100, 300],
        row_heights=[38, 26],
    )
    return FakeGateway(state)


def dirty_gateway(**kwargs):
    # 列 A が不足（必要幅 135 > 現在幅 50）
    state = make_state(
        [["名前", "メモ"], ["あ" * 10, "x"]],
        column_widths=[50, 300],
        row_heights=[38, 26],
    )
    return FakeGateway(state, **kwargs)


@pytest.fixture
def install_gateway(monkeypatch):
    """CLI が生成するゲートウェイを、指定した FakeGateway に差し替える。"""

    def _install(gateway):
        monkeypatch.setattr(
            cli_module, "CliGateway", lambda *a, **k: gateway, raising=False
        )
        monkeypatch.setattr(
            gateway_module, "CliGateway", lambda *a, **k: gateway, raising=False
        )
        return gateway

    return _install


def argv(command, config_path, *extra):
    return [command, "--config", str(config_path), "--target", TARGET_NAME, *extra]


class TestCheckCommand:
    def test_clean_sheet_returns_zero(self, tmp_path, install_gateway):
        install_gateway(clean_gateway())
        config = write_cli_config(tmp_path)
        assert cli_module.main(argv("check", config)) == 0

    def test_violations_return_nonzero(self, tmp_path, install_gateway):
        install_gateway(dirty_gateway())
        config = write_cli_config(tmp_path)
        assert cli_module.main(argv("check", config)) != 0

    def test_fix_returns_zero_and_applies_format_changes(
        self, tmp_path, install_gateway
    ):
        gateway = install_gateway(dirty_gateway())
        config = write_cli_config(tmp_path)
        assert cli_module.main(argv("check", config, "--fix")) == 0
        assert gateway.state.column_widths[0] == 135


class TestAppendCommand:
    def test_append_returns_zero_and_adds_row(self, tmp_path, install_gateway):
        gateway = install_gateway(clean_gateway())
        config = write_cli_config(tmp_path)
        rc = cli_module.main(
            argv("append", config, "--row", '["新しい名前", "短いメモ"]')
        )
        assert rc == 0
        assert gateway.state.values[2] == ["新しい名前", "短いメモ"]

    def test_append_multiple_rows(self, tmp_path, install_gateway):
        gateway = install_gateway(clean_gateway())
        config = write_cli_config(tmp_path)
        rc = cli_module.main(
            argv(
                "append",
                config,
                "--row",
                '["1行目", "a"]',
                "--row",
                '["2行目", "b"]',
            )
        )
        assert rc == 0
        assert gateway.state.values[2] == ["1行目", "a"]
        assert gateway.state.values[3] == ["2行目", "b"]

    def test_append_verification_failure_returns_nonzero(
        self, tmp_path, install_gateway
    ):
        # 列幅の変更を無視する Fake: 検証で失敗し、黙って成功しない
        gateway = install_gateway(dirty_gateway(ignore_column_widths=True))
        config = write_cli_config(tmp_path)
        rc = cli_module.main(
            argv("append", config, "--row", '["あいうえおかきくけこ", "x"]')
        )
        assert rc != 0
        assert gateway is not None

    def test_append_invalid_row_json_fails(self, tmp_path, install_gateway):
        install_gateway(clean_gateway())
        config = write_cli_config(tmp_path)
        try:
            rc = cli_module.main(argv("append", config, "--row", "not-json"))
        except (ValueError, SystemExit):
            return
        assert rc != 0


def test_target_columns_from_config_are_used(tmp_path, install_gateway, m):
    # config の B 列 wrap 指定が効くこと: 追加セルの書式に WRAP が付く
    gateway = install_gateway(clean_gateway())
    config = write_cli_config(tmp_path)
    rc = cli_module.main(argv("append", config, "--row", '["abc", "メモ"]'))
    assert rc == 0
    assert gateway.state.cell_formats[2][1].get("wrapStrategy") == "WRAP"
    # 参考: ColumnPolicy の生成が config 形式と一致していることも確認する
    assert ColumnPolicy(mode="wrap", width_px=300).width_px == 300
