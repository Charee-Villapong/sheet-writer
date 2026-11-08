"""テスト基盤（FakeGateway）: フィールドマスク意味論の一般化を固定する。

実 Sheets API の repeatCell は、fields（フィールドマスク）に挙がって
いるのに cell に無いフィールドを削除する。従来の Fake はこの削除を
背景色（backgroundColor / backgroundColorStyle）だけにモデル化して
いたが、anchor（update）経路では書込先セルのあらゆる残留書式を
マスクで消す必要があるため、削除意味論を全キーへ一般化する。

固定する意味論:
- マスクにあって cell に無いトップレベルキー（numberFormat 等）は
  セルから削除される。
- マスクに無いキーは保持される。
- マスクにあり cell にもあるキーは、削除でなく値の適用になる。
- textFormat のサブキー（textFormat.bold 等）も同じ規則で削除される。
- 背景色の削除は従来どおり（test_background_rule.py で担保済み）。
"""

from fake_gateway import DUMMY_SHEET_ID, FakeGateway, make_state

PALE = {"red": 0.9, "green": 0.95, "blue": 0.9}
DATE_FORMAT = {"type": "DATE", "pattern": "yyyy/mm/dd"}


def gateway_with_cell(cell_format):
    state = make_state(
        [["名前"], ["abc"]],
        column_widths=[100],
        row_heights=[38, 26],
        cell_formats=[[{}], [cell_format]],
    )
    return FakeGateway(state)


def repeat_request(fmt, fields):
    """2行目・1列目（インデックス 1, 0）への repeatCell リクエスト。"""
    return {
        "repeatCell": {
            "range": {
                "sheetId": DUMMY_SHEET_ID,
                "startRowIndex": 1,
                "endRowIndex": 2,
                "startColumnIndex": 0,
                "endColumnIndex": 1,
            },
            "cell": {"userEnteredFormat": fmt},
            "fields": fields,
        }
    }


class TestGeneralizedFieldMask:
    def test_masked_but_absent_number_format_is_deleted(self):
        gateway = gateway_with_cell(
            {"numberFormat": DATE_FORMAT, "verticalAlignment": "MIDDLE"}
        )
        gateway.batch_update(
            "dummy-spreadsheet-id-0001",
            [repeat_request({}, "userEnteredFormat.numberFormat")],
        )
        # マスクに無い verticalAlignment は保持される
        assert gateway.state.cell_formats[1][0] == {"verticalAlignment": "MIDDLE"}

    def test_key_not_in_mask_is_preserved(self):
        gateway = gateway_with_cell(
            {"numberFormat": DATE_FORMAT, "backgroundColor": PALE}
        )
        gateway.batch_update(
            "dummy-spreadsheet-id-0001",
            [repeat_request({}, "userEnteredFormat.backgroundColor")],
        )
        assert gateway.state.cell_formats[1][0] == {"numberFormat": DATE_FORMAT}

    def test_masked_key_present_in_cell_is_applied_not_deleted(self):
        gateway = gateway_with_cell({"horizontalAlignment": "CENTER"})
        gateway.batch_update(
            "dummy-spreadsheet-id-0001",
            [
                repeat_request(
                    {"numberFormat": DATE_FORMAT},
                    "userEnteredFormat.numberFormat",
                )
            ],
        )
        assert gateway.state.cell_formats[1][0] == {
            "horizontalAlignment": "CENTER",
            "numberFormat": DATE_FORMAT,
        }

    def test_masked_text_format_subkey_is_deleted(self):
        gateway = gateway_with_cell({"textFormat": {"bold": True, "italic": True}})
        gateway.batch_update(
            "dummy-spreadsheet-id-0001",
            [
                repeat_request(
                    {"textFormat": {"italic": True}},
                    "userEnteredFormat.textFormat.bold,"
                    "userEnteredFormat.textFormat.italic",
                )
            ],
        )
        assert gateway.state.cell_formats[1][0] == {"textFormat": {"italic": True}}
