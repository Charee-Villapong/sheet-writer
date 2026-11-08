"""M2: タブ名不一致時の fail-open をやめる（先行テスト）。

仕様（QA 必須対応 M2）:
- CliGateway.get_state で、要求したタブ名に一致するシートが応答に
  無い場合は、黙って先頭シートへフォールバックせず例外（ValueError）
  を送出する。
- 応答にシートが1つも無い場合も同様に ValueError を送出する。
"""

import json
from types import SimpleNamespace

import pytest

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


def sheet_block(sheet_id, title, rows):
    """spreadsheets.get 応答の sheets 要素1件分を作る。"""
    return {
        "properties": {"sheetId": sheet_id, "title": title},
        "data": [
            {
                "rowData": [
                    {
                        "values": [
                            {"formattedValue": v, "userEnteredFormat": {}} for v in row
                        ]
                    }
                    for row in rows
                ],
                "rowMetadata": [{"pixelSize": 26} for _ in rows],
                "columnMetadata": [
                    {"pixelSize": 100} for _ in range(len(rows[0]) if rows else 0)
                ],
            }
        ],
    }


def gateway_with_sheets(sheets):
    runner = FakeRunner({"spreadsheetId": DUMMY_ID, "sheets": sheets})
    return CliGateway(runner=runner)


class TestMatchingTabIsSelected:
    def test_second_sheet_is_returned_when_it_matches(self):
        # 先頭ではないシートが要求タブと一致する場合、そのシートを返す
        # （先頭シートへのフォールバックではないこと）
        gateway = gateway_with_sheets(
            [
                sheet_block(11, "別のタブ", [["先頭シートの値"]]),
                sheet_block(22, "対象タブ", [["対象シートの値"]]),
            ]
        )
        state = gateway.get_state(DUMMY_ID, "対象タブ")
        assert state.sheet_id == 22
        assert state.values == [["対象シートの値"]]

    def test_first_sheet_is_returned_when_it_matches(self):
        gateway = gateway_with_sheets(
            [
                sheet_block(11, "対象タブ", [["対象シートの値"]]),
                sheet_block(22, "別のタブ", [["別の値"]]),
            ]
        )
        state = gateway.get_state(DUMMY_ID, "対象タブ")
        assert state.sheet_id == 11
        assert state.values == [["対象シートの値"]]


class TestMissingTabRaises:
    def test_single_other_sheet_raises_value_error(self):
        # 応答にシートが1件だけでも、タブ名が一致しなければ例外
        gateway = gateway_with_sheets(
            [sheet_block(11, "別のタブ", [["先頭シートの値"]])]
        )
        with pytest.raises(ValueError):
            gateway.get_state(DUMMY_ID, "対象タブ")

    def test_multiple_sheets_without_match_raise_value_error(self):
        gateway = gateway_with_sheets(
            [
                sheet_block(11, "タブA", [["a"]]),
                sheet_block(22, "タブB", [["b"]]),
                sheet_block(33, "タブC", [["c"]]),
            ]
        )
        with pytest.raises(ValueError):
            gateway.get_state(DUMMY_ID, "対象タブ")

    def test_similar_but_not_equal_title_raises_value_error(self):
        # 部分一致・表記揺れは一致とみなさない（完全一致のみ）
        gateway = gateway_with_sheets(
            [sheet_block(11, "対象タブ ", [["末尾スペース違い"]])]
        )
        with pytest.raises(ValueError):
            gateway.get_state(DUMMY_ID, "対象タブ")


class TestNoSheetsRaises:
    def test_empty_sheets_list_raises_value_error(self):
        gateway = gateway_with_sheets([])
        with pytest.raises(ValueError):
            gateway.get_state(DUMMY_ID, "対象タブ")

    def test_missing_sheets_key_raises_value_error(self):
        runner = FakeRunner({"spreadsheetId": DUMMY_ID})
        gateway = CliGateway(runner=runner)
        with pytest.raises(ValueError):
            gateway.get_state(DUMMY_ID, "対象タブ")
