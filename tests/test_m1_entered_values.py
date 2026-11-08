"""M1: 書き込み後の値照合を実 API のセマンティクスに合わせる（先行テスト）。

仕様（QA 必須対応 M1）:
- 書き込みは USER_ENTERED で Sheets 側に解釈されるため、読み戻しの
  表示値（formattedValue）は整形されて返る（日付 "2026-11-15" →
  "2026/11/15"、金額 "12345" → "12,345"、数式 "=SUM(A2:A3)" → "300"）。
  表示値と書き込み文字列の単純比較だけでは、正しく書けていても
  検証エラーになり得る。
- 状態取得では各セルの入力値（userEnteredValue）も取得する:
  - SheetState に entered_values フィールド（各セルの userEnteredValue
    を表す dict の2次元リスト。値が無いセルは空 dict）を追加する。
  - CliGateway.get_state は API 応答の userEnteredValue をそこへ格納し、
    取得フィールド指定にも userEnteredValue を含める。
- writer の値検証:
  - 表示値が書き込み文字列と一致すれば合格（従来どおり）。
  - 一致しなくても、userEnteredValue が同じ値を表していれば合格:
    formulaValue（完全一致）/ stringValue（完全一致）/
    numberValue（数値として一致。日付・時刻は 1899-12-30 からの
    日数＋時刻の小数であるシリアル値）/
    boolValue（TRUE/FALSE の文字列表現と一致、大文字小文字は問わない）。
  - userEnteredValue が別の値を表している場合や、セル自体が
    落ちている（空）場合は、従来どおり VerificationError。
"""

import copy
import json
from datetime import date, datetime, time
from types import SimpleNamespace

import pytest

from fake_gateway import FakeGateway, make_state
from sheet_writer.config import ColumnPolicy
from sheet_writer.errors import VerificationError
from sheet_writer.gateway import CliGateway, SheetState
from sheet_writer.writer import append_rows

DUMMY_ID = "dummy-spreadsheet-id-0001"

# Sheets のシリアル値の起点（1899-12-30）。期待値はここから計算し、
# マジックナンバーにしない。
SERIAL_EPOCH = date(1899, 12, 30)


def serial_of_date(d):
    """日付だけのシリアル値（日数）。"""
    return float((d - SERIAL_EPOCH).days)


def serial_of_datetime(dt):
    """日時のシリアル値（日数＋時刻の小数）。"""
    seconds = dt.hour * 3600 + dt.minute * 60 + dt.second
    return (dt.date() - SERIAL_EPOCH).days + seconds / 86400


def serial_of_time(t):
    """時刻だけのシリアル値（1日に対する小数）。"""
    seconds = t.hour * 3600 + t.minute * 60 + t.second
    return seconds / 86400


# ---------------------------------------------------------------------------
# 実 API の振る舞いを模した Fake
# ---------------------------------------------------------------------------


class RealApiFakeGateway(FakeGateway):
    """表示値は整形済み・entered_values 付きで状態を返す FakeGateway。

    - formatted: {(行, 列): 表示値} — append 後の行など、読み戻し時に
      Sheets が整形して返す表示値を差し替える。
    - entered: {(行, 列): userEnteredValue dict} — 各セルの入力値。
      指定のないセルは空 dict（値なし）になる。
    土台は既存 FakeGateway（batch_update を解釈して寸法・書式を反映）
    なので、幅・高さ・書式の検証とは干渉しない。
    """

    def __init__(self, state, *, formatted=None, entered=None, **kwargs):
        super().__init__(state, **kwargs)
        self._formatted = dict(formatted or {})
        self._entered = dict(entered or {})

    def get_state(self, spreadsheet_id, tab):
        state = super().get_state(spreadsheet_id, tab)
        n_cols = max((len(row) for row in state.values), default=0)
        entered_grid = [[{} for _ in range(n_cols)] for _ in state.values]
        for (r, c), entered in self._entered.items():
            if r < len(entered_grid) and c < n_cols:
                entered_grid[r][c] = copy.deepcopy(entered)
        for (r, c), display in self._formatted.items():
            if r < len(state.values) and c < len(state.values[r]):
                state.values[r][c] = display
        try:
            state.entered_values = entered_grid
        except Exception:
            object.__setattr__(state, "entered_values", entered_grid)
        return state


