Adventure Table 單機版 — 繁體中文
================================

這是什麼
Adventure Table Standalone 是 Windows x64 離線角色工具，包含 Character
Workshop、創角、角色卡、升級、Version History、封存／永久刪除、繁中／英文
切換，以及角色 JSON 匯入／匯出。不包含 Room、Campaign、Session、Seat、
Combat、Timeline、AI Actor、帳號與線上同步。

啟動與關閉
執行 adventure-table.exe。程式運作期間會保留 console 視窗，並自動打開預設
瀏覽器。要停止程式，請在 console 按 Ctrl+C，或直接關閉 console 視窗。
只關閉瀏覽器分頁「不會」停止本機 server。

你的資料
預設資料庫是 adventure-table.exe 同一資料夾內的 adventure-table.sqlite3。
Launcher 會印出實際絕對路徑，Landing 頁也會顯示同一路徑。解壓新版時，只要
先把舊資料夾的 adventure-table.sqlite3 複製到新版資料夾即可沿用角色資料。
進階使用者可用 ADVENTURE_TABLE_DATABASE_PATH 覆寫位置。

匯入／匯出
Character Workshop 與 Character Sheet 都可以匯出角色；Character Workshop
可以選擇 JSON 檔或直接貼上 JSON 匯入。網頁版與單機版在 M03 使用同一份角色
交換格式。

M03 重要限制
M03 期間 Character JSON schema 仍是 UNSTABLE。這個版本匯出的 JSON，不保證
未來版本一定讀得進去；要到 P2 才會鎖定 schema。請保留原本的單機資料夾／
SQLite 檔作為可靠的原始資料。

平台
M03 目前只提供 Windows x64 portable zip，不是 installer；沒有自動更新，也
沒有 code signing。

回報問題
若啟動失敗，請附上 console 輸出、第一行顯示的 build id，以及 console 顯示的
資料庫路徑是否可寫入。
