# M01-H Closeout Checklist

M01-H — TCE Artificer Advanced Features & Infusions closeout scope：

- [x] Known Infusions 為 immutable Build identity；`CharacterBuild.infusion_refs` 保存正式 StableKey，Builder / Review / Confirm 由 server authoritative 驗證 Known count、minimum Artificer level 與重複選擇。
- [x] Active Infusions 為 Current State；保存 inventory entry id、infusion ref、可追蹤 charge/resource 與 Armorer armor part，並驗證 Known、item eligibility、同 item 單一 infusion、同 infusion active copy與 active capacity。
- [x] Artificer Infusion progression 已資料化並由 Rules Layer derive：Lv2 4/2、Lv6 6/3、Lv10 8/4、Lv14 10/5、Lv18 12/6，其餘 level 沿 progression 維持。
- [x] TCE Infusion 已成為 first-class content kind；本 Subphase安裝 16 個 H 所需 Infusions，包含 Enhanced Defense / Weapon / Arcane Focus、Returning Weapon、Repeating Shot、Mind Sharpener、Homunculus Servant、Armor of Magical Strength、Replicate Magic Item、Boots of the Winding Path、Radiant Weapon、Repulsion Shield、Resistant Armor、Spell-Refueling Ring、Helm of Awareness、Arcane Propulsion Armor。
- [x] Infusion metadata保存 minimum level、item filter、attunement requirement、modifier metadata、charge capacity、description與 manual-effect boundary；不存在於目前 automation substrate 的 combat trigger不假裝自動執行。
- [x] Replicate Magic Item維持「Known Infusion recipe」與「referenced item identity / active inventory instance」分離；沒有因此提前導入完整 TCE Magic Item dataset。
- [x] Feature resources可追蹤 supplied Artificer limited-use能力；Flash of Genius、Armorer Defensive Field、Battle Smith Arcane Jolt與 Spell-Storing Item capacity由既有 Rules / resource substrate derive，recharge metadata保留但不新增 Rest transaction。
- [x] Artificer attunement capacity由 Rules Layer derive：baseline 3、Artificer 10 → 4、14 → 5、18 → 6；Magic Item Savant等 restriction bypass metadata保留供未來 Attunement validator使用。
- [x] Armorer Guardian / Infiltrator為 live `feature_modes` state；可在 Character Sheet切換且不建立 Build Version，reload後仍保留目前 Armor Model。
- [x] Armor Modifications的 extra infusion capacity / armor-part boundary已有結構化表示；不靠 Frontend hardcode class level。
- [x] Spell-Storing Item保存 target Inventory item、stored spell ref與 remaining uses，並驗證 Artificer spell list、spell level / action eligibility及 capacity；actual cast resolution仍為 manual。
- [x] Alchemist / Armorer / Artillerist / Battle Smith runtime boundary明確；可持久化的 mode/resource/metadata進既有 Build/State，Experimental Elixir效果、Armorer weapon effects、Eldritch Cannon與Steel Defender combat execution不提前建立 P4 Combat substrate。
- [x] Build Edit / Level Up reconciliation不 silent delete live state；Known Infusion被移除但仍 active時形成 blocking conflict，capacity變動保留已使用／剩餘語意。
- [x] Existing Artificer Level Up對H以前／H以後 Build均有 migration/preservation路徑；歷史 Known Infusion selection不會因新H eligibility被錯誤重新判定為 invalid，真正新增的 Known choices仍只開放在target-level namespace。
- [x] Character Review / Character Sheet可清楚顯示 Known Infusions、Active Infusions / capacity、tracked resources、attunement capacity、Armor Model、Spell-Storing Item與manual-effect提示。
- [x] 新增／首次 expose的 rules presentation遵守M02永久 localization規則；TCE Infusion / Artificer相關 `zh-TW` / `en` presentation與 localization regression均通過。

## Verification Evidence

2026-09-01 最終 code驗證，分支 `m01-h-artificer-advanced-features`，受測 HEAD `4225fb02b49a9b8f00fe68352d45b5b3274ea7b0`。

