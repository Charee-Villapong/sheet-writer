"""設定（係数・対象シート）の定義と読み込み。

JSON 形式は ``config.example.json`` と同形。実 ID を書いた設定ファイルは
``*.local.*`` として gitignore 対象にし、リポジトリには実値を置かない。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Measures:
    """見切れ防止の計測係数（規約スキルの実測確定値がデフォルト）。"""

    fullwidth_px: float = 11.5
    halfwidth_px: float = 6.3
    bold_fullwidth_px: float = 12.0
    bold_halfwidth_px: float = 6.6
    padding_px: int = 20
    row_base_px: int = 10
    line_height_px: int = 16
    min_row_height_px: int = 26
    header_height_px: int = 38
    default_wrap_width_px: int = 300


@dataclass(frozen=True)
class ColumnPolicy:
    """列ごとの方針。``fit`` は1行に収める幅まで拡大、``wrap`` は固定幅で折り返す。"""

    mode: str = "fit"
    width_px: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in ("fit", "wrap"):
            raise ValueError(f"unknown column mode: {self.mode}")


#: vertical_alignment ルールで許す値（Sheets API の列挙値）
VERTICAL_ALIGNMENTS = ("TOP", "MIDDLE", "BOTTOM")


@dataclass(frozen=True)
class Target:
    spreadsheet_id: str
    tab: str
    columns: dict[str, ColumnPolicy] = field(default_factory=dict)
    background_rule: bool = False
    append_anchor_column: str | None = None
    checkbox_columns: tuple[str, ...] = ()
    vertical_alignment: str | None = None

    def __post_init__(self) -> None:
        alignment = self.vertical_alignment
        if alignment is not None and alignment not in VERTICAL_ALIGNMENTS:
            raise ValueError(
                "vertical_alignment は TOP / MIDDLE / BOTTOM のいずれか"
                f"である必要があります: {alignment!r}"
            )
        anchor = self.append_anchor_column
        if anchor is not None and (
            not isinstance(anchor, str) or re.fullmatch(r"[A-Z]+", anchor) is None
        ):
            raise ValueError(
                f"append_anchor_column は大文字の列名である必要があります: {anchor!r}"
            )
        cols = self.checkbox_columns
        if not isinstance(cols, (list, tuple)) or any(
            not isinstance(col, str) or re.fullmatch(r"[A-Z]+", col) is None
            for col in cols
        ):
            raise ValueError(
                "checkbox_columns は大文字の列名の並びである必要があります: "
                f"{cols!r}"
            )
        object.__setattr__(self, "checkbox_columns", tuple(cols))


@dataclass(frozen=True)
class Config:
    measures: Measures
    targets: dict[str, Target]


def load_config(path: str | Path) -> Config:
    """JSON 設定ファイルを読み込む。壊れた JSON は ValueError、欠損は OSError。

    設定の不備（必須キーの欠落・未知のキー・値の型の誤り）は KeyError /
    TypeError を漏らさず ValueError に包んで送出する。
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    try:
        if not isinstance(raw, dict):
            raise ValueError("設定の最上位は JSON オブジェクトである必要があります")
        measures_raw = raw.get("measures") or {}
        if not isinstance(measures_raw, dict):
            raise ValueError("measures は JSON オブジェクトである必要があります")
        measures = Measures(**measures_raw)
        targets_raw = raw.get("targets") or {}
        if not isinstance(targets_raw, dict):
            raise ValueError("targets は JSON オブジェクトである必要があります")
        targets: dict[str, Target] = {}
        known_target_keys = {
            "spreadsheet_id",
            "tab",
            "columns",
            "background_rule",
            "append_anchor_column",
            "checkbox_columns",
            "vertical_alignment",
        }
        for name, entry in targets_raw.items():
            if not isinstance(entry, dict):
                raise ValueError(
                    f"ターゲット {name} は JSON オブジェクトである必要があります"
                )
            unknown_keys = set(entry) - known_target_keys
            if unknown_keys:
                raise ValueError(
                    f"ターゲット {name} に未知のキーがあります: "
                    f"{', '.join(sorted(unknown_keys))}"
                )
            background_rule = entry.get("background_rule", False)
            if not isinstance(background_rule, bool):
                raise ValueError(
                    f"ターゲット {name} の background_rule は"
                    " 真偽値である必要があります"
                )
            checkbox_columns = entry.get("checkbox_columns", [])
            if not isinstance(checkbox_columns, list):
                raise ValueError(
                    f"ターゲット {name} の checkbox_columns は"
                    " 列名の配列である必要があります"
                )
            vertical_alignment = entry.get("vertical_alignment")
            if vertical_alignment is not None and (
                not isinstance(vertical_alignment, str)
                or vertical_alignment not in VERTICAL_ALIGNMENTS
            ):
                raise ValueError(
                    f"ターゲット {name} の vertical_alignment は"
                    " TOP / MIDDLE / BOTTOM のいずれかである必要があります"
                )
            columns_raw = entry.get("columns") or {}
            if not isinstance(columns_raw, dict):
                raise ValueError(
                    f"ターゲット {name} の columns は"
                    " JSON オブジェクトである必要があります"
                )
            columns: dict[str, ColumnPolicy] = {}
            for letter, policy in columns_raw.items():
                if not isinstance(policy, dict):
                    raise ValueError(
                        f"ターゲット {name} の列 {letter} の設定は"
                        " JSON オブジェクトである必要があります"
                    )
                columns[letter] = ColumnPolicy(
                    mode=policy.get("mode", "fit"),
                    width_px=policy.get("width_px"),
                )
            targets[name] = Target(
                spreadsheet_id=entry["spreadsheet_id"],
                tab=entry["tab"],
                columns=columns,
                background_rule=background_rule,
                append_anchor_column=entry.get("append_anchor_column"),
                checkbox_columns=tuple(checkbox_columns),
                vertical_alignment=vertical_alignment,
            )
    except ValueError:
        raise
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"設定が不正です: {exc}") from exc
    return Config(measures=measures, targets=targets)