def basic_gateway(formatted=None, entered=None, **fake_kwargs):
    """ヘッダー + データ2行のシート（test_writer.py の基本形と同形）。

    列: A=名前（fit） / B=メモ（wrap 300） / C=数量（fit）
    追加行は 4 行目（インデックス 3）に入る。
    """
    values = [
        ["名前", "メモ", "数量"],
        ["abc", "x", "10"],
        ["def", "y", "20"],
    ]
    state = make_state(
        values,
        column_widths=[50, 100, 80],
        row_heights=[38, 26, 26],
    )
    return RealApiFakeGateway(
        state, formatted=formatted, entered=entered, **fake_kwargs
    )


def basic_target(make_target):
    return make_target(
        {
            "A": ColumnPolicy(mode="fit"),
            "B": ColumnPolicy(mode="wrap", width_px=300),
            "C": ColumnPolicy(mode="fit"),
        }
    )


APPENDED = 3  # 追加行の0始まりインデックス


class TestWriterAcceptsSameValueViaEnteredValue:
    """表示値が整形されていても、入力値が同じ値を表せば合格する。"""

    def test_date_via_number_value_serial(self, m, make_target):
        # 書き込み "2026-11-15" → 表示 "2026/11/15"、入力値は日付シリアル
        gateway = basic_gateway(
            formatted={(APPENDED, 0): "2026/11/15"},
            entered={
                (APPENDED, 0): {"numberValue": serial_of_date(date(2026, 11, 15))}
            },
        )
        result = append_rows(
            gateway, basic_target(make_target), [["2026-11-15", "x", "1"]], m
        )
        assert result.appended_rows == [4]

    def test_datetime_via_number_value_serial(self, m, make_target):
        # 書き込み "2026-11-15 12:00:00" → 表示 "2026/11/15 12:00"
        gateway = basic_gateway(
            formatted={(APPENDED, 0): "2026/11/15 12:00"},
            entered={
                (APPENDED, 0): {
                    "numberValue": serial_of_datetime(
                        datetime(2026, 11, 15, 12, 0, 0)
                    )
                }
            },
        )
        result = append_rows(
            gateway,
            basic_target(make_target),
            [["2026-11-15 12:00:00", "x", "1"]],
            m,
        )
        assert result.appended_rows == [4]

    def test_time_via_number_value_serial(self, m, make_target):
        # 書き込み "13:30" → 表示 "13:30:00"、入力値は時刻の小数シリアル
        gateway = basic_gateway(
            formatted={(APPENDED, 0): "13:30:00"},
            entered={
                (APPENDED, 0): {"numberValue": serial_of_time(time(13, 30))}
            },
        )
        result = append_rows(
            gateway, basic_target(make_target), [["13:30", "x", "1"]], m
        )
        assert result.appended_rows == [4]

    def test_amount_via_number_value(self, m, make_target):
        # 書き込み "12345" → 表示 "12,345"、入力値は数値 12345
        gateway = basic_gateway(
            formatted={(APPENDED, 2): "12,345"},
            entered={(APPENDED, 2): {"numberValue": 12345}},
        )
        result = append_rows(
            gateway, basic_target(make_target), [["abc", "x", "12345"]], m
        )
        assert result.appended_rows == [4]

    def test_decimal_via_number_value_float(self, m, make_target):
        # 書き込み "1.5" → 表示は丸めた "2"、入力値は 1.5 のまま
        gateway = basic_gateway(
            formatted={(APPENDED, 2): "2"},
            entered={(APPENDED, 2): {"numberValue": 1.5}},
        )
        result = append_rows(
            gateway, basic_target(make_target), [["abc", "x", "1.5"]], m
        )
        assert result.appended_rows == [4]

    def test_formula_via_formula_value(self, m, make_target):
        # 書き込み "=SUM(C2:C3)" → 表示は計算結果 "30"、入力値は数式文字列
        gateway = basic_gateway(
            formatted={(APPENDED, 2): "30"},
            entered={(APPENDED, 2): {"formulaValue": "=SUM(C2:C3)"}},
        )
        result = append_rows(
            gateway, basic_target(make_target), [["abc", "x", "=SUM(C2:C3)"]], m
        )
        assert result.appended_rows == [4]

    def test_string_via_string_value(self, m, make_target):
        # 表示が変わって返っても、stringValue が完全一致すれば合格
        gateway = basic_gateway(
            formatted={(APPENDED, 0): "ABC"},
            entered={(APPENDED, 0): {"stringValue": "abc"}},
        )
        result = append_rows(
            gateway, basic_target(make_target), [["abc", "x", "1"]], m
        )
        assert result.appended_rows == [4]

    def test_bool_true_case_insensitive(self, m, make_target):
        # 書き込み "true" → 表示は正規形 "TRUE"、入力値は bool True
        gateway = basic_gateway(
            formatted={(APPENDED, 0): "TRUE"},
            entered={(APPENDED, 0): {"boolValue": True}},
        )
        result = append_rows(
            gateway, basic_target(make_target), [["true", "x", "1"]], m
        )
        assert result.appended_rows == [4]

    def test_bool_false_case_insensitive(self, m, make_target):
        gateway = basic_gateway(
            formatted={(APPENDED, 0): "FALSE"},
            entered={(APPENDED, 0): {"boolValue": False}},
        )
        result = append_rows(
            gateway, basic_target(make_target), [["False", "x", "1"]], m
        )
        assert result.appended_rows == [4]

    def test_display_match_still_passes_without_entered(self, m, make_target):
        # 従来どおり: 表示値が書き込み文字列と一致すれば合格
        # （entered_values が空 dict でもよい）
        gateway = basic_gateway()
        result = append_rows(
            gateway, basic_target(make_target), [["abc", "x", "1"]], m
        )
        assert result.appended_rows == [4]


