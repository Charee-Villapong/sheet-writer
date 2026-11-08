"""CliGateway のテスト。

runner（subprocess.run 相当）をモックに差し替え、以下を固定する:
- 実行コマンドは /opt/hatch/bin/hatch_gws_cli sheets ... の引数リスト形式
- クエリは --params '<JSON>'、ボディは --json '<JSON>' で渡す
  （Google Sheets コネクタの正規形）
- stdout の JSON をパースして返す
"""

import json
import subprocess
from types import SimpleNamespace

import pytest

from sheet_writer.gateway import CliGateway, SheetState

CLI_PATH = "/opt/hatch/bin/hatch_gws_cli"
DUMMY_ID = "dummy-spreadsheet-id-0001"


class FakeRunner:
    """subprocess.run 相当のフェイク。応答 JSON を順に返し、呼び出しを記録する。"""

    def __init__(self, *stdout_payloads):
        self.calls = []
        self._payloads = list(stdout_payloads)

    def __call__(self, cmd, *args, **kwargs):
        self.calls.append(list(cmd))
        payload = self._payloads.pop(0) if self._payloads else {}
        if not isinstance(payload, str):
            payload = json.dumps(payload, ensure_ascii=False)
        return SimpleNamespace(stdout=payload, stderr="", returncode=0)


def flag_value(cmd, flag):
    """cmd の中から `--flag <value>` の value を取り出す。"""
    assert flag in cmd, f"{flag} がコマンドに含まれていない: {cmd}"
    return cmd[cmd.index(flag) + 1]


class TestConstruction:
    def test_default_construction(self):
        gateway = CliGateway()
        assert callable(gateway.get_values)
        assert callable(gateway.append_values)
        assert callable(gateway.get_state)
        assert callable(gateway.batch_update)

    def test_runner_is_injectable(self):
        gateway = CliGateway(runner=FakeRunner({"values": []}))
        assert gateway.get_values(DUMMY_ID, "タブ!A1") == []


class TestGetValues:
    def test_command_and_json_parsing(self):
        runner = FakeRunner(
            {
                "range": "タブ!A1:B2",
                "majorDimension": "ROWS",
                "values": [["名前", "メモ"], ["abc", "x"]],
            }
        )
        gateway = CliGateway(runner=runner)
        result = gateway.get_values(DUMMY_ID, "タブ!A1:B2")

        assert result == [["名前", "メモ"], ["abc", "x"]]
        (cmd,) = runner.calls
        assert cmd[0] == CLI_PATH
        assert cmd[1] == "sheets"
        assert cmd[2:5] == ["spreadsheets", "values", "get"]
        params = json.loads(flag_value(cmd, "--params"))
        assert params["spreadsheetId"] == DUMMY_ID
        assert params["range"] == "タブ!A1:B2"

    def test_missing_values_key_means_empty(self):
        # 空範囲では API 応答に values キー自体が無い
        runner = FakeRunner({"range": "タブ!A1:B2", "majorDimension": "ROWS"})
        gateway = CliGateway(runner=runner)
        assert gateway.get_values(DUMMY_ID, "タブ!A1:B2") == []

    def test_runner_error_propagates(self):
        def failing_runner(cmd, *args, **kwargs):
            raise subprocess.CalledProcessError(1, cmd, stderr="boom")

        gateway = CliGateway(runner=failing_runner)
        with pytest.raises(subprocess.CalledProcessError):
            gateway.get_values(DUMMY_ID, "タブ!A1")


