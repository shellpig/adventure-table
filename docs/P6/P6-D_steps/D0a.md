# D0a — 拆 `service.py`：errors／conversion／adventure_overlay／events leaf module

## Scope

純搬移，零行為改變。從 `app/domain/campaign_runtime/service.py` 搬出四組 module-level 定義到同 package 的新檔，`service.py` 改為 import；consumer 改從新檔 import；`service.py` 不保留 re-export。

| 新檔 | 搬入 | 改名 |
|---|---|---|
| `errors.py` | `CampaignRuntimeAuthorityError`、`NotFoundError`、`ConflictError`、`ActiveSessionError`、`SessionNotActiveError`、`IdempotencyConflictError`、`RevisionConflictError`、`ArchivedError`、`ValidationError`（`CampaignRuntimeError` base 仍住 `payloads.py`） | 無 |
| `conversion.py` | `stored_aggregate_to_runtime_entry`、`project_runtime_aggregate`、`project_runtime_aggregates`、`stored_override_to_domain`、`_stored_to_context_domain` | `_stored_to_context_domain` → `stored_context_to_domain` |
| `adventure_overlay.py` | `_get_attached_adventure_entry_source`、`_validate_and_parse_entry_state`、`_build_adventure_entry_overlay`、`_get_adventure_entry_overlay_in_transaction`、`_list_adventure_entry_overlays_in_transaction` | 前兩者（D0b 的 override mutation 也用）與後兩者（`context.py` 用）去掉 leading underscore；`_build_adventure_entry_overlay` 只在本檔用，保留 |
| `events.py` | `_override_event_envelope`、`_runtime_entry_event_envelope`、`_context_event_envelope`、`_session_event_idempotency_key`、`_actor_identity` | 全部去掉 leading underscore |

Consumer 更新：`campaign_runtime/__init__.py`、`campaign_runtime/context.py`、`app/api/rooms/campaign_runtime.py`、`tests/test_p6b_runtime_api.py`（只改 import）。`service.py` 尾端 `__all__` 刪除（搬移後失效；package `__init__` 才是 public surface）。

## 契約與輸入

- 無新契約；`docs/P6/開發設計方針.md`「Subphase implementation boundary」P6-D 段、P6-C 派工約束 2。
- 前置：`main@10565217`。

## 驗收

- 指揮者 AST 比對：搬移前後每個函式／class 本體 `ast.dump` 相等（改名者以新名對照）。
- `pytest tests/test_p6b_*.py tests/test_p6c_*.py tests/test_code_quality_gate.py tests/test_m03_import_boundary.py`；`python -c "import app.main"`；`ruff`／unused-import 掃描；`git diff --check`。
- `service.py` 不得再定義上表任何名稱；新 leaf module 不得 import `service.py`（`context.py` 仍 import `service.py`，不得形成循環）。

## 完成紀錄

- **起始**：2026-09-21；agy 1 回合，331 秒；conversation `b348e4c5-c1f1-491b-85ed-b69bddaa787a`。
- **交付**：`errors.py`（75 行）、`conversion.py`（123）、`adventure_overlay.py`（197）、`events.py`（99）；`service.py` 2,511 → 2,099 行；改名十個（見 Scope 表）；`service.py` 尾端 `__all__` 刪除；consumer 四檔只改 import。
- **指揮者審核修正**：`service.py` 留下三個孤兒 import（`Collection`、`TableActorKind` 隨函式搬走後未清；`CampaignRuntimeConflictError` 新 import 但本檔無人用），自行刪除。
- **測試**：AST 逐函式比對 39／39 本體相等（rename 正規化後）；`import app.main` OK；P6-A／B／C 全部＋code quality＋M03 boundary：216 passed／2 skipped；unused-import 掃描乾淨；`git diff --check` 通過。
- **驗證 commit**：見步驟板。
- **未解問題／下一步**：無；接 D0b。
