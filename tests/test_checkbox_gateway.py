"""仕様（gateway）: CliGateway.get_state が dataValidation を取り出す。

- get_state の取得フィールドに dataValidation が含まれる。
- SheetState.data_validations はセル単位の dict のグリッドで、
  入力規則のないセルは {}、あるセルは API の dataValidation そのもの。
- data_validations を省略して SheetState を作ると空（既定）になる。
"""

import json
from types import SimpleNamespace

from sheet_writer.gateway import CliGateway, SheetState

DUMMY_ID = "dummy-spreadsheet-id-0001"

BOOLEAN_RULE = {"condition": {"type": "BOOLEAN"}, "strict": True}


class FakeRunner:
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
    assert flag in cmd, f"{flag} がコマンドに含まれていない: {cmd}"
    return cmd[cmd.index(flag) + 1]


def state_payload():
    return {
        "spreadsheetId": DUMMY_ID,
        "sheets": [
            {
                "properties": {"sheetId": 7, "title": "タブ"},
                "data": [
                    {
                        "rowData": [
                            {
                                "values": [
                                    {"formattedValue": "不要"},
                                    {"formattedValue": "タスク"},
                                ]
                            },
                            {
                                "values": [
                                    {
                                        "formattedValue": "FALSE",
                                        "userEnteredValue": {"boolValue": False},
                                        "dataValidation": BOOLEAN_RULE,
                                    },
                                    {"formattedValue": "掃除"},
                                ]
                            },
                            {
                                "values": [
                                    {
                                        "formattedValue": "FALSE",
                                        "userEnteredValue": {"stringValue": "FALSE"},
                                    },
                                    {"formattedValue": "洗濯"},
                                ]
                            },
                        ],
                        "rowMetadata": [{"pixelSize": 38}] + [{"pixelSize": 26}] * 2,
                        "columnMetadata": [{"pixelSize": 100}, {"pixelSize": 300}],
                    }
                ],
            }
        ],
    }


class TestGetStateDataValidation:
    def test_validations_are_parsed_per_cell(self):
        gateway = CliGateway(runner=FakeRunner(state_payload()))
        state = gateway.get_state(DUMMY_ID, "タブ")
        assert state.data_validations[1][0] == BOOLEAN_RULE
        # 入力規則のないセルは空 dict
        assert state.data_validations[0][0] == {}
        assert state.data_validations[0][1] == {}
        assert state.data_validations[1][1] == {}
        assert state.data_validations[2][0] == {}

    def test_fields_request_includes_data_validation(self):
        gateway = CliGateway(runner=FakeRunner(state_payload()))
        gateway.get_state(DUMMY_ID, "タブ")
        (cmd,) = gateway._runner.calls
        params = json.loads(flag_value(cmd, "--params"))
        assert "dataValidation" in params["fields"]

    def test_state_without_validation_key_is_all_empty(self):
        payload = state_payload()
        for row in payload["sheets"][0]["data"][0]["rowData"]:
            for cell in row["values"]:
                cell.pop("dataValidation", None)
        gateway = CliGateway(runner=FakeRunner(payload))
        state = gateway.get_state(DUMMY_ID, "タブ")
        assert all(cell == {} for row in state.data_validations for cell in row)


class TestSheetStateDefault:
    def test_data_validations_defaults_to_empty(self):
        state = SheetState(
            sheet_id=3,
            values=[["a"]],
            column_widths=[120],
            row_heights=[26],
            cell_formats=[[{}]],
        )
        assert state.data_validations == []