class TestWriterRejectsDifferentEnteredValue:
    """入力値が別の値を表す・セルが落ちている場合は VerificationError。"""

    def test_different_number_value(self, m, make_target):
        gateway = basic_gateway(
            formatted={(APPENDED, 2): "12,346"},
            entered={(APPENDED, 2): {"numberValue": 12346}},
        )
        with pytest.raises(VerificationError):
            append_rows(
                gateway, basic_target(make_target), [["abc", "x", "12345"]], m
            )

    def test_different_date_serial(self, m, make_target):
        # 1日ずれた日付シリアルは別の値
        gateway = basic_gateway(
            formatted={(APPENDED, 0): "2026/11/16"},
            entered={
                (APPENDED, 0): {"numberValue": serial_of_date(date(2026, 11, 16))}
            },
        )
        with pytest.raises(VerificationError):
            append_rows(
                gateway, basic_target(make_target), [["2026-11-15", "x", "1"]], m
            )

    def test_different_formula_value(self, m, make_target):
        gateway = basic_gateway(
            formatted={(APPENDED, 2): "999"},
            entered={(APPENDED, 2): {"formulaValue": "=SUM(C2:C4)"}},
        )
        with pytest.raises(VerificationError):
            append_rows(
                gateway, basic_target(make_target), [["abc", "x", "=SUM(C2:C3)"]], m
            )

    def test_different_string_value(self, m, make_target):
        gateway = basic_gateway(
            formatted={(APPENDED, 0): "abd"},
            entered={(APPENDED, 0): {"stringValue": "abd"}},
        )
        with pytest.raises(VerificationError):
            append_rows(
                gateway, basic_target(make_target), [["abc", "x", "1"]], m
            )

    def test_different_bool_value(self, m, make_target):
        gateway = basic_gateway(
            formatted={(APPENDED, 0): "FALSE"},
            entered={(APPENDED, 0): {"boolValue": False}},
        )
        with pytest.raises(VerificationError):
            append_rows(
                gateway, basic_target(make_target), [["TRUE", "x", "1"]], m
            )

    def test_empty_cell_is_rejected(self, m, make_target):
        # セル自体が落ちている（表示値も入力値も空）場合は従来どおり失敗
        gateway = basic_gateway(formatted={(APPENDED, 0): ""})
        with pytest.raises(VerificationError):
            append_rows(
                gateway, basic_target(make_target), [["消えるはず", "x", "1"]], m
            )


