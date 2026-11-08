"""仕様（checker）: 末尾判定列 append_anchor_column による検査範囲の決定。

実不具合（2026-11-08）: A列チェックボックスが200行目まで事前設定された
台帳で、checker がチェックボックスのみの行へ row_height の幽霊違反を
大量に出した（取りまとめ実測179件）。原因は writer と共通で
「末尾＝いずれかの列に値のある最終行」という判定。

固定する期待動作:
- anchor 設定時: 検査対象のデータ行は「anchor 列に値のある最終行」
  まで。それより下の行（他列に事前設定値のみの行）は row_height・
  wrap・background のいずれの対象にもしない。fix も同様に対象外。
- ただし anchor 最終行までのデータ行の違反は、従来どおり検出する
  （範囲を狭めたことで本物の違反まで消えないこと）。
- anchor 未設定では従来どおり、事前設定値のみの行も違反になることを
  特性として固定する。

状態の数え方（preset_gateway）:
- 1行目: ヘッダー
- 2〜4行目: データ3行（B=タスク名あり）
- 5〜8行目: A列だけ "FALSE" が入った事前設定行（B は空）
よって anchor="B" での検査対象は4行目まで。
"""

from fake_gateway import FakeGateway, make_state
from sheet_writer.checker import check_sheet, fix_sheet
from sheet_writer.config import ColumnPolicy, Target

PALE = {"red": 0.9, "green": 0.95, "blue": 0.9}

COLUMNS = {
    "A": ColumnPolicy(mode="fit"),
    "B": ColumnPolicy(mode="wrap", width_px=300),
}


def anchor_target(anchor="B", columns=None, **kwargs):
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="テストタブ",
        columns=dict(COLUMNS) if columns is None else columns,
        append_anchor_column=anchor,
        **kwargs,
    )


def plain_target(**kwargs):
    # anchor 未設定の Target（新フィールドを使わない従来形）
    return Target(
        spreadsheet_id="dummy-spreadsheet-id-0001",
        tab="テストタブ",
        columns=dict(COLUMNS),
        **kwargs,
    )


def preset_gateway(preset_height=21, cell_formats=None, **fake_kwargs):
    """事前設定行は行高不足（必要26pxに対し preset_height）の状態。

    データ行は幅・高さとも十分で、違反が出るのは事前設定行だけになる。
    """
    values = [
        ["チェック", "タスク"],
        ["FALSE", "タスク1"],
        ["FALSE", "タスク2"],
        ["FALSE", "タスク3"],
        ["FALSE", ""],
        ["FALSE", ""],
        ["FALSE", ""],
        ["FALSE", ""],
    ]
    state = make_state(
        values,
        column_widths=[100, 300],
        row_heights=[38, 26, 26, 26] + [preset_height] * 4,
        cell_formats=cell_formats,
    )
    return FakeGateway(state, **fake_kwargs)


def row_height_locations(violations):
    return [v.location for v in violations if v.kind == "row_height"]


class TestRowHeightScope:
    def test_preset_rows_below_anchor_are_not_flagged(self, m):
        gateway = preset_gateway()
        assert check_sheet(gateway, anchor_target("B"), m) == []

    def test_preset_rows_are_flagged_without_anchor(self, m):
        # 特性固定: anchor 未設定では事前設定行（5〜8行目）も
        # row_height 違反になる（幽霊違反の従来動作）
        gateway = preset_gateway()
        violations = check_sheet(gateway, plain_target(), m)
        assert row_height_locations(violations) == [
            "5行目",
            "6行目",
            "7行目",
            "8行目",
        ]

    def test_real_violation_within_anchor_range_is_still_flagged(self, m):
        # データ行（3行目）の本物の行高不足は anchor でも検出する:
        # B に WRAP 済みの "あ"*30（2行分・必要42px）で高さ26px
        values = [
            ["チェック", "タスク"],
            ["FALSE", "タスク1"],
            ["FALSE", "あ" * 30],
            ["FALSE", "タスク3"],
            ["FALSE", ""],
            ["FALSE", ""],
        ]
        formats = [[{}, {}] for _ in values]
        formats[2][1] = {"wrapStrategy": "WRAP"}
        state = make_state(
            values,
            column_widths=[100, 300],
            row_heights=[38, 26, 26, 26, 21, 21],
            cell_formats=formats,
        )
        gateway = FakeGateway(state)
        violations = check_sheet(gateway, anchor_target("B"), m)
        assert row_height_locations(violations) == ["3行目"]

    def test_fix_does_not_touch_preset_rows_with_anchor(self, m):
        gateway = preset_gateway()
        target = anchor_target("B")
        assert fix_sheet(gateway, target, m) == []
        # 事前設定行の高さは直されずそのまま
        assert gateway.state.row_heights[4:] == [21, 21, 21, 21]

    def test_fix_repairs_preset_rows_without_anchor(self, m):
        # 特性固定: anchor 未設定では fix も事前設定行を対象にする
        gateway = preset_gateway()
        fixed = fix_sheet(gateway, plain_target(), m)
        assert len(row_height_locations(fixed)) == 4
        assert gateway.state.row_heights[4:] == [26, 26, 26, 26]


