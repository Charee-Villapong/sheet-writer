"""設定（係数・対象シート）の定義と読み込み。

JSON 形式は ``config.example.json`` と同形。実 ID を書いた設定ファイルは
``*.local.*`` として gitignore 対象にし、リポジトリには実値を置かない。
"""

from __future__ import annotations

import json
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


@dataclass(frozen=True)
class Target:
    spreadsheet_id: str
    tab: str
    columns: dict[str, ColumnPolicy] = field(default_factory=dict)
    background_rule: bool = False
    append_anchor_column: str | None = None


@dataclass(frozen=True)
class Config:
    measures: Measures
    targets: dict[str, Target]


def load_config(path: str | Path) -> Config:
    """JSON 設定ファイルを読み込む。壊れた JSON は ValueError、欠損は OSError。"""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    measures = Measures(**(raw.get("measures") or {}))
    targets: dict[str, Target] = {}
    for name, entry in (raw.get("targets") or {}).items():
        columns = {
            letter: ColumnPolicy(
                mode=policy.get("mode", "fit"),
                width_px=policy.get("width_px"),
            )
            for letter, policy in (entry.get("columns") or {}).items()
        }
        targets[name] = Target(
            spreadsheet_id=entry["spreadsheet_id"],
            tab=entry["tab"],
            columns=columns,
            background_rule=bool(entry.get("background_rule") or False),
            append_anchor_column=entry.get("append_anchor_column"),
        )
    return Config(measures=measures, targets=targets)