# ---------------------------------------------------------------------------
# CliGateway / SheetState の契約
# ---------------------------------------------------------------------------


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


def grid_payload(cells):
    """cells（userEnteredValue を含むセル dict の2次元リスト）から
    spreadsheets.get の応答を作る。"""
    row_data = []
    for row in cells:
        row_data.append({"values": row})
    return {
        "spreadsheetId": DUMMY_ID,
        "sheets": [
            {
                "properties": {"sheetId": 7, "title": "タブ"},
                "data": [
                    {
                        "rowData": row_data,
                        "rowMetadata": [{"pixelSize": 38}] + [{"pixelSize": 26}] * (
                            len(cells) - 1
                        ),
                        "columnMetadata": [
                            {"pixelSize": 100} for _ in range(len(cells[0]))
                        ],
                    }
                ],
            }
        ],
    }


class TestGatewayEnteredValues:
    def test_sheet_state_accepts_entered_values(self):
        state = SheetState(
            sheet_id=3,
            values=[["a"]],
            column_widths=[120],
            row_heights=[26],
            cell_formats=[[{}]],
            entered_values=[[{"stringValue": "a"}]],
        )
        assert state.entered_values == [[{"stringValue": "a"}]]

    def test_get_state_stores_user_entered_values(self):
        cells = [
            [
                {
                    "formattedValue": "2026/11/15",
                    "userEnteredFormat": {},
                    "userEnteredValue": {
                        "numberValue": serial_of_date(date(2026, 11, 15))
                    },
                },
                {
                    "formattedValue": "メモ",
                    "userEnteredFormat": {},
                    "userEnteredValue": {"stringValue": "メモ"},
                },
            ],
            [
                {
                    "formattedValue": "30",
                    "userEnteredFormat": {},
                    "userEnteredValue": {"formulaValue": "=SUM(A2:A3)"},
                },
                {
                    "formattedValue": "TRUE",
                    "userEnteredFormat": {},
                    "userEnteredValue": {"boolValue": True},
                },
            ],
        ]
        runner = FakeRunner(grid_payload(cells))
        gateway = CliGateway(runner=runner)
        state = gateway.get_state(DUMMY_ID, "タブ")

        assert getattr(state, "entered_values", None) == [
            [
                {"numberValue": serial_of_date(date(2026, 11, 15))},
                {"stringValue": "メモ"},
            ],
            [
                {"formulaValue": "=SUM(A2:A3)"},
                {"boolValue": True},
            ],
        ]
        # 表示値・書式など既存の取得も壊れていない
        assert state.values == [["2026/11/15", "メモ"], ["30", "TRUE"]]

    def test_cell_without_user_entered_value_is_empty_dict(self):
        cells = [
            [
                {"formattedValue": "名前", "userEnteredFormat": {}},
                {
                    "formattedValue": "x",
                    "userEnteredFormat": {},
                    "userEnteredValue": {"stringValue": "x"},
                },
            ]
        ]
        runner = FakeRunner(grid_payload(cells))
        gateway = CliGateway(runner=runner)
        state = gateway.get_state(DUMMY_ID, "タブ")

        entered = getattr(state, "entered_values", None)
        assert entered is not None
        assert entered[0][0] == {}
        assert entered[0][1] == {"stringValue": "x"}
        # values と同じ形（行数・列数）である
        assert len(entered) == len(state.values)
        assert all(
            len(entered_row) == len(value_row)
            for entered_row, value_row in zip(entered, state.values)
        )

    def test_get_state_requests_user_entered_value_field(self):
        cells = [[{"formattedValue": "a", "userEnteredFormat": {}}]]
        runner = FakeRunner(grid_payload(cells))
        gateway = CliGateway(runner=runner)
        gateway.get_state(DUMMY_ID, "タブ")

        (cmd,) = runner.calls
        # 取得フィールド指定のどこかに userEnteredValue が含まれている
        assert "userEnteredValue" in json.dumps(cmd, ensure_ascii=False)
