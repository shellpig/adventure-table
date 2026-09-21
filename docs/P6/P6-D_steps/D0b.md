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

（待補）
