"""仕様（writer・必須1）: anchor 経路で書込先セルの既存書式が残留しない。

実地の形: 台帳では書込先が事前設定行（チェックボックス行）になる。
anchor 経路は values update で既存セルへ直接書くため、書込先セルに
元々あった書式が、継承した意図書式に無いキーまで残ってしまう。
現行は意図書式が空のキーに書式リクエストを送らないため残留を消せず、
background_rule 有効時は必ず VerificationError になり、checker は
範囲外として消せないためデッドロックする。

固定する期待動作:
- anchor + background_rule 有効: 書込先の事前設定行セルに
  backgroundColor / backgroundColorStyle があっても append が成功し、
  追加行のセルに背景キーが残らない。他の意図書式（配置・WRAP 等）は
  従来どおり付く。対象は追加行だけで、下の事前設定行は触らない。
- anchor + ルール無効: 書込先セルに、継承元に無い numberFormat
  （日付書式）がある状態で append し、追加行セルの書式が意図どおり
  （numberFormat の残留なし）になる。

実装想定は「anchor 経路では追加行セルへ全継承キーを fields に挙げた
repeatCell を送り、マスクで残留を消す」こと。Fake のマスク意味論は
test_fake_field_mask.py で一般化を担保済み。

状態の数え方:
- 1行目: ヘッダー
- 2〜4行目: データ3行（B=タスク名あり）
- 5〜7行目: A列だけ値がある事前設定行（B は空）
よって anchor="B" での追加先は5行目で、書式の継承元は4行目。
"""

from fake_gateway import FakeGateway, make_state

from sheet_writer.config import ColumnPolicy, Target
from sheet_writer.writer import append_rows

PALE = {"red": 0.9, "green": 0.95, "blue": 0.9}
STYLE_PALE = {"rgbColor": {"red": 0.9, "green": 0.95, "blue": 0.9}}
DATE_FORMAT = {"type": "DATE", "pattern": "yyyy/mm/dd"}

COLUMNS = {
    "A": ColumnPolicy(mode="fit"),
    "B": ColumnPolicy(mode="wrap", width_px=300),
    "C": ColumnPolicy(mode="fit"),
}

NEW_ROW = ["", "新しいタスク", "5"]

# 継承元（4行目）の書式: 配置のみで、背景も numberFormat も持たない
DATA_FORMATS = [
    {"horizontalAlignment": "LEFT"},
    {"horizontalAlignment": "LEFT"},
    {"horizontalAlignment": "RIGHT"},
]


def anchor_target(background_rule=False):
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="テストタブ",
        columns=dict(COLUMNS),
        append_anchor_column="B",
        background_rule=background_rule,
    )


def preset_gateway(preset_format, destination_overrides=None):
    """事前設定行の全セルに preset_format を持たせたシート。

    destination_overrides は {(列インデックス): 追加書式} で、書込先
    （5行目）の特定セルだけ書式を差し替えたい場合に使う。
    """
    values = [
        ["チェック", "タスク", "数量"],
        ["FALSE", "タスク1", "10"],
        ["FALSE", "タスク2", "20"],
        ["FALSE", "タスク3", "30"],
        ["FALSE", "", ""],
        ["FALSE", "", ""],
        ["FALSE", "", ""],
    ]
    formats = [[{"textFormat": {"bold": True}} for _ in range(3)]]
    formats += [[dict(cell) for cell in DATA_FORMATS] for _ in range(3)]
    formats += [[dict(preset_format) for _ in range(3)] for _ in range(3)]
    for col, extra in (destination_overrides or {}).items():
        formats[4][col].update(extra)
    state = make_state(
        values,
        column_widths=[100, 300, 100],
        row_heights=[38, 26, 26, 26, 21, 21, 21],
        cell_formats=formats,
    )
    return FakeGateway(state)


class TestAnchorAppendClearsPresetBackground:
    def test_append_succeeds_and_background_does_not_remain(self, m):
        gateway = preset_gateway(
            {
                "backgroundColor": PALE,
                "backgroundColorStyle": STYLE_PALE,
                "horizontalAlignment": "CENTER",
            }
        )
        result = append_rows(gateway, anchor_target(background_rule=True), [NEW_ROW], m)
        assert result.appended_rows == [5]
        assert gateway.state.values[4] == NEW_ROW
        new_formats = gateway.state.cell_formats[4]
        for cell in new_formats:
            assert "backgroundColor" not in cell
            assert "backgroundColorStyle" not in cell

    def test_other_intended_formats_still_applied(self, m):
        gateway = preset_gateway(
            {
                "backgroundColor": PALE,
                "backgroundColorStyle": STYLE_PALE,
                "horizontalAlignment": "CENTER",
            }
        )
        append_rows(gateway, anchor_target(background_rule=True), [NEW_ROW], m)
        new_formats = gateway.state.cell_formats[4]
        # 配置は継承元（4行目）のものが付き、事前設定行の中央寄せは残らない
        assert [c.get("horizontalAlignment") for c in new_formats] == [
            "LEFT",
            "LEFT",
            "RIGHT",
        ]
        # wrap 列の WRAP 設定も従来どおり付く
        assert new_formats[1]["wrapStrategy"] == "WRAP"

    def test_preset_rows_below_are_not_touched(self, m):
        gateway = preset_gateway(
            {
                "backgroundColor": PALE,
                "backgroundColorStyle": STYLE_PALE,
                "horizontalAlignment": "CENTER",
            }
        )
        append_rows(gateway, anchor_target(background_rule=True), [NEW_ROW], m)
        # 追加行より下の事前設定行の背景はそのまま（消すのは追加行だけ）
        assert gateway.state.cell_formats[5][0]["backgroundColor"] == PALE
        assert gateway.state.cell_formats[6][0]["backgroundColor"] == PALE


class TestAnchorAppendClearsPresetNumberFormat:
    def test_number_format_does_not_remain_when_rule_off(self, m):
        # 書込先（5行目）の C 列だけに、継承元に無い日付書式を持たせる
        gateway = preset_gateway(
            {"horizontalAlignment": "CENTER"},
            destination_overrides={2: {"numberFormat": DATE_FORMAT}},
        )
        result = append_rows(
            gateway, anchor_target(background_rule=False), [NEW_ROW], m
        )
        assert result.appended_rows == [5]
        new_formats = gateway.state.cell_formats[4]
        # 追加行の書式は意図どおり（numberFormat の残留なし）
        assert new_formats[2] == {"horizontalAlignment": "RIGHT"}
        assert new_formats[0] == {"horizontalAlignment": "LEFT"}
        assert new_formats[1] == {
            "horizontalAlignment": "LEFT",
            "wrapStrategy": "WRAP",
        }