class TestAppendValues:
    def test_command_and_updated_range(self):
        runner = FakeRunner(
            {
                "spreadsheetId": DUMMY_ID,
                "tableRange": "タブ!A1:B2",
                "updates": {
                    "spreadsheetId": DUMMY_ID,
                    "updatedRange": "タブ!A3:B3",
                    "updatedRows": 1,
                    "updatedColumns": 2,
                    "updatedCells": 2,
                },
            }
        )
        gateway = CliGateway(runner=runner)
        rows = [["あいうえお", "メモ"]]
        result = gateway.append_values(DUMMY_ID, "タブ!A:B", rows)

        assert result == "タブ!A3:B3"
        (cmd,) = runner.calls
        assert cmd[0] == CLI_PATH
        assert cmd[1] == "sheets"
        assert cmd[2:5] == ["spreadsheets", "values", "append"]
        params = json.loads(flag_value(cmd, "--params"))
        assert params["spreadsheetId"] == DUMMY_ID
        assert params["range"] == "タブ!A:B"
        body = json.loads(flag_value(cmd, "--json"))
        assert body["values"] == rows


class TestBatchUpdate:
    def test_command_and_body(self):
        requests = [
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": 7,
                        "dimension": "COLUMNS",
                        "startIndex": 0,
                        "endIndex": 1,
                    },
                    "properties": {"pixelSize": 78},
                    "fields": "pixelSize",
                }
            }
        ]
        runner = FakeRunner({"replies": [{}]})
        gateway = CliGateway(runner=runner)

        assert gateway.batch_update(DUMMY_ID, requests) is None

        (cmd,) = runner.calls
        assert cmd[0] == CLI_PATH
        assert cmd[1] == "sheets"
        assert "batchUpdate" in cmd
        params = json.loads(flag_value(cmd, "--params"))
        assert params["spreadsheetId"] == DUMMY_ID
        body = json.loads(flag_value(cmd, "--json"))
        assert body["requests"] == requests


class TestGetState:
    def test_state_is_built_from_grid_data(self):
        white = {"red": 1.0, "green": 1.0, "blue": 1.0}
        runner = FakeRunner(
            {
                "spreadsheetId": DUMMY_ID,
                "sheets": [
                    {
                        "properties": {"sheetId": 7, "title": "タブ"},
                        "data": [
                            {
                                "rowData": [
                                    {
                                        "values": [
                                            {
                                                "formattedValue": "名前",
                                                "userEnteredFormat": {
                                                    "textFormat": {"bold": True}
                                                },
                                            },
                                            {
                                                "formattedValue": "メモ",
                                                "userEnteredFormat": {},
                                            },
                                        ]
                                    },
                                    {
                                        "values": [
                                            {
                                                "formattedValue": "abc",
                                                "userEnteredFormat": {
                                                    "backgroundColor": white
                                                },
                                            },
                                            {
                                                "formattedValue": "x",
                                                "userEnteredFormat": {},
                                            },
                                        ]
                                    },
                                ],
                                "rowMetadata": [
                                    {"pixelSize": 38},
                                    {"pixelSize": 26},
                                ],
                                "columnMetadata": [
                                    {"pixelSize": 100},
                                    {"pixelSize": 300},
                                ],
                            }
                        ],
                    }
                ],
            }
        )
        gateway = CliGateway(runner=runner)
        state = gateway.get_state(DUMMY_ID, "タブ")

        assert isinstance(state, SheetState)
        assert state.sheet_id == 7
        assert state.values == [["名前", "メモ"], ["abc", "x"]]
        assert state.column_widths == [100, 300]
        assert state.row_heights == [38, 26]
        assert state.cell_formats[0][0] == {"textFormat": {"bold": True}}
        assert state.cell_formats[1][0] == {"backgroundColor": white}

        (cmd,) = runner.calls
        assert cmd[0] == CLI_PATH
        assert cmd[1] == "sheets"
        assert cmd[2:4] == ["spreadsheets", "get"]
        params = json.loads(flag_value(cmd, "--params"))
        assert params["spreadsheetId"] == DUMMY_ID

    def test_sheet_state_dataclass_fields(self):
        state = SheetState(
            sheet_id=3,
            values=[["a"]],
            column_widths=[120],
            row_heights=[26],
            cell_formats=[[{"wrapStrategy": "WRAP"}]],
        )
        assert state.sheet_id == 3
        assert state.values == [["a"]]
        assert state.column_widths == [120]
        assert state.row_heights == [26]
        assert state.cell_formats[0][0]["wrapStrategy"] == "WRAP"
