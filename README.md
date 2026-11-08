# sheet-writer

Google スプレッドシートへの書き込みで、**見切れ防止の書式をコードの構造で担保する**ための tool と検査役（checker）。

規約（正本はスキル `spreadsheet_cutoff_prevention`）は文章のルールとして存在したが、書き手が Sheets API を直接叩くときに「思い出すかどうか」へ依存し、実際に違反（折り返し未設定・行高不足）が発生した。本 tool は書式計算・設定・検証を機械的に行い、検証が通らなければエラーで返す（黙って成功にしない）。

数値の実体（文字幅・余白・行高の係数）は本リポジトリの設定（`config.example.json` の `measures`、コード側デフォルト）に置く。スキル側は指揮と要点のみを持つ。

## 何をするか

### 書き込み tool（`append`）

行追加を受け取り、次を機械的に行う。

1. 列幅を「ヘッダー＋全データ行の最長値」から再計算して設定する（全角1文字 ≒ 11.5px、半角 ≒ 6.3px、太字は 12 / 6.6px、余白 +20px。列ごとに `fit`（1行に収める）／`wrap`（固定幅で折り返す）のモードを設定で選ぶ）。**列幅は縮めない**（現行より小さくなる計算結果は採用しない）。
2. `wrap` 列には折り返し（WRAP）を設定する。
3. 行高を折り返し後の行数から設定する（行高 = 10 + 16 × 行数 px、最小 26px。ヘッダー行は 38px）。
4. 追加行の書式（背景色・配置・数値書式）は上の行に揃える。交互色（背景色が1行ごとに切り替わる）シートでは、同パリティの行の書式を使う。
5. 書き込み後に `columnMetadata` / `rowMetadata` と値・書式を読み戻し、意図どおりでなければ `VerificationError` で失敗する。

### 検査役（`check`）

既存シートを走査し、違反を検出して報告する。

- 列幅不足（`fit` 列で必要幅 > 現在幅）
- はみ出す内容があるのに折り返しが設定されていないセル
- 行高不足（推定必要行高 > 現在の行高）

`--fix` を付けると**書式のみ**（列幅・折り返し・行高）を自動修正する。値・数式には絶対に触らない。自動修正は、対象として承認されたシート（タスク台帳など）でのみ使う。

## 設定

`config.example.json` をコピーしてローカル設定を作る（実 ID を書いた設定ファイルは `*.local.*` として gitignore 対象にする。リポジトリに実値を書かない）。

- `measures`: 幅・高さの係数（規約スキルの確定値）
- `targets.<名前>`: `spreadsheet_id` / `tab` / 列ごとのモード（`fit` または `{"mode": "wrap", "width_px": 300}`）

## 使い方

前提: Google Sheets コネクタ（`hatch_gws_cli`）が接続済みの環境で実行する。

```bash
# 行追加（値は JSON 配列で渡す。複数行は --row を繰り返す）
python -m sheet_writer.cli append \
  --config config.local.json --target task-ledger \
  --row '["11","タスク名","待ち","理由テキスト","確認方法","2026-11-15","https://example.com/issue","2026-11-08"]'

# 検査（報告のみ）
python -m sheet_writer.cli check --config config.local.json --target task-ledger

# 検査＋書式のみ自動修正（承認されたシートでのみ）
python -m sheet_writer.cli check --config config.local.json --target task-ledger --fix
```

### タスク台帳への行追加（取りまとめ用手順）

台帳「Muse のタスク台帳」への行追加は、Sheets を直接編集せず本 tool の `append` を使う。列は No. / タスク / 状態 / 止まってる理由・前提条件 / 前提の確認方法 / 期日・次回確認日 / 関連リンク / 最終更新。複数文を入れるセルは「。」ごとに改行して渡す。

## 載せ替え状況（第1波・2026-11-08 実施済み）

- interview-notes の面談一覧: ゲートウェイの行追加経路を本 tool 経由に差し替え済み（interview-notes 側コミット `0cdc7c5`）。列ポリシーは A〜C が fit、D〜F が wrap 300px。tool の場所は設定 `sheet_writer_src` で与え、未設定時は兄弟ミラー配置から導出する。実経路で試験行を1行追加し、違反ゼロを読み戻しで確認後に削除済み
- cron-watchdog の見守り cron（`cron-watchdog-check`）: 異常履歴への追記を本 tool 経由に変更し、台帳タブ更新の後に `check --fix`（書式のみ）で検査する手順へ移行済み。ローカル設定は `~/workspace/cron-watchdog-data/sheet-writer.local.json`（実 ID を含むためリポジトリ外）。異常履歴タブへの試験行追加→読み戻し確認→削除まで実地確認済み。移行前に検出された既存違反（台帳タブの行高、異常履歴の折り返し未設定）は、次回の cron 実行時に `check --fix` で自動修正される
- タスク台帳: 取りまとめの行追加は本 tool の CLI を使う（本 README の手順）。ローカル設定は `~/workspace/task-ledger-data/sheet-writer.local.json`。試験行は書かず、`check --fix` の実地確認で書式のみの自動修正が効くことを確認済み

## 注意（実地確認で判明した点）

- 値の書き込みは `USER_ENTERED` のため、日時・数値らしい文字列は Sheets 側で解釈される。不正な形式の日時文字列などは変換で化けることがあるが、その場合は書き込み後の検証が不一致を検出してエラーで返す（黙って成功にはならない）。化けた行が残ることがあるため、エラー時は対象行を確認すること
- 検査役は「内容のない行」を行高不足の対象にしない（グリッドの残り行は既定行高のままでよい）

## テスト

```bash
~/workspace/.venvs/gui-flow-tools/bin/python -m pytest
```

外部接続（`hatch_gws_cli`）はゲートウェイ層に閉じ込め、テストではモックに差し替える。
