"""仕様（本題）: チェックボックス設定チェック — checker / Fake の意味論。

checker（check_sheet / fix_sheet）:
- ``checkbox_columns`` で列挙した列についてだけ、データ行（2行目以降）の
  セルを検査する。有効化していない対象では検査しない（opt-in）。
- 「真偽値が入っている」とは、userEnteredValue に boolValue があるか、
  表示値が "TRUE" / "FALSE" のいずれかであること（文字列として
  "FALSE" と打たれたセルも、チェックボックス列では真偽値のつもりの
  入力なので対象に含める。これが発端の不整合の実態）。
- 真偽値があるのに、そのセルの入力規則（dataValidation）の
  condition.type が "BOOLEAN" でない場合は違反にする。
  kind="checkbox"、location は "A20" のようなセル番地、
  expected="BOOLEAN"、actual は現行の condition.type（無ければ "未設定"）。
- ヘッダー行・空セル・真偽値でないセル・対象外の列は違反にしない。
- append_anchor_column 設定時は、他のチェックと同様に検査範囲は
  anchor 最終行まで。それより下の行は対象外で、--fix も触らない。
- fix では違反セルへ setDataValidation で BOOLEAN の入力規則だけを
  設定し、再検査で違反ゼロになる。値・数式・書式には触らない
  （従来の「書式専任」の範囲。入力規則は値ではない）。

Fake:
- make_state は data_validations（セル単位の入力規則グリッド）を
  受け取り、batch_update の setDataValidation リクエストを解釈して
  状態へ反映する。
"""

from fake_gateway import DUMMY_SHEET_ID, FakeGateway, make_state

from sheet_writer.checker import check_sheet, fix_sheet
from sheet_writer.config import ColumnPolicy, Target

BOOLEAN_RULE = {"condition": {"type": "BOOLEAN"}, "strict": True}
LIST_RULE = {
    "condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": "x"}]}
}

COLUMNS = {
    "A": ColumnPolicy(mode="fit"),
    "B": ColumnPolicy(mode="wrap", width_px=300),
}

HEADER = ["不要", "タスク"]


def checkbox_target(checkbox_columns=("A",), **overrides):
    kwargs = {
        "spreadsheet_id": "dummy-spreadsheet-id-0001",
        "tab": "テストタブ",
        "columns": dict(COLUMNS),
        "checkbox_columns": checkbox_columns,
    }
    kwargs.update(overrides)
    return Target(**kwargs)


def checkbox_violations(violations):
    return [v for v in violations if v.kind == "checkbox"]


def clean_gateway(values, validations=None, entered=None, **fake_kwargs):
    """チェックボックス以外はクリーンなシート（幅・高さの違反が出ない寸法）。

    entered は userEnteredValue のグリッド。省略時は make_state の
    既定合成（文字列は stringValue）に従う。
    """
    state = make_state(
        values,
        column_widths=[100, 300],
        row_heights=[38] + [26] * (len(values) - 1),
        data_validations=validations,
    )
    if entered is not None:
        state.entered_values = entered
    return FakeGateway(state, **fake_kwargs)


def bool_entered(rows):
    """表示値が TRUE/FALSE のセルを boolValue 入力として合成する。"""
    grid = []
    for row in rows:
        out = []
        for value in row:
            if value == "TRUE":
                out.append({"boolValue": True})
            elif value == "FALSE":
                out.append({"boolValue": False})
            elif value == "":
                out.append({})
            else:
                out.append({"stringValue": value})
        grid.append(out)
    return grid


# ---------------------------------------------------------------------------
# checker: 検出
# ---------------------------------------------------------------------------


