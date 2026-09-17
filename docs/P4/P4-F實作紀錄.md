# P4-F — Full P4 Integration & Closeout 實作紀錄

最後更新：2026-09-17

## 目標與邊界

本紀錄對齊 `實作規格.md` P4-F（1～11）、`開發設計方針.md` §9、§10、`測試指南.md` P4-F（F.1～F.4）。P4-F 以真正可玩的完整 Quick Combat journey 驗證 P4，並收掉 P4-C／P4-D／P4-E closeout 留下、已明列歸 P4-F 的缺口。不做 P5 geometry、不建 P6 runtime、不加 Undo。

branch：`feat/p4f-full-p4-integration-closeout`（自 `main` `6ed11d24` 開出）。實作以步驟切分，每步獨立可驗證、獨立 commit；步驟由 agy worker 執行、Claude 審 diff / 跑 focused test / commit（流程見 `docs/others/conductor-handbook.md`）。每步完成後更新下表。

已拍板（2026-09-17）：`ConditionSemantics` 接進 attack / save modifier pipeline納入 P4-F（F7），排在真實 AI gate 之前的最後一個 code step，不阻塞 F.3。

## 步驟進度

| 步 | 內容 | 對應契約 | 狀態 |
|---|---|---|---|
| F1 | Monster 0 HP outcome：DM 選 dead / unconscious / surrendered / fled / other；migration `0027` 放寬 `combat_entries.status` / `monster_instances.combat_status`；REST + MCP + event | 實作規格 P4-C 10、P4-E 7、P4-F 1；規格企劃「Monster 0 HP / Combat End」 | ⬜ |
| F2 | Monster Instance bookkeeping：DM PATCH name / visibility / position_note + reveal toggles（AC / description / position note）；`MonsterRevealState` 持久化（migration `0028`）；REST + MCP + event | 實作規格 P4-E 7（部分→完整）、3 | ⬜ |
| F3 | F1 / F2 的 Session table UI：DM 卡片 outcome / visibility / reveal / position note 控制、新 entry status 標籤、Player 可見 outcome、雙語 copy、web client | 實作規格 P4-E 1、2、13 | ⬜ |
| F4 | `grappled` escape action + Character state PATCH DTO 補 `concentration` / `exhaustion_level` / `death_saves` / `temporary_effects` | P4-C / P4-D closeout 留下 | ⬜ |
| F5 | 真 PostgreSQL + server restart / reconnect：Round ≥ 2、pending save 或 reaction → restart → 狀態完整、resolve 一次不重擲 | 實作規格 P4-F 3；測試指南 F.1 | ⬜ |
| F6 | Full browser journey spec（F.2 全項：spell / save、damage / healing、condition、concentration 或 reaction、0 HP outcome、Session boundary resume、End cleanup）+ `P4 Full-Stack E2E` workflow | 實作規格 P4-F 1、2、4、5、6；測試指南 F.2 | ⬜ |
| F7 | `ConditionSemantics` 接進 attack / save modifier pipeline（advantage / disadvantage / auto-fail / adjacent crit） | P4-D closeout 留下；P4-F 已拍板納入 | ⬜ |
| F8 | 真實 ChatGPT Web Combat gate（人工，含 `wait_for_event` / reconnect continuity）+ DM proxy audit 與 secrecy 三層證據彙整 | 實作規格 P4-F 5、6、9、10；測試指南 F.3 | ⬜ |
| F9 | static review + Non-E2E / PostgreSQL / standalone boundary regression 彙整 + P4-F closeout + P4 Phase closeout | 實作規格 P4-F 7、8、11；測試指南 F.4 | ⬜ |

步驟粒度可在實作中再切；新增子步以 `F1a` 之類接續，不重編已完成項目。

## 步驟紀錄
