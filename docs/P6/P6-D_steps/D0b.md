# D0b — 拆 `service.py`：entry／override／context mutation module

## Scope

純搬移，零行為改變。承 D0a，把 transaction-bound mutation 函式搬到三個新檔；`service.py` 只留 `CampaignRuntimeService`（`__init__`、authority helper、兩個 orchestrator、management／active mutation wrapper、read method）。

| 新檔 | 搬入 | 改名 |
|---|---|---|
| `entry_mutations.py` | `validate_mutation_identity`、`_require_management_authority`、`_validate_idempotency_key`、`_validate_entry_references`、`_prepare_create_entry`、`_execute_create_in_transaction`、`_execute_update_in_transaction`、`_execute_archive_in_transaction` | `service.py` 仍呼叫者去掉 leading underscore：`require_management_authority`、`validate_idempotency_key`、`execute_create_entry_in_transaction`、`execute_update_entry_in_transaction`、`execute_archive_entry_in_transaction`；`_validate_entry_references`、`_prepare_create_entry` 只在本檔用，保留 |
| `override_mutations.py` | `_execute_create_override_in_transaction`、`_execute_update_override_in_transaction`、`_execute_clear_override_in_transaction` | 去掉 leading underscore |
| `context_mutations.py` | `_validate_context_references`、`_execute_update_context_in_transaction`、`_execute_clear_context_in_transaction` | 後兩者去掉 leading underscore；`_validate_context_references` 只在本檔用，保留 |

三個 mutation module 只依賴 D0a 的 leaf module 與 persistence，不得 import `service.py`。`campaign_runtime/__init__.py` 的 `validate_mutation_identity` 改從 `entry_mutations` import。

## 契約與輸入

- 無新契約。前置：D0a 已 commit。

## 驗收

- 同 D0a：AST 逐函式比對、P6-B／P6-C 全部 pytest、code quality gate、M03 boundary、`import app.main`、unused-import 掃描、`git diff --check`。
- `service.py` 只剩 `CampaignRuntimeService` 一個 class 與 import／`T = TypeVar`。

## 完成紀錄

- **起始**：2026-09-21；agy 1 回合，298 秒；conversation `22f6a3aa-e4be-46d8-bc20-c2efb8862cde`。
- **交付**：`entry_mutations.py`（492 行）、`override_mutations.py`（260）、`context_mutations.py`（232）；`service.py` 2,099 → 1,242 行，只剩 import、`T = TypeVar` 與 `CampaignRuntimeService`；改名十個（見 Scope 表）；`__init__.py` 的 `validate_mutation_identity` 改從 `entry_mutations` import。三個 mutation module 只依賴 D0a leaf module／schemas／persistence，無循環。
- **指揮者審核修正**：無。
- **測試**：AST 逐函式比對 39／39 本體相等（累計 D0a＋D0b）；`import app.main` OK；P6-A／B／C 全部＋code quality＋M03 boundary：216 passed／2 skipped；unused-import 掃描乾淨；`git diff --check` 通過；全套 backend pytest 2,101 passed／74 skipped／0 failed。
- **驗證 commit**：見步驟板。
- **未解問題／下一步**：D0 完成。`service.py` 仍 1,242 行，主因 16 個 management／active wrapper 各約 40 行樣板；P6-D `CampaignWorldService` 若能以 intent 表驅動包裝，可再壓縮，但不在 D0 範圍。
