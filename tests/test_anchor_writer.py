"""仕様（writer）: 末尾判定列 append_anchor_column による追加位置の決定。

実不具合（2026-11-08）: 台帳は A列チェックボックスが200行目まで事前設定
（FALSE 値入り）されているため、append がデータ末尾を200行目付近と
誤認し、新規行が末尾側に入った（本来はデータ最終行の直後）。

固定する期待動作:
- anchor 設定時: シート状態から「anchor 列に値（空でない）がある最終行」
  を求め、新規行はその直後に入る。A列など他列に事前設定値だけが
  下に続いていても影響されない。
- 読み戻し検証もその位置を前提に行われ、append が成功する
  （AppendResult.appended_rows が期待位置になる。行高・書式の適用先も
  その行になる。追加行の書式は、README の「上の行に揃える」に従い、
  追加位置の上の行＝anchor 最終データ行から継承する）。
- anchor 未設定では従来どおりの位置（他列の事前設定値に引っ張られた
  物理末尾の直後）になることを特性として固定する。

状態の数え方（ledger_gateway）:
- 1行目: ヘッダー
- 2〜20行目: データ19行（A="FALSE" / B=タスク名 / C=メモ）
- 21〜200行目: A列だけ "FALSE" が入った事前設定行（B・C は空）
よって anchor="B" での追加先は 21行目、未設定では 201行目。

FakeGateway の append は実 API のテーブル検出を模す（範囲の列範囲で
値のある最終行の直後へ挿入）。writer が anchor を効かせるには、
テーブル検出の対象が anchor 列基準になる範囲で append する必要がある。
"""

from fake_gateway import FakeGateway, make_state

from sheet_writer.config import ColumnPolicy, Target
from sheet_writer.writer import append_rows

COLUMNS = {
    "A": ColumnPolicy(mode="fit"),
    "B": ColumnPolicy(mode="wrap", width_px=300),
    "C": ColumnPolicy(mode="fit"),
}

NEW_ROW = ["", "新しいタスク", "新しいメモ"]


def anchor_target(anchor="B"):
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="テストタブ",
        columns=dict(COLUMNS),
        append_anchor_column=anchor,
    )


def plain_target():
    # anchor 未設定の Target（新フィールドを使わない従来形）
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="テストタブ",
        columns=dict(COLUMNS),
    )


def ledger_gateway(n_data=19, preset_last_row=200, **fake_kwargs):
    """ヘッダー＋データ＋A列のみ事前設定行が続くシート。

    データ行の書式は左寄せ、事前設定行の書式は中央寄せにして、
    追加行がどちらの行の書式を継承したか区別できるようにする。
    """
    values = [["チェック", "タスク", "メモ"]]
    values += [["FALSE", f"タスク{i}", "メモ"] for i in range(1, n_data + 1)]
    n_preset = preset_last_row - len(values)
    values += [["FALSE", "", ""] for _ in range(n_preset)]
    assert len(values) == preset_last_row
    formats = [[{"textFormat": {"bold": True}} for _ in range(3)]]
    formats += [
        [{"horizontalAlignment": "LEFT"} for _ in range(3)] for _ in range(n_data)
    ]
    formats += [
        [{"horizontalAlignment": "CENTER"} for _ in range(3)] for _ in range(n_preset)
    ]
    state = make_state(
        values,
        column_widths=[60, 300, 100],
        row_heights=[38] + [26] * n_data + [21] * n_preset,
        cell_formats=formats,
    )
    return FakeGateway(state, **fake_kwargs)


class TestAppendWithAnchor:
    def test_append_lands_right_after_anchor_last_row(self, m):
        gateway = ledger_gateway()
        result = append_rows(gateway, anchor_target("B"), [NEW_ROW], m)
        # データ最終行は20行目 → 追加は21行目
        assert result.appended_rows == [21]
        assert gateway.state.values[20] == NEW_ROW
        # 追加行の下は事前設定行のまま（消えたり上書きで欠けたりしない）
        assert gateway.state.values[21] == ["FALSE", "", ""]

    def test_append_two_rows_with_anchor(self, m):
        gateway = ledger_gateway()
        rows = [["", "タスクA", "a"], ["", "タスクB", "b"]]
        result = append_rows(gateway, anchor_target("B"), rows, m)
        assert result.appended_rows == [21, 22]
        assert gateway.state.values[20] == rows[0]
        assert gateway.state.values[21] == rows[1]
        assert gateway.state.values[22] == ["FALSE", "", ""]

    def test_row_height_is_applied_at_anchor_position(self, m):
        gateway = ledger_gateway()
        # B（wrap 300）に "あ"*30 → 2行分 → 行高42が21行目に付く
        result = append_rows(gateway, anchor_target("B"), [["", "あ" * 30, "x"]], m)
        assert result.appended_rows == [21]
        assert result.row_heights == {21: 42}
        assert gateway.state.row_heights[20] == 42

    def test_format_inherited_from_anchor_last_row(self, m):
        gateway = ledger_gateway()
        append_rows(gateway, anchor_target("B"), [NEW_ROW], m)
        new_formats = gateway.state.cell_formats[20]
        # 追加位置の上の行（20行目・データ行）の左寄せを継承する。
        # 事前設定行（中央寄せ）ではない。
        assert [c.get("horizontalAlignment") for c in new_formats] == [
            "LEFT",
            "LEFT",
            "LEFT",
        ]
        # wrap 列の WRAP 設定も従来どおり付く
        assert new_formats[1]["wrapStrategy"] == "WRAP"

    def test_anchor_column_decides_not_other_columns(self, m):
        # C は10行目までしか値がなく、B は20行目まで、A は200行目まで
        # 値がある状態で anchor="C" なら追加は11行目になる
        values = [["チェック", "タスク", "メモ"]]
        for i in range(1, 20):
            values.append(["FALSE", f"タスク{i}", "メモ" if i <= 9 else ""])
        values += [["FALSE", "", ""] for _ in range(180)]
        assert len(values) == 200
        state = make_state(
            values,
            column_widths=[60, 300, 100],
            row_heights=[38] + [26] * 199,
        )
        gateway = FakeGateway(state)
        result = append_rows(gateway, anchor_target("C"), [NEW_ROW], m)
        assert result.appended_rows == [11]
        assert gateway.state.values[10] == NEW_ROW

    def test_anchor_with_header_only_data_lands_at_row_2(self, m):
        # anchor 列の値がヘッダー（1行目）だけなら追加は2行目
        gateway = ledger_gateway(n_data=0, preset_last_row=10)
        result = append_rows(gateway, anchor_target("B"), [NEW_ROW], m)
        assert result.appended_rows == [2]
        assert gateway.state.values[1] == NEW_ROW


class TestAppendWithoutAnchorIsLegacy:
    def test_append_lands_after_preset_rows_without_anchor(self, m):
        # 特性固定: anchor 未設定では A列の事前設定値に引っ張られ、
        # 物理末尾（200行目）の直後＝201行目に入る
        gateway = ledger_gateway()
        result = append_rows(gateway, plain_target(), [NEW_ROW], m)
        assert result.appended_rows == [201]
        assert gateway.state.values[200] == NEW_ROW