class TestCheckerDetectsCheckbox:
    def test_bool_value_without_rule_is_a_violation(self, m):
        values = [HEADER, ["FALSE", "掃除"], ["TRUE", "洗濯"]]
        validations = [[{}, {}], [{}, {}], [BOOLEAN_RULE, {}]]
        gateway = clean_gateway(values, validations, entered=bool_entered(values))
        violations = checkbox_violations(check_sheet(gateway, checkbox_target(), m))
        assert len(violations) == 1
        assert violations[0].location == "A2"
        assert violations[0].expected == "BOOLEAN"
        assert violations[0].actual == "未設定"

    def test_string_false_without_rule_is_a_violation(self, m):
        # 発端の不整合そのもの: 文字列 "FALSE" で入り、入力規則がない
        values = [HEADER, ["FALSE", "掃除"]]
        gateway = clean_gateway(values, [[{}, {}], [{}, {}]])
        violations = checkbox_violations(check_sheet(gateway, checkbox_target(), m))
        assert [v.location for v in violations] == ["A2"]

    def test_bool_value_with_boolean_rule_is_clean(self, m):
        values = [HEADER, ["FALSE", "掃除"], ["TRUE", "洗濯"]]
        validations = [[{}, {}], [BOOLEAN_RULE, {}], [BOOLEAN_RULE, {}]]
        gateway = clean_gateway(values, validations, entered=bool_entered(values))
        assert check_sheet(gateway, checkbox_target(), m) == []

    def test_bool_value_with_other_rule_type_is_a_violation(self, m):
        values = [HEADER, ["FALSE", "掃除"]]
        validations = [[{}, {}], [LIST_RULE, {}]]
        gateway = clean_gateway(values, validations, entered=bool_entered(values))
        violations = checkbox_violations(check_sheet(gateway, checkbox_target(), m))
        assert len(violations) == 1
        assert violations[0].location == "A2"
        assert violations[0].actual == "ONE_OF_LIST"

    def test_empty_cell_without_rule_is_clean(self, m):
        values = [HEADER, ["", "掃除"], ["", "洗濯"]]
        gateway = clean_gateway(values, [[{}, {}], [{}, {}], [{}, {}]])
        assert check_sheet(gateway, checkbox_target(), m) == []

    def test_non_bool_text_in_checkbox_column_is_clean(self, m):
        values = [HEADER, ["対象外", "掃除"]]
        gateway = clean_gateway(values, [[{}, {}], [{}, {}]])
        assert check_sheet(gateway, checkbox_target(), m) == []

    def test_header_row_is_exempt(self, m):
        # ヘッダーに真偽値があっても対象外
        values = [["TRUE", "タスク"], ["FALSE", "掃除"]]
        validations = [[{}, {}], [BOOLEAN_RULE, {}]]
        gateway = clean_gateway(values, validations, entered=bool_entered(values))
        assert check_sheet(gateway, checkbox_target(), m) == []

    def test_other_columns_are_not_checked(self, m):
        values = [HEADER, ["TRUE", "FALSE"]]
        validations = [[{}, {}], [BOOLEAN_RULE, {}]]
        gateway = clean_gateway(values, validations, entered=bool_entered(values))
        assert check_sheet(gateway, checkbox_target(), m) == []

    def test_rule_disabled_by_default(self, m):
        values = [HEADER, ["FALSE", "掃除"]]
        gateway = clean_gateway(values, [[{}, {}], [{}, {}]])
        assert check_sheet(gateway, checkbox_target(checkbox_columns=()), m) == []

    def test_multiple_checkbox_columns(self, m):
        values = [HEADER, ["FALSE", "TRUE"]]
        gateway = clean_gateway(values, [[{}, {}], [{}, {}]])
        target = checkbox_target(checkbox_columns=("A", "B"))
        violations = checkbox_violations(check_sheet(gateway, target, m))
        assert sorted(v.location for v in violations) == ["A2", "B2"]

    def test_each_cell_reported_separately(self, m):
        values = [HEADER, ["FALSE", "掃除"], ["TRUE", "洗濯"], ["FALSE", "買物"]]
        gateway = clean_gateway(values, [[{}, {}] for _ in values])
        violations = checkbox_violations(check_sheet(gateway, checkbox_target(), m))
        assert [v.location for v in violations] == ["A2", "A3", "A4"]


class TestCheckboxScopeWithAnchor:
    def test_rows_beyond_anchor_last_row_are_exempt(self, m):
        values = [
            HEADER,
            ["FALSE", "掃除"],
            ["FALSE", ""],  # anchor（B列）が空 = 検査範囲外
            ["FALSE", ""],
        ]
        gateway = clean_gateway(values, [[{}, {}] for _ in values])
        target = checkbox_target(append_anchor_column="B")
        violations = checkbox_violations(check_sheet(gateway, target, m))
        assert [v.location for v in violations] == ["A2"]

    def test_fix_does_not_touch_rows_beyond_anchor(self, m):
        values = [HEADER, ["FALSE", "掃除"], ["FALSE", ""]]
        gateway = clean_gateway(values, [[{}, {}] for _ in values])
        target = checkbox_target(append_anchor_column="B")
        fixed = fix_sheet(gateway, target, m)
        assert [v.location for v in checkbox_violations(fixed)] == ["A2"]
        validations = gateway.state.data_validations
        assert validations[1][0] == {
            "condition": {"type": "BOOLEAN"},
            "showCustomUi": True,
        }
        assert validations[2][0] == {}


# ---------------------------------------------------------------------------
# checker: fix
# ---------------------------------------------------------------------------


