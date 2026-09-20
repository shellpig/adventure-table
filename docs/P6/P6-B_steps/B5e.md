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

- 待補。
