"""テスト共通の前提。

- src レイアウトのパッケージを、インストール状態に依存せず import できるようにする。
- 仕様のデフォルト Measures と、テスト用 Target を作る fixture を提供する。
"""

import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).resolve().parent.parent / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sheet_writer.config import ColumnPolicy, Measures, Target  # noqa: E402

DUMMY_SPREADSHEET_ID = "dummy-spreadsheet-id-0001"
DUMMY_TAB = "テストタブ"


@pytest.fixture
def m():
    """仕様のデフォルト係数。"""
    return Measures()


@pytest.fixture
def make_target():
    """列ポリシーを差し替えて Target を作るファクトリ。"""

    def _make(columns=None):
        if columns is None:
            columns = {"A": ColumnPolicy(mode="fit")}
        return Target(
            spreadsheet_id=DUMMY_SPREADSHEET_ID,
            tab=DUMMY_TAB,
            columns=columns,
        )

    return _make
