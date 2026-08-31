# M02-H — Automated Status

最後更新：2026-08-31

## 狀態

**Implementation in progress / automated gate pending.**

本分支完成 M02-G 留下的 structured system-message contract 缺口，並準備進入 M02-H full regression。M02-H 尚未 closeout；`實作規格.md` H.7 要求的真人 browser smoke 在完成前仍是獨立人工 gate。

## 本分支已完成

- `BuilderIssue` 新增 `message_params`。
- `BuilderChoice` / `BuilderChoiceOption` 新增 `disabled_reason_code` 與 `disabled_reason_params`。
- Multiclass prerequisite 由語言中立 ability / minimum-score 結構表示；content identity 使用 StableKey（例如 `class_ref`）。
- Feat prerequisite 由語言中立 ability / minimum-score 結構表示；Feat identity 使用 `feat_ref` StableKey。
- Nested choice、ASI prerequisite / cap / branch guard 使用 stable disabled-reason code。
- Compiler 的 effective-ability 第二次 eligibility pass 會同步重算 reason code + params，不只覆寫英文 prose。
- Frontend formatter 直接消費 structured params，繁中 / English 各自格式化，不 regex-match server 英文句子。
- `zh-TW` unknown-message fallback 仍維持純中文，不把 canonical English prose 串入 UI。
- 新增 backend / frontend contract regression。

## 尚未宣稱完成

以下項目必須由 PR CI / closeout gate 證明後才能更新為完成：

- backend full pytest。
- Alembic fresh DB / legacy migration compatibility。
- frontend TypeScript production build。
- Vitest full suite。
- Docker full stack。
- Playwright full suite / M02 locale flows。
- restart persistence。
- localization completeness gates。

另外，M02-H H.7 的真人 browser smoke 必須另行記錄結果；自動 Playwright 不代替真人 gate。

## Closeout boundary

在 automated gates 與 H.7 human gate 都通過以前：

- 不將 `PROJECT_BRIEF.md` 的下一步切到 M01-D。
- 不宣稱 M02 closeout。
- 不開始 M01-D coding。
