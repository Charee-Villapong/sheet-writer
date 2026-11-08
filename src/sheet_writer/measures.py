"""幅・行数・行高の計測（純粋関数）。

数値は規約スキル ``spreadsheet_cutoff_prevention`` の実測確定値に基づく
（フォント 11px: 全角 11.5px / 半角 6.3px、太字は 12.0 / 6.6px、余白 +20px）。
係数の実体は :class:`sheet_writer.config.Measures` 側に置き、本モジュールは
計算だけを担う。
"""

from __future__ import annotations

import math
import unicodedata
from typing import Iterable

from sheet_writer.config import Measures

_FULLWIDTH_KINDS = ("W", "F")


def _char_width(ch: str, *, bold: bool, m: Measures) -> float:
    if unicodedata.east_asian_width(ch) in _FULLWIDTH_KINDS:
        return m.bold_fullwidth_px if bold else m.fullwidth_px
    return m.bold_halfwidth_px if bold else m.halfwidth_px


def text_width_px(text: str, *, bold: bool = False, m: Measures) -> float:
    """表示文字列の幅（px）。数値のカンマや記号も表示形のまま数える。"""
    return sum(_char_width(ch, bold=bold, m=m) for ch in text)


def needed_width_px(
    texts: Iterable[str], *, bold: bool = False, m: Measures
) -> int:
    """テキスト群を1行ずつ収めるのに必要な列幅（px、切り上げ）。

    各テキストは ``\\n`` でセグメントに割り、最大セグメント幅 + 余白で見積もる。
    空の入力では 0 を返す。
    """
    texts = list(texts)
    if not texts:
        return 0
    widest = 0.0
    for text in texts:
        for segment in text.split("\n"):
            widest = max(widest, text_width_px(segment, bold=bold, m=m))
    return math.ceil(widest + m.padding_px)


def cell_lines(
    text: str, column_width_px: float, *, bold: bool = False, m: Measures
) -> int:
    """列幅に対してセルが占める行数。空セグメントも1行として数える。"""
    usable = max(column_width_px - m.padding_px, 1)
    lines = 0
    for segment in text.split("\n"):
        width = text_width_px(segment, bold=bold, m=m)
        lines += max(1, math.ceil(width / usable))
    return lines


def row_height_px(lines: int, m: Measures) -> int:
    """行数から行高（px）を求める。``max(最小行高, 基準 + 行高単価 × 行数)``。"""
    return max(m.min_row_height_px, m.row_base_px + m.line_height_px * lines)
