"""R2: CliGateway.get_state の疎なグリッド変換。

仕様:
- 疎なペイロード（rowData の行に values が無い、セルに
  formattedValue / userEnteredFormat が無い、rowMetadata が
  rowData より短い）でも例外にならない。
- 欠けた値は空文字・空書式で埋めた SheetState を返す。
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


def payload(grid):
    """grid dict（rowData / rowMetadata / columnMetadata）を応答にする。"""
    return {
        "spreadsheetId": DUMMY_ID,
        "sheets": [
            {
                "properties": {"sheetId": 7, "title": "タブ"},
                "data": [grid],
            }
        ],
    }


def get_state(grid):
    gateway = CliGateway(runner=FakeRunner(payload(grid)))
    return gateway.get_state(DUMMY_ID, "タブ")


class TestSparseGrid:
    def test_row_without_values_key(self):
        state = get_state(
            {
                "rowData": [
                    {
                        "values": [
                            {"formattedValue": "名前", "userEnteredFormat": {}},
                            {"formattedValue": "メモ", "userEnteredFormat": {}},
                        ]
                    },
                    {},  # values 自体が無い行
                    {
                        "values": [
                            {"formattedValue": "abc", "userEnteredFormat": {}},
                            {"formattedValue": "x", "userEnteredFormat": {}},
                        ]
                    },
                ],
                "rowMetadata": [
                    {"pixelSize": 38},
                    {"pixelSize": 26},
                    {"pixelSize": 26},
                ],
                "columnMetadata": [{"pixelSize": 100}, {"pixelSize": 300}],
            }
        )
        assert state.values[0] == ["名前", "メモ"]
        # values の無い行は空文字で埋まる（列数は他の行に揃う）
        assert state.values[1] == ["", ""]
        assert state.values[2] == ["abc", "x"]
        assert state.cell_formats[1] == [{}, {}]

    def test_cell_without_formatted_value_or_format(self):
        state = get_state(
            {
                "rowData": [
                    {
                        "values": [
                            {},  # formattedValue も userEnteredFormat も無い
                            {"formattedValue": "メモ"},
                            {"userEnteredFormat": {"wrapStrategy": "WRAP"}},
                        ]
                    }
                ],
                "rowMetadata": [{"pixelSize": 38}],
                "columnMetadata": [
                    {"pixelSize": 100},
                    {"pixelSize": 100},
                    {"pixelSize": 100},
                ],
            }
        )
        assert state.values == [["", "メモ", ""]]
        assert state.cell_formats[0][0] == {}
        assert state.cell_formats[0][1] == {}
        assert state.cell_formats[0][2] == {"wrapStrategy": "WRAP"}

    def test_row_metadata_shorter_than_row_data(self):
        state = get_state(
            {
                "rowData": [
                    {"values": [{"formattedValue": "名前", "userEnteredFormat": {}}]},
                    {"values": [{"formattedValue": "abc", "userEnteredFormat": {}}]},
                    {"values": [{"formattedValue": "def", "userEnteredFormat": {}}]},
                ],
                # rowData 3行に対して rowMetadata は1件だけ
                "rowMetadata": [{"pixelSize": 38}],
                "columnMetadata": [{"pixelSize": 100}],
            }
        )
        assert state.values == [["名前"], ["abc"], ["def"]]
        assert state.row_heights[0] == 38
        assert state.column_widths == [100]

    def test_short_values_row_is_padded_to_column_count(self):
        state = get_state(
            {
                "rowData": [
                    {
                        "values": [
                            {"formattedValue": "名前", "userEnteredFormat": {}},
                            {"formattedValue": "メモ", "userEnteredFormat": {}},
                            {"formattedValue": "数量", "userEnteredFormat": {}},
                        ]
                    },
                    {
                        "values": [
                            {"formattedValue": "abc", "userEnteredFormat": {}}
                        ]
                    },
                ],
                "rowMetadata": [{"pixelSize": 38}, {"pixelSize": 26}],
                "columnMetadata": [
                    {"pixelSize": 100},
                    {"pixelSize": 300},
                    {"pixelSize": 80},
                ],
            }
        )
        assert state.values[1] == ["abc", "", ""]
        assert state.cell_formats[1] == [{}, {}, {}]
        # entered_values がある実装では、そちらも同じ形に埋まっている
        entered = getattr(state, "entered_values", None)
        if entered is not None:
            assert entered[1] == [{}, {}, {}]

    def test_missing_metadata_keys_entirely(self):
        state = get_state(
            {
                "rowData": [
                    {"values": [{"formattedValue": "a", "userEnteredFormat": {}}]}
                ]
                # rowMetadata / columnMetadata 自体が無い
            }
        )
        assert state.values == [["a"]]
        assert state.cell_formats == [[{}]]
