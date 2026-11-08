"""Sheets への接続層。

実接続は Google Sheets コネクタの正規経路（``hatch_gws_cli``）に限定し、
このモジュールに閉じ込める。writer / checker は :class:`SheetsGateway`
プロトコルだけに依存し、テストではインメモリ Fake に差し替えられる。
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Protocol

CLI_PATH = "/opt/hatch/bin/hatch_gws_cli"

_STATE_FIELDS = (
    "sheets(properties(sheetId,title),"
    "data(rowMetadata,columnMetadata,"
    "rowData(values(formattedValue,userEnteredValue,userEnteredFormat))))"
)


@dataclass
class SheetState:
    """あるタブの状態スナップショット（値・寸法・セル書式）。"""

    sheet_id: int
    values: list[list[str]]
    column_widths: list[int | None]
    row_heights: list[int | None]
    cell_formats: list[list[dict]]
    entered_values: list[list[dict]] = field(default_factory=list)


class SheetsGateway(Protocol):
    def get_values(self, spreadsheet_id: str, range_a1: str) -> list[list[str]]: ...

    def append_values(
        self, spreadsheet_id: str, range_a1: str, values: list[list[str]]
    ) -> str:
        """行を追加し、updatedRange を返す。"""
        ...

    def update_values(
        self, spreadsheet_id: str, range_a1: str, values: list[list[str]]
    ) -> str:
        """指定範囲へ値を直接書き込み、updatedRange を返す。"""
        ...

    def get_state(self, spreadsheet_id: str, tab: str) -> SheetState: ...

    def batch_update(self, spreadsheet_id: str, requests: list[dict]) -> None: ...


class CliGateway:
    """``hatch_gws_cli`` を subprocess で呼ぶ SheetsGateway 実装。

    ``runner`` は subprocess.run 相当の呼び出しオブジェクトで、テストでは
    モックに差し替えられる。runner の例外（CalledProcessError 等）は
    そのまま伝播させる。
    """

    def __init__(self, runner: Callable | None = None) -> None:
        self._runner = runner if runner is not None else subprocess.run

    def _call(
        self,
        args: list[str],
        *,
        params: dict | None = None,
        body: dict | None = None,
    ) -> dict:
        cmd = [CLI_PATH, "sheets", *args]
        if params is not None:
            cmd += ["--params", json.dumps(params, ensure_ascii=False)]
        if body is not None:
            cmd += ["--json", json.dumps(body, ensure_ascii=False)]
        result = self._runner(cmd, capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        return payload if isinstance(payload, dict) else {}

    def get_values(self, spreadsheet_id: str, range_a1: str) -> list[list[str]]:
        payload = self._call(
            ["spreadsheets", "values", "get"],
            params={"spreadsheetId": spreadsheet_id, "range": range_a1},
        )
        return [list(row) for row in payload.get("values", [])]

    def append_values(
        self, spreadsheet_id: str, range_a1: str, values: list[list[str]]
    ) -> str:
        payload = self._call(
            ["spreadsheets", "values", "append"],
            params={
                "spreadsheetId": spreadsheet_id,
                "range": range_a1,
                "valueInputOption": "USER_ENTERED",
                "insertDataOption": "INSERT_ROWS",
            },
            body={"values": values},
        )
        updates = payload.get("updates", {})
        return str(updates.get("updatedRange", ""))

    def update_values(
        self, spreadsheet_id: str, range_a1: str, values: list[list[str]]
    ) -> str:
        payload = self._call(
            ["spreadsheets", "values", "update"],
            params={
                "spreadsheetId": spreadsheet_id,
                "range": range_a1,
                "valueInputOption": "USER_ENTERED",
            },
            body={"values": values},
        )
        return str(payload.get("updatedRange", ""))

    def batch_update(self, spreadsheet_id: str, requests: list[dict]) -> None:
        self._call(
            ["spreadsheets", "batchUpdate"],
            params={"spreadsheetId": spreadsheet_id},
            body={"requests": requests},
        )
        return None

    def get_state(self, spreadsheet_id: str, tab: str) -> SheetState:
        payload = self._call(
            ["spreadsheets", "get"],
            params={
                "spreadsheetId": spreadsheet_id,
                "ranges": tab,
                "fields": _STATE_FIELDS,
            },
        )
        sheet = self._pick_sheet(payload, tab)
        properties = sheet.get("properties", {})
        data_list = sheet.get("data") or []
        data = data_list[0] if data_list else {}

        row_data = data.get("rowData") or []
        row_metadata = data.get("rowMetadata") or []
        column_metadata = data.get("columnMetadata") or []

        n_cols = len(column_metadata)
        for row in row_data:
            n_cols = max(n_cols, len(row.get("values") or []))
        n_rows = max(len(row_data), len(row_metadata))

        values: list[list[str]] = []
        cell_formats: list[list[dict]] = []
        entered_values: list[list[dict]] = []
        for r in range(n_rows):
            cells = []
            if r < len(row_data):
                cells = row_data[r].get("values") or []
            value_row: list[str] = []
            format_row: list[dict] = []
            entered_row: list[dict] = []
            for c in range(n_cols):
                cell = cells[c] if c < len(cells) else {}
                value_row.append(str(cell.get("formattedValue", "")))
                format_row.append(dict(cell.get("userEnteredFormat") or {}))
                entered = cell.get("userEnteredValue")
                entered_row.append(dict(entered) if isinstance(entered, dict) else {})
            values.append(value_row)
            cell_formats.append(format_row)
            entered_values.append(entered_row)

        column_widths = [
            (entry.get("pixelSize") if isinstance(entry, dict) else None)
            for entry in column_metadata
        ]
        row_heights = [
            (
                row_metadata[r].get("pixelSize")
                if r < len(row_metadata) and isinstance(row_metadata[r], dict)
                else None
            )
            for r in range(n_rows)
        ]
        return SheetState(
            sheet_id=int(properties.get("sheetId", 0)),
            values=values,
            column_widths=column_widths,
            row_heights=row_heights,
            cell_formats=cell_formats,
            entered_values=entered_values,
        )

    @staticmethod
    def _pick_sheet(payload: dict, tab: str) -> dict:
        sheets = payload.get("sheets") or []
        for sheet in sheets:
            if sheet.get("properties", {}).get("title") == tab:
                return sheet
        raise ValueError(f"タブが見つかりません: {tab}")