WRAP_COLUMNS = {
    "A": ColumnPolicy(mode="fit"),
    "B": ColumnPolicy(mode="wrap", width_px=300),
    "C": ColumnPolicy(mode="wrap", width_px=300),
}


class TestWrapScope:
    def _wrap_gateway(self):
        """データ行2行目と事前設定行に、折り返し未設定のはみ出しを作る。

        列は A=fit / B=wrap（anchor）/ C=wrap。現在幅はどれも100px。
        - 2行目 B: "あ"*20 が幅100pxに収まらず WRAP なし → wrap 違反 B2
        - 事前設定行（5・6行目）C: B は空だが C に "あ"*20 があり
          WRAP なし → anchor 未設定なら wrap 違反 C5・C6
        判定は kind="wrap" の location だけを見る（列幅違反など
        他種別の有無はこのテストの対象外）。
        """
        values = [
            ["チェック", "タスク", "メモ"],
            ["x", "あ" * 20, "短い"],
            ["x", "短い", "短い"],
            ["x", "短い", "短い"],
            ["FALSE", "", "あ" * 20],
            ["FALSE", "", "あ" * 20],
        ]
        state = make_state(
            values,
            column_widths=[100, 100, 100],
            row_heights=[38, 58, 26, 26, 58, 58],
        )
        return FakeGateway(state)

    def test_wrap_below_anchor_is_not_flagged(self, m):
        gateway = self._wrap_gateway()
        target = anchor_target("B", columns=dict(WRAP_COLUMNS))
        violations = check_sheet(gateway, target, m)
        wrap = [v.location for v in violations if v.kind == "wrap"]
        # データ行の本物の違反だけが残り、事前設定行は対象外
        assert wrap == ["B2"]

    def test_wrap_below_anchor_is_flagged_without_anchor(self, m):
        gateway = self._wrap_gateway()
        target = Target(
            spreadsheet_id="dummy-spreadsheet-id-0001",
            tab="テストタブ",
            columns=dict(WRAP_COLUMNS),
        )
        violations = check_sheet(gateway, target, m)
        wrap = sorted(v.location for v in violations if v.kind == "wrap")
        assert wrap == ["B2", "C5", "C6"]


class TestBackgroundScope:
    def _background_gateway(self):
        """データ行2行目 B と事前設定行の A に背景色がある状態。

        背景色チェック自体は background_rule（別仕様）で有効化する。
        行高は全行十分にして、background 以外の違反が出ない寸法にする。
        """
        formats = [[{}, {}] for _ in range(6)]
        formats[1][1] = {"backgroundColor": PALE}  # データ行の本物の違反
        formats[4][0] = {"backgroundColor": PALE}  # 事前設定行
        formats[5][0] = {"backgroundColor": PALE}  # 事前設定行
        values = [
            ["チェック", "タスク"],
            ["FALSE", "タスク1"],
            ["FALSE", "タスク2"],
            ["FALSE", "タスク3"],
            ["FALSE", ""],
            ["FALSE", ""],
        ]
        state = make_state(
            values,
            column_widths=[100, 300],
            row_heights=[38, 26, 26, 26, 26, 26],
            cell_formats=formats,
        )
        return FakeGateway(state)

    def test_background_below_anchor_is_not_flagged(self, m):
        gateway = self._background_gateway()
        target = anchor_target("B", background_rule=True)
        violations = check_sheet(gateway, target, m)
        background = [v.location for v in violations if v.kind == "background"]
        assert background == ["B2"]

    def test_background_below_anchor_is_flagged_without_anchor(self, m):
        gateway = self._background_gateway()
        target = plain_target(background_rule=True)
        violations = check_sheet(gateway, target, m)
        background = sorted(v.location for v in violations if v.kind == "background")
        assert background == ["A5", "A6", "B2"]
