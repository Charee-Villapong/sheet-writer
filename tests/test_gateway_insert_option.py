"""R8: CliGateway.append_values は insertDataOption=INSERT_ROWS を渡す。

仕様:
- CLI 呼び出しの params に "insertDataOption": "INSERT_ROWS" を含める
  （行を挿入して追記し、既存行を上書きしない形を明示する）。
- runner モックで params を検証する。
"""

import json
from types import SimpleNamespace

from sheet_writer.gateway import CliGateway

DUMMY_ID = "dummy-spreadsheet-id-0001"


class FakeRunner:
    """subprocess.run 相当のフェイク（test_gateway_cli.py と同じ流儀）。"""

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


class TestInsertDataOption:
    def test_append_params_include_insert_rows(self):
        runner = FakeRunner(
            {
                "spreadsheetId": DUMMY_ID,
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
        result = gateway.append_values(DUMMY_ID, "タブ!A:B", [["a", "b"]])

        assert result == "タブ!A3:B3"
        (cmd,) = runner.calls
        params = json.loads(flag_value(cmd, "--params"))
        assert params["insertDataOption"] == "INSERT_ROWS"
        # 既存の params も壊れていない
        assert params["spreadsheetId"] == DUMMY_ID
        assert params["range"] == "タブ!A:B"