```text
GitHub Actions — M01-H Non-E2E Regression #5
Run: 33493402806

TCE installed reference audit
MISSING_TCE_REFS []

Backend pytest
385 passed, 1 warning in 88.02s

Localization authoring unit tests
Ran 13 tests
OK

Fresh SQLite migration
alembic upgrade head
passed through 0006_character_archive

Frontend Vitest
15 test files passed
76 tests passed

TypeScript / Vite
npm run build
passed

Docker Compose
compose-config job
passed

GitHub Actions — M01-H Full-Stack E2E #4
Run: 33493402786

Clean Docker full stack
PostgreSQL + server migration/startup + Vite web + readiness
passed

Deterministic P0 + M01-H Armorer fixtures
passed

Complete Playwright suite
54 passed (4.9m)

Cleanup
docker compose down -v --remove-orphans
passed

Playwright artifact
m01h-playwright-results
Artifact ID: 9794913218
```

Full-Stack E2E的H-specific browser smoke實際驗證：

- Lv3 Armorer顯示 Known Infusions `4 / 4`。
- active Enhanced Defense顯示 Active capacity `1 / 2`。
- Deactivate後 API與UI均為 `0 / 2`。
- sparse `active_infusions` state patch不會清掉其他Current State欄位。
- Armor Model可由 Guardian切到Infiltrator，API立即反映。
- reload後 Active Infusions與Armor Model均維持最新Current State。

Closeout前 full-suite E2E曾抓到一個真 regression：M01-G既有 Artificer Lv2 → Lv3 Level Up的歷史 `level:2:artificer:infusions-known` selection，會被H的新eligibility重新當成目前可編輯選項驗證而阻塞Review。修正後：

- 歷史Known Infusions由authoritative base Build保留。
- Level Up真正新增／migration choice仍使用target-level namespace，不開放改寫歷史Build choice。
- 新增 `test_m01h_level_up_infusion_history.py` regression coverage。
- 既有 `m01g-artificer.spec.ts` 的Lv2 → Lv3 real-backend E2E重新全綠，形成跨Subphase第二層驗證。

H browser smoke第一次失敗另定位為測試fixture缺少Armorer Armor Model feature identity，不是state PATCH副作用。修正fixture後，同一完整E2E證明Deactivate Infusion不會清除 `feature_modes`，Armor Model可繼續切換並reload persistence。

唯一backend warning是FastAPI TestClient載入時的Starlette `httpx` deprecation warning；GitHub hosted runner另有Actions Node 20 runtime deprecation提示。兩者均未影響產品測試結果或M01-H correctness。

## Static Review

Closeout前重新檢查 `main...m01-h-artificer-advanced-features` diff：

- Build / Current State boundary維持一致；Known Infusions進Build，Active Infusions / Armor Model / Spell-Storing Item進State。
- legality與capacity由server Rules Layer驗證；Frontend僅呈現與送出state intent，沒有複製Artificer level table作為authoritative rule。
- Existing Character versioning仍走P1-G既有immutable Build workflow；H沒有建立Artificer-only version system。
- sparse state PATCH以既有Character State merge contract更新，不重建未提供欄位。
- H新增content / presentation / localization均使用現有Content Registry與M02 localization pipeline，沒有Markdown runtime parser或第二套translation model。
- Advanced combat effects保持structured/manual，沒有偷跑Rest、Reaction、Bonus Action或P4 combat entity engine。
- `main...branch`在closeout前為ahead-only，未落後main；H改動集中在Artificer content/rules/builder/reconciliation/sheet/UI與對應tests/workflows。

未發現剩餘M01-H blocking static-review issue。

## Boundary

M01-H明確不完成：

- 正式 Rest workflow / automatic recharge transaction。
- Reaction / Bonus Action / combat trigger execution engine。
- Experimental Elixir完整random/consumption automation。
- Armorer special weapon attack execution。
- Eldritch Cannon combat entity。
- Steel Defender combat entity。
- Soul of Artifice reaction resolution。
- Magic Item crafting system。
- 完整TCE Magic Item dataset。
- generic attune / unattune workflow。

這些項目保持metadata / manual boundary，不是M01-H closeout blocker。

## Handoff

M01-H已完成並關門。下一個可開工Subphase：**M01-I — TCE Optional Class Features & Fighting Styles**。

M01-I繼續遵守M02 localization Definition of Done：新增、修改或首次 expose的user-visible system / rules content，必須在同一Subphase同步 `zh-TW` / `en`；並沿用現有generic Builder / StableKey / Content Registry，不為Optional Class Features或Fighting Styles建立第二套角色系統。
