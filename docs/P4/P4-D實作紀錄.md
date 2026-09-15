# P4-D — Spells, Conditions, Concentration & Reactions 實作紀錄

最後更新：2026-09-15

## 目標與邊界

本紀錄對齊 `實作規格.md`、`開發設計方針.md`、`測試指南.md` 的 P4-D / D.0～D.5 驗收條件。

P4-D 只完成 Quick Combat 的規則／持久化 foundation；REST / realtime / MCP / Human UI surface 留在 P4-E。不得為 Quick Combat 建立 geometry、condition scripting DSL、Monster 假 Character class，或第二套 Character Current State。

## D.0 Shared Character State

- `app.domain.character.schemas.CharacterState` 是 PC runtime truth；P4-D 以 additive/default-safe 欄位擴充它。
- 新增 shared state：Concentration、Exhaustion level、Death Save state、persistent Temporary Effects。
- 新欄位不得保存 Room / Campaign / Session / Combat row identity。
- Character JSON external `schema_version="1"` 維持不變；舊 v1 / legacy fixture 缺欄位時使用 backward-compatible defaults。
- `character_states.state_payload` 既有 JSON + revision CAS 直接承載 additive state；不為這些欄位新增 Web-only combat table。
- Combat End 不自動清除仍合法的 Concentration / persistent effects。

## D.1 Spell source / resource

- Character spell source沿用 `CharacterBuild.spellcasting_profiles`、`spell_access_entries`、`spell_resource_pools` 與 `CharacterState`。
- normal multiclass slots 使用 `state.spell_slots`；Pact Magic 使用既有 `pact_resource_key(...)` 來源感知 counter，兩池不得合併。
- Monster casting以 `StoredMonsterInstance.rules_snapshot` 的 normalized stat-block casting資料與 instance live `resources` 為 authoritative source；不得偽造 Character class source。
- cast 先完整 validate，再一次扣 resource；invalid request與 duplicate command不得重扣。
- spell attack / save / damage / healing / upcast / concentration走同一 resolver，damage保留 typed parts以套用既有 affinity pipeline。

## D.2 AoE

- Quick Combat不計 radius / coordinates / cells。
- acting user提出 target identities；需要空間判定時由 durable Combat adjudication確認 affected set。
- confirmed target list才進 group saves / per-target resolve。
- command id / state transition guard確保 retry不重扣 slot、不重套 damage。

## D.3 Conditions / Effects / Exhaustion

- 完整 2014 conditions：Blinded、Charmed、Deafened、Frightened、Grappled、Incapacitated、Invisible、Paralyzed、Petrified、Poisoned、Prone、Restrained、Stunned、Unconscious。
- Exhaustion 1～6 累積語意與 recovery/reset。
- mechanical contributions使用 typed flags/modifiers；需要來源可見性、距離等 contextual rule的項目保留 conditional flag，不由 Quick Combat猜 geometry。
- Temporary Effect支援 advantage/disadvantage、+N、AC、Speed、Attack、Save、Check、Damage contribution與 deterministic expiry；未知 note不自動推導規則。

## D.4 Concentration

- 同一 creature同時最多一個 concentration；開始 B會結束 A並移除 A-linked effects。
- semantic damage完成後，若實際 HP/Temp HP damage > 0 且正在 concentrating，建立 CON save，DC=`max(10, floor(damage / 2))`。
- failed save結束 concentration並清 linked effects；pass保留。
- Combat End本身不清 concentration。

## D.5 Reaction / Ready / OA / Legendary

- ReactionRequest為 durable pending state，具有 trigger、source、eligible entries、optional target、safe/secret payload、status與 session provenance。
- accept/decline/resolve/cancel/timeout皆有 single-transition / idempotency guard；accepted reaction必須驗 controller/eligibility/reaction availability並消耗 reaction。
- turn start刷新 reaction。
- Quick OA只可由 DM trigger / adjudication建立，不從 movement prose自動推 geometry。
- Ready使用同一 reaction substrate；自由文字 trigger由 DM判斷；到 owner下一 turn仍未觸發即 expire，不退款已消耗的原 action/resource。
- Lightweight Legendary Action只提供 timing/resource representation：其他 creature turn end可用、扣 durable resource；複雜/lair timing仍交 DM adjudication。

## 測試關門條件

P4-D closeout必須同時通過：

1. D.0 shared Character State backward compatibility / persistence / JSON v1 roundtrip。
2. D.1 prepared、known、multiclass ability、normal/Pact分池、upcast、duplicate resource spend。
3. D.2 proposed targets → DM-confirmed AoE → multi-save/per-target outcome，且沒有 fake geometry。
4. D.3 concentration replacement / damage save / fail cleanup / Combat End preserve。
5. D.4 全 2014 condition registry + mechanical focused tests + Exhaustion。
6. D.5 durable ReactionRequest reload、accept/decline、spent、duplicate、DM-triggered OA、Ready expiry、legendary timing/resource。
7. P4-C / P4-B regression、full backend pytest、PostgreSQL migration/regression、frontend test/build、compose config 全綠。

第一版 P4-D helper commits只算 foundation；本紀錄之後的 commit才作為 D.0～D.5 closeout evidence。