"""仕様: 範囲文字列のタブ名は A1 記法で常にクォートする。

- ``quote_tab`` がタブ名をシングルクォートで囲み、内部の ``'`` は
  ``''`` にエスケープする。
- 範囲を組み立てる箇所（writer の append / anchor update、
  CliGateway.get_state の ranges）はすべて ``quote_tab`` を通す。
  スペースや記号を含むタブ名でも範囲として解釈される。
- 記号を含まない日本語タブ名（候補リスト等）でも従来どおり
  追加・検証が通る（クォート付き A1 記法は実 API でも有効）。
"""

import json
from types import SimpleNamespace

from fake_gateway import FakeGateway, make_state

from sheet_writer.config import ColumnPolicy, Target
from sheet_writer.gateway import CliGateway, quote_tab
from sheet_writer.writer import append_rows

DUMMY_ID = "dummy-spreadsheet-id-0001"


class FakeRunner:
    """subprocess.run 相当のフェイク（test_m2_tab_match.py と同じ流儀）。"""

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


def params_of(call):
    return json.loads(call[call.index("--params") + 1])


class TestQuoteTab:
    def test_plain_japanese_name_is_quoted(self):
        assert quote_tab("候補リスト") == "'候補リスト'"

    def test_name_with_space_and_hyphen_is_quoted(self):
        assert quote_tab("候補 リスト-2026") == "'候補 リスト-2026'"

    def test_single_quote_is_doubled(self):
        assert quote_tab("it's") == "'it''s'"


class TestGetStateRangesAreQuoted:
    def test_ranges_param_uses_quoted_tab(self):
        runner = FakeRunner(
            {"spreadsheetId": DUMMY_ID, "sheets": [sheet_block(7, "対象タブ", [["v"]])]}
        )
        gateway = CliGateway(runner=runner)
        state = gateway.get_state(DUMMY_ID, "対象タブ")
        assert state.values == [["v"]]
        assert params_of(runner.calls[0])["ranges"] == "'対象タブ'"


def spaced_tab_target(**overrides):
    kwargs = {
        "spreadsheet_id": DUMMY_ID,
        "tab": "候補 リスト",
        "columns": {"A": ColumnPolicy(mode="fit"), "B": ColumnPolicy(mode="fit")},
    }
    kwargs.update(overrides)
    return Target(**kwargs)


class TestAppendWithSpacedTab:
    def test_append_range_is_quoted_and_verified(self, m):
        gateway = FakeGateway(
            make_state([["名前", "値"], ["a", "1"]], column_widths=[100, 100])
        )
        result = append_rows(gateway, spaced_tab_target(), [["b", "2"]], m)
        assert result.appended_rows == [3]
        assert gateway.append_calls[0][1] == "'候補 リスト'!A:B"
        assert gateway.state.values[2] == ["b", "2"]

    def test_anchor_update_range_is_quoted_and_verified(self, m):
        gateway = FakeGateway(
            make_state([["名前", "値"], ["a", "1"]], column_widths=[100, 100])
        )
        target = spaced_tab_target(append_anchor_column="A")
        result = append_rows(gateway, target, [["b", "2"]], m)
        assert result.appended_rows == [3]
        assert gateway.update_calls[0][1] == "'候補 リスト'!A3:B3"
        assert gateway.state.values[2] == ["b", "2"]


class TestPlainJapaneseTabStillWorks:
    def test_append_with_japanese_tab(self, m):
        gateway = FakeGateway(
            make_state([["名前", "値"], ["a", "1"]], column_widths=[100, 100])
        )
        target = Target(
            spreadsheet_id=DUMMY_ID,
            tab="候補リスト",
            columns={"A": ColumnPolicy(mode="fit"), "B": ColumnPolicy(mode="fit")},
        )
        result = append_rows(gateway, target, [["b", "2"]], m)
        assert result.appended_rows == [3]
        assert gateway.append_calls[0][1] == "'候補リスト'!A:B"
        assert gateway.state.values[2] == ["b", "2"]
