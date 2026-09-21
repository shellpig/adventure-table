# B3b — Current Scene／Situation context 與 concurrency

## Scope

- 實作 Campaign runtime context get/update/clear；Adventure scene 與 Runtime scene 最多一個非 null，兩者皆 null 合法，Situation 可單獨存在。
- 驗證 Adventure 已 attach、Runtime scene 同 Campaign 且 kind=scene。
- expected revision + campaign mutation idempotency；active Session 成功時安全發布 `world.context_changed`，session 外不造 event。

## 契約與輸入

- 依賴 B2c；P6 設計 B.3、Events、Concurrency；測試 B.3、B.5。

## 驗收

- null/situation-only/Adventure scene/Runtime scene/互斥/clear 全覆蓋。
- 同 revision 競爭只能一方成功，失敗方無 target／mutation／event 半筆。

## 完成紀錄

- **起始**：2026-09-20；agy 兩回合實作／證據修正，conversation `417f589a-e084-4ee7-8985-fdc442e67848`。
- **交付**：typed Campaign Runtime Context／patch、absence virtual revision 0、首次寫入 revision 1、單調 CAS update／clear；Adventure／Runtime scene reference 驗證；management 與 active Human／AI DM get／update／clear；`world.context_changed` dm-only 安全 event、campaign mutation idempotency與跨 Session replay。
- **指揮者審核修正**：固定 clear 不刪 row以避免 ABA；要求 scene 切換必須同 patch明確清除另一 reference。首輪審核退回補正：rollback測試改成 real mutation insert後才故障、跨 Session replay先結束舊 Session再建立新 Session、補 active clear success／retry，以及 Human access session與 AI grant真實 revoke後 read／write／replay皆拒絕。
- **測試**：B3b＋B3a＋既有 P6-B／P6-A Campaign Adventure／quality gate `59 passed, 2 skipped`；Docker 專用 `adventure_table_p6b_b3b_test` 對 B3a/B3b兩條真 PostgreSQL concurrency測試 `2 passed`，測後已刪除。B3b未修改 frontend；B3a已驗證全套前端與 build。`git diff --check` 通過。
- **驗證 commit**：`5505160d`。
- **未解問題／下一步**：無；B3 完成，停在 B4 routes／stable errors／secrecy matrix 前。
