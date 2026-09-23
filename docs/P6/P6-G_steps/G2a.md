# G2a — Adventure journey：Adventure 至 Stage

## Scope

- 新增可單跑的 Adventure-driven browser journey：以既有 manual／Importer authoring 建 Adventure、finalize、attach Campaign、選 Current Scene、將 Adventure／Runtime image 設 Stage。
- UI／API 證明 Adventure baseline 與 Campaign Runtime 分開；Player 只看到 DM 放上的 Stage，不直讀 Adventure 或 secret asset。
- Explore／Check／Combat／write-back／next Session 留 G2b。

## 契約與驗收

- 規格 P6-G G.2；測試指南 G.2 前半、G.5。參考 `p6a-adventures.spec.ts`、`p6d-stage-and-review.spec.ts`、`p6f-import-review.spec.ts`。
- 新 spec 單跑通過；原 P6-A／D／F 相關 E2E 與 unit／build 通過。

## 完成紀錄

（待填）
