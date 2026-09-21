# B5e — Player Journal public／own-character projection

## Scope

- Session Player Journal 唯讀呈現 public Runtime Quest/Fact 與自己 active Character knowledge。
- 不直接讀 Adventure Definition；不呈現 dm_only、dm_notes、other-character knowledge 或秘密事件 payload。
- controller handoff/reconnect 後 projection 跟 Character identity，不跟 Seat display name；無 active Character 時只顯示 public。

## 契約與輸入

- 依賴 B5a/B4；P6 共用 secrecy、B.4 Knowledge、REST/UI surface。

## 驗收

- component/API tests 覆蓋 DM、Human Player、AI-equivalent Player projection matrix及無 active Character。
- 全 web unit、build 通過。

## 完成紀錄

- **起始**：2026-09-21；agy conversation `e0652097-633d-4116-b7b0-b6b1c7c20a44` 兩回合實作／退修，約 27 分鐘；prompt 位於 `C:/_work/AI_Work/Tools/agy-runs/agy-p6b-B5e*.prompt.txt`。
- **交付**：active Session 的 current Human Player controller 掛載唯讀 Player Journal，只呼叫 active Runtime entries endpoint；顯示 public Quest／Fact 與 Server 依目前 controlled active Character identities 投影的 character knowledge。projection key 使用 access session＋current controlled Seat ids＋active Character ids，handoff／reconnect／角色變更會重建 Journal；無 active Character 時只接受 public projection。Journal 只以既有 `world.*` cursor 觸發 refresh，不新增 polling／wait。
- **指揮者審核修正**：退修 partial DTO guard、未知額外欄位放行、無 active Character 時僅 UI 隱藏 character entry、render 階段 setState、raw Character id fallback與測試用 re-export；改為精確十欄 Player DTO 白名單、kind／state discriminant／正整數 revision 驗證及無角色 character projection 整批拒絕。unsafe／authority projection 會清除 Journal並 invalidate舊 load；generic refresh error保留 last-good selection。另修正 authority failure invalidation後 loading未關閉的 lifecycle 問題。
- **測試**（驗證 commit `0a52b93d`）：`npm test -- --run` → 100 files／718 tests passed；指揮者最後修正後 focused Journal＋Session → 2 files／60 tests passed；`npm run build` → passed；`..\..\.venv\Scripts\python.exe -m pytest tests/test_code_quality_gate.py -q -n 0` → 2 passed；`git diff --check` 通過。既有 Vite dynamic-import／chunk-size warning 不影響輸出；browser E2E 依步驟留在 B6。
- **未解問題／下一步**：B5e 無未解；下一步 B6 執行 P6-B browser E2E、完整 gate、closeout 與合併流程。