class TestFixSetsCheckboxRule:
    def test_fix_sets_boolean_rule_and_recheck_is_clean(self, m):
        values = [HEADER, ["FALSE", "掃除"], ["TRUE", "洗濯"]]
        gateway = clean_gateway(values, [[{}, {}] for _ in values])
        fixed = fix_sheet(gateway, checkbox_target(), m)
        assert [v.location for v in checkbox_violations(fixed)] == ["A2", "A3"]
        state = gateway.state
        expected_rule = {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}
        assert state.data_validations[1][0] == expected_rule
        assert state.data_validations[2][0] == expected_rule
        assert check_sheet(gateway, checkbox_target(), m) == []

    def test_fix_does_not_touch_values_or_formats(self, m):
        values = [HEADER, ["FALSE", "掃除"]]
        gateway = clean_gateway(values, [[{}, {}], [{}, {}]])
        before = gateway.state
        fix_sheet(gateway, checkbox_target(), m)
        after = gateway.state
        assert after.values == before.values
        assert after.entered_values == before.entered_values
        assert after.cell_formats == before.cell_formats

    def test_fix_uses_set_data_validation_with_boolean_condition(self, m):
        values = [HEADER, ["FALSE", "掃除"]]
        gateway = clean_gateway(values, [[{}, {}], [{}, {}]])
        fix_sheet(gateway, checkbox_target(), m)
        requests = [
            req["setDataValidation"]
            for req in gateway.batch_requests
            if "setDataValidation" in req
        ]
        assert len(requests) == 1
        body = requests[0]
        assert body["rule"]["condition"]["type"] == "BOOLEAN"
        rng = body["range"]
        assert rng["sheetId"] == DUMMY_SHEET_ID
        assert rng["startRowIndex"] == 1 and rng["endRowIndex"] == 2
        assert rng["startColumnIndex"] == 0 and rng["endColumnIndex"] == 1
        # 値の書き込みリクエストは含まれない
        assert all(
            "updateCells" not in req and "repeatCell" not in req
            for req in gateway.batch_requests
        )

    def test_fix_replaces_other_rule_type(self, m):
        values = [HEADER, ["FALSE", "掃除"]]
        validations = [[{}, {}], [LIST_RULE, {}]]
        gateway = clean_gateway(values, validations, entered=bool_entered(values))
        fix_sheet(gateway, checkbox_target(), m)
        assert gateway.state.data_validations[1][0]["condition"]["type"] == "BOOLEAN"
        assert check_sheet(gateway, checkbox_target(), m) == []

    def test_fix_with_rule_disabled_changes_nothing(self, m):
        values = [HEADER, ["FALSE", "掃除"]]
        gateway = clean_gateway(values, [[{}, {}], [{}, {}]])
        before = gateway.state
        assert fix_sheet(gateway, checkbox_target(checkbox_columns=()), m) == []
        assert gateway.state.data_validations == before.data_validations
        assert gateway.batch_requests == []


# ---------------------------------------------------------------------------
# Fake の setDataValidation 意味論（テスト基盤の担保）
# ---------------------------------------------------------------------------


def set_validation_request(row, col, rule):
    return {
        "setDataValidation": {
            "range": {
                "sheetId": DUMMY_SHEET_ID,
                "startRowIndex": row,
                "endRowIndex": row + 1,
                "startColumnIndex": col,
                "endColumnIndex": col + 1,
            },
            "rule": rule,
        }
    }


class TestFakeSetDataValidationSemantics:
    def test_rule_is_applied_to_state(self):
        values = [HEADER, ["FALSE", "掃除"]]
        gateway = clean_gateway(values, [[{}, {}], [{}, {}]])
        rule = {"condition": {"type": "BOOLEAN"}, "showCustomUi": True}
        gateway.batch_update(
            "dummy-spreadsheet-id-0001", [set_validation_request(1, 0, rule)]
        )
        assert gateway.state.data_validations[1][0] == rule
        assert gateway.state.data_validations[1][1] == {}

    def test_make_state_default_validations_are_empty(self):
        state = make_state([["a", "b"], ["c", "d"]])
        assert state.data_validations == [[{}, {}], [{}, {}]]

    def test_appended_row_gets_empty_validations(self, m):
        values = [HEADER, ["FALSE", "掃除"]]
        validations = [[{}, {}], [BOOLEAN_RULE, {}]]
        gateway = clean_gateway(values, validations, entered=bool_entered(values))
        target = checkbox_target()
        from sheet_writer.writer import append_rows

        append_rows(gateway, target, [["", "片付け"]], m)
        state = gateway.state
        assert len(state.data_validations) == len(state.values)
        assert all(len(row) == 2 for row in state.data_validations)
