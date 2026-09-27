# P5-D — AoE & Tactical Spell Geometry · Closeout

- **關門日期**：2026-09-27
- **Branch**：`feat/p5d-aoe-tactical-spell-geometry`（自 `main@7eeab560`）
- **Worker**：Muse（D1，`40741554`，在自己環境跑綠後推送）、指揮者（驗收、補測試、關門）

## 範圍

Backend only。`app/domain/spatial/aoe.py`：由 spell content `area_of_effect` normalize 成 circle／cone／line／square，cell-center 規則＋shared 5/10 距離算 affected cells 與 candidate combatants（多格 creature 任一 occupied cell 被涵蓋即列入）。Tactical Character AoE：preview route（actor-projected）、提案要求 template＋`board_revision`，Server 重算 candidate 寫入既有 P4 AoE 提案，DM confirm 可增刪 target，既有 save／damage resolution 只跑一次；`board_revision` 過期 409 `combat_board_stale`。Monster AoE 無結構化 area 時維持 DM 裁定。Quick AoE 行為不變。前端 renderer、template UI、MCP tool 屬 P5-F。

## 驗收對應

| 契約（測試指南） | 證據（`apps/server/tests/`） |
|---|---|
| D.1 Shape golden fixtures | `test_p5d_aoe_geometry.py::test_golden_fixture_round_trip`（`fixtures/p5d_aoe_golden.json`，P5-F renderer 重用）、`::test_circle_radius_boundary_inclusive`、`::test_circle_odd_radius_boundary`、`::test_cone_wedge_boundary`、`::test_cone_length_boundary`、`::test_line_half_width_boundary_inclusive`、`::test_line_length_boundary`、`::test_square_quadrants`、`::test_normalize_area_of_effect` |
| D.2 Multi-cell targets | `test_p5d_aoe_geometry.py::test_resolve_aoe_candidates_multi_cell_creature` |
| D.3 Preview／canonical parity | `test_p5d_aoe_tactical.py::test_preview_returns_cells_candidates_and_revision`、`::test_propose_recomputes_candidates_and_ignores_client_targets`、`::test_stale_revision_conflicts_with_zero_side_effects`、`::test_api_maps_board_stale_to_409` |
| D.4 Spell integration／idempotency | `test_p5d_aoe_tactical.py::test_resolve_happens_once_and_consumes_action`、`::test_duplicate_propose_and_resolve_with_same_key_apply_once` |
| D.5 Hidden AoE | `test_p5d_aoe_tactical.py::test_preview_hides_hidden_candidates_from_player_but_not_dm`、`::test_hidden_caster_entry_id_redacted_from_player_event`、`::test_tactical_event_projection_strips_hidden_targets` |
| D.6 Obstruction adjudication | `test_p5d_aoe_tactical.py::test_dm_confirm_can_add_and_remove_tactical_targets`、`::test_resolve_happens_once_and_consumes_action` |
| Quick 不變 | `::test_quick_propose_still_rejects_empty_targets`、`::test_confirm_aoe_still_rejects_subset_violation_for_quick`、既有 `test_p4*` 全綠 |

## 關門 gate

- 全套 backend pytest（`P4_POSTGRES_URL=…/adventure_table_p4`，`40741554`）：2,962 passed、39 skipped、0 failed。補測試後 `test_p5d_aoe_tactical.py` 全綠。
- `docker compose config`：通過（未改 compose）。未動 `apps/web`，不需 `npm test`／`npm run build`。
- **全套 Docker E2E**（三個 project 分開呼叫，`40741554`）：`parallel` 102 passed／3 skipped／2 failed（`p1f-character-creation`、`m01i-optional-features`）、`baseline-room` 30 passed／1 skipped、`serial-restart` 2 passed。`m01i` 以 0 ms 失敗，單跑 5 passed（flake）；`p1f` 為 `main` 既有穩定失敗（見 P6-D closeout）。

## 指揮者審核修正

- D.4 只測「換 key 再 resolve 被拒」且以 `pytest.raises(Exception)` 斷言，未證明同 key 重送不重複效果——補 `test_duplicate_propose_and_resolve_with_same_key_apply_once`（propose 重送同 action、不多寫 action／event；resolve 重送 HP 不再變、不多寫 event）。程式本身已正確，無需修改。

## 已知限制

- Line 寬度固定 5 ft（content 無寬度資料）；寬度不同的 line（例如 10 ft）交 DM 在 confirm 時增刪。
- Obstruction 不自動傳播：牆後的格子仍會列入 candidate，交 DM confirm 調整（契約 §8.4 刻意不做 generic simulator）。
- Cone／line 的方向為任意角度（`aim` 點），前端 P5-F 需以同一 golden fixture 對齊 renderer。
- Muse 環境的 PostgreSQL 為 16（VM 重置後 PGDG 連不上）；指揮者本機以 17 驗證。
- Muse D1 最終報告因其網站載入問題未讀取；交付以 commit 與本機驗證為準。
