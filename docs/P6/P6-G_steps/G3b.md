# G3b — Secrecy matrix、Quick／Standalone 邊界

## Scope

- 查 REST／Resume／Event／MCP／UI network 的 Player projection：Adventure entry 任何 visibility 不可直接讀、DM Notes／Runtime secret／他人 knowledge／source excerpt 不外洩。
- 驗 P6 journey 無 Tactical geometry 或 P5 import 仍可運作；M03 import boundary＋schema parity 與 PDF／DOCX Standalone package 既有證據有效。
- 如找到 leak 或邊界破壞，定位至來源 Subphase 修正，不靠 UI 隱藏。

## 契約與驗收

- 測試指南 G.5～G.7；以現有 server test／E2E coverage 做矩陣，對缺口補最小測試，保留拒絕零副作用證據。
- focused＋受影響 regression、`p6g` journeys、M03 boundary／schema parity 通過。

## 完成紀錄

- **執行者與日期**：2026-09-24，指揮者；先依 G.5～G.7 列 REST／Resume／Event／MCP／UI network、P5 independence、Standalone 的逐項檢查表，再對照現有 production code、test 與本輪 browser journey。
- **REST／Importer source**：`test_p6a_adventure_authoring.py`／`test_p6a_adventure_api.py` 的 Member／cross-Room 拒絕；`test_p6b_runtime_api.py` 的 Player list／item／override／context 拒絕與零副作用；G2 browser 的 Player Adventure any-visibility direct-read 404、secret asset 404；G3a restart browser 的 Importer list／draft／sources／source chunk Player 403。Player 可見 Runtime entry 只透過 server projection，`dm_notes`、`needs_review`、`provenance_json` 未送出。
- **Resume／Event／MCP**：`test_p3c_resume_projection.py` fail-closed；`test_p6b_runtime_active_service.py` event payload allowlist、`test_p6d_world_action.py` secret／character knowledge event projection；`test_p6c_context_service.py`／`test_p6c_context_search.py` 的 AI Player secret／Adventure omission 與 own-character 分界；`test_p6c_mcp_tools.py`、`test_p6d_mcp_tools.py`、`test_p6f_mcp_tools.py` 的 role／grant gate。G2 browser 新增 **實際 Player `/sessions/active` Resume network JSON** 斷言，不含 secret entry／DM Note／override note；同場 Event Player projection 不含 DM-only `world.override.created`／`world.context_changed`。
- **UI／P5／Standalone**：G1／G2 Player 頁面無 DM world control／秘密文案，Stage image 走 blob，不洩漏 source asset id；G2 Quick Combat 無 Tactical grid，P6 domain／MCP 無 P5 tactical／spatial module import。`test_m03_import_boundary.py` 與 `test_m03d_schema_parity.py` 保持綠；G branch 自 F closeout 後只改 E2E／文件，未新增 Python dependency、schema 或 Standalone package 相依。
- **測試與證據**：專案 venv 跑上述 P3／P6 secrecy、MCP、M03 boundary／schema parity 相關 13 module，**358 passed**；Docker E2E `p6g-adventure-journey.spec.ts`（含 Player Resume network inspection）**1 passed**；全套 frontend Vitest **103 files／775 tests passed**、`npm run build` 通過；`git diff --cached --check` 通過。驗證 code commit：`e1627262`。
- **未解與下一步**：本步無 secrecy／P5／Standalone blocker；G4 用真實 ChatGPT Web 與合法 AI DM grant 驗外部 AI 的 P6 context／write-back／reconnect。
