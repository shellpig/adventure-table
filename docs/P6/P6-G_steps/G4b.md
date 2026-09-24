# G4b — AI DM 即興與桌面語言指引（G4 第二次嘗試補缺）

## Scope

- G4 第二次嘗試（Session `12518d5a`）中 AI DM 已能自行發現 Adventure、設 scene、檢定與寫回，但出現兩個指引缺口（見 [G4](G4.md)「發現與處置」）：Stage／current_situation 照抄英文 Adventure 原文；Adventure 缺少達成開啟條件的遭遇時 AI 停在原地（soft-lock），未依 `規格企劃.md` 〇 第 7 條即興。
- 只補 AI guidance，不新增資料模型、不做 Adventure 完整性驗證（自由文字條件無法可靠驗證，且 Adventure 本就 optional／可不完整）。
- 契約：`開發設計方針.md`「P6-C — C.1」AI DM 發現條款新增「Adventure 是底稿不是劇本」與語言要求。

## 實作

- DM active loop（zh-TW／en）第 1 步加入「Adventure 是底稿不是劇本：沒給路徑時像真人 DM 即興（新 NPC 用 world_create_entry、敵人用 Quick Combat）」，第 6 步寫回範圍含重要即興內容，結尾加「敘事、Stage 與寫回一律用玩家使用的語言」；為守 `BRIEFING_MAX_CHARS` 精簡既有措辭（保留既有測試鎖定的關鍵字），DM active briefing 2955／3000 字。
- DM pre-session briefing 加入語言規則。`/mcp/guide`「Adventure 與世界狀態（DM）」段加入即興（含守衛 soft-lock 例子）與語言轉述規則（zh-TW／en）。

## 驗證

- `tests/test_p6g_adventure_outline.py` 擴充：DM active／pre-session briefing 雙語含即興、Quick Combat 與語言規則；guide 雙語段落含即興與語言規則。
- Focused regression（13 檔，含 M04 briefing／guide／tool description、P3-E、P4-E／F、P6-C／D／F MCP）：**280 passed**。
- 完整 backend pytest（cwd `apps/server`）：**2538 passed／78 skipped**，exit 0。前端未改動。

## 完成紀錄

- 2026-09-24 完成實作與驗證；commit 訊息標題含 `G4b`。
