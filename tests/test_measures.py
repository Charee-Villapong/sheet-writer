"""measures（純粋関数）の数値を仕様・規約スキルから固定する。

固定値の根拠（フォント11px・実測確定値）:
- 全角 11.5px / 半角 6.3px、太字は全角 12.0px / 半角 6.6px
- セルの余白（padding）+20px、必要幅は切り上げ
- 行高 = max(26, 10 + 16 × 行数)
- 全角/半角の判定は東アジア幅 W/F を全角、それ以外を半角とする
"""

import pytest

from sheet_writer.config import Measures
from sheet_writer.measures import (
    cell_lines,
    needed_width_px,
    row_height_px,
    text_width_px,
)


class TestTextWidthPx:
    def test_empty_string_is_zero(self, m):
        assert text_width_px("", m=m) == 0.0

    def test_halfwidth_only(self, m):
        # 3文字 × 6.3px
        assert text_width_px("abc", m=m) == pytest.approx(18.9)

    def test_fullwidth_only(self, m):
        # 3文字 × 11.5px
        assert text_width_px("あいう", m=m) == pytest.approx(34.5)

    def test_mixed_full_and_half(self, m):
        # 6.3 + 11.5
        assert text_width_px("aあ", m=m) == pytest.approx(17.8)

    def test_digits_and_symbols_are_halfwidth(self, m):
        # "1,000" は表示形のまま数える（カンマ込み5文字 × 6.3px）
        assert text_width_px("1,000", m=m) == pytest.approx(31.5)

    def test_fullwidth_latin_is_fullwidth(self, m):
        # 全角英字（U+FF21、東アジア幅 F）は全角扱い
        assert text_width_px("Ａ", m=m) == pytest.approx(11.5)

    def test_ambiguous_width_char_is_halfwidth(self, m):
        # 東アジア幅 A（ambiguous）の文字は W/F でないので半角扱い
        assert text_width_px("α", m=m) == pytest.approx(6.3)

    def test_emoji_is_fullwidth(self, m):
        # 絵文字は東アジア幅 W なので全角扱い
        assert text_width_px("😀", m=m) == pytest.approx(11.5)

    def test_bold_uses_bold_widths(self, m):
        # 太字: 半角 6.6 + 全角 12.0
        assert text_width_px("aあ", bold=True, m=m) == pytest.approx(18.6)

    def test_bold_halfwidth_only(self, m):
        assert text_width_px("abc", bold=True, m=m) == pytest.approx(19.8)

    def test_custom_measures_are_used(self):
        custom = Measures(fullwidth_px=10.0, halfwidth_px=5.0)
        assert text_width_px("aあ", m=custom) == pytest.approx(15.0)


class TestNeededWidthPx:
    def test_empty_list_is_zero(self, m):
        assert needed_width_px([], m=m) == 0

    def test_empty_string_is_padding_only(self, m):
        # 空文字でも余白 20px は必要
        assert needed_width_px([""], m=m) == 20

    def test_halfwidth_text_rounds_up(self, m):
        # 18.9 + 20 = 38.9 → 切り上げ 39
        assert needed_width_px(["abc"], m=m) == 39

    def test_fullwidth_text_rounds_up(self, m):
        # 34.5 + 20 = 54.5 → 切り上げ 55
        assert needed_width_px(["あいう"], m=m) == 55

    def test_takes_max_over_texts(self, m):
        # "ab" = 32.6 → 33、"あ" = 31.5 → 32。最大は前者
        assert needed_width_px(["ab", "あ"], m=m) == 33

    def test_newline_segments_are_measured_separately(self, m):
        # セグメント最大は "あいうえお" = 57.5。57.5 + 20 = 77.5 → 78
        assert needed_width_px(["ab\nあいうえお"], m=m) == 78

    def test_bold_header_measurement(self, m):
        # ヘッダーは太字で計測: 12.0 + 20 = 32
        assert needed_width_px(["あ"], bold=True, m=m) == 32

    def test_long_fullwidth_text(self, m):
        # 20文字 × 11.5 + 20 = 250（ちょうど割り切れる場合はその値）
        assert needed_width_px(["あ" * 20], m=m) == 250

    def test_returns_int(self, m):
        assert isinstance(needed_width_px(["abc"], m=m), int)


class TestCellLines:
    def test_empty_string_is_one_line(self, m):
        assert cell_lines("", 100, m=m) == 1

    def test_short_text_is_one_line(self, m):
        assert cell_lines("abc", 100, m=m) == 1

    def test_wrapping_text(self, m):
        # 10文字 = 115px、有効幅 100-20=80px → ceil(115/80) = 2行
        assert cell_lines("あ" * 10, 100, m=m) == 2

    def test_explicit_newlines_add_up(self, m):
        # 1行 + 2行 = 3行
        assert cell_lines("abc\n" + "あ" * 10, 100, m=m) == 3

    def test_empty_segment_counts_as_one_line(self, m):
        assert cell_lines("a\n\nb", 100, m=m) == 3

    def test_exact_fit_is_one_line(self):
        # カスタム係数で割り切れるケース: 文字幅 80px = 有効幅 80px → 1行
        custom = Measures(fullwidth_px=10.0, halfwidth_px=5.0, padding_px=20)
        assert cell_lines("あ" * 8, 100, m=custom) == 1
        # 1文字増えると 90px > 80px → 2行
        assert cell_lines("あ" * 9, 100, m=custom) == 2

    def test_bold_text_wraps_earlier(self, m):
        # 有効幅 80px に対し、通常幅 77.5px は 1 行に収まるが
        # 太字幅 81px は収まらず 2 行になる（太字係数が効く境界ケース）
        text = "あ" * 4 + "a" * 5
        assert cell_lines(text, 100, m=m) == 1
        assert cell_lines(text, 100, bold=True, m=m) == 2


class TestRowHeightPx:
    @pytest.mark.parametrize(
        "lines,expected",
        [
            (0, 26),  # 最小値が効く
            (1, 26),  # 標準のデータ行
            (2, 42),
            (3, 58),
            (4, 74),
            (5, 90),
        ],
    )
    def test_height_formula(self, m, lines, expected):
        # 行高 = max(26, 10 + 16 × 行数)
        assert row_height_px(lines, m) == expected

    def test_header_height_measure_is_separate(self, m):
        # ヘッダー行 38px は Measures 側の値であり、行高式の結果ではない
        assert m.header_height_px == 38
        assert row_height_px(1, m) == 26

    def test_custom_measures_are_used(self):
        custom = Measures(row_base_px=20, line_height_px=10, min_row_height_px=30)
        assert row_height_px(1, custom) == 30
        assert row_height_px(3, custom) == 50
