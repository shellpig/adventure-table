# M01-G Closeout Checklist

M01-G — TCE Artificer Core closeout scope：

- [x] 新增 `tce` Content Pack，並把 `tce` 加入 default enabled content packs。
- [x] Artificer 以正式 Class identity `tce:class:artificer` 進入 Builder / Review / Confirm / Character Sheet，不建立第二套 Artificer-only Builder。
- [x] Artificer class basics 正確：d8 Hit Die、Lv1 base HP 8、later fixed HP 5、CON / INT saves、Light / Medium Armor / Shield、Simple Weapons、hand crossbow、heavy crossbow、Thieves' Tools、Tinker's Tools、choose 1 Artisan's Tools、choose 2 skills。
- [x] Optional firearm proficiency 未啟用；專案仍沒有正式 firearm equipment universe，因此沒有 dangling firearm ref 或 fake firearm proficiency。
- [x] Starting-class grants 與 multiclass grants 分離，Artificer multiclass prerequisite / grants 以 supplied data 驗證。
- [x] Lv1～20 progression 連續完整，包含 proficiency bonus、feature refs、ASI markers、cantrips known、1～5 level spell slots、Infusions Known / Infused Items Max metadata，以及 Tool Expertise / Flash of Genius / Magic Item Adept / Spell-Storing Item / Magic Item Savant / Magic Item Master / Soul of Artifice 等 feature progression。
- [x] Spellcasting 使用既有 P1 framework；Artificer prepared formula 為 `INT modifier + floor(Artificer level / 2)`，minimum 1。
- [x] Multiclass normal slot contribution 泛化為 canonical data-driven `formula + rounding`；legacy string config 仍 backward-compatible normalize，Artificer half-caster contribution 使用 `ceil`，Paladin / Ranger 維持 `floor`。
- [x] Prepared formula rounding 與 multiclass slot contribution rounding 彼此獨立，odd-level Artificer 不互相污染。
- [x] Warlock Pact Magic 與 Artificer normal multiclass slots 保持隔離。
- [x] Artificer spell list 只指向 installed valid spell entries；未 supplied 或不足以成為正式 SpellEntry 的 TCE spells 不 fake、不 dangling，並由 blocking reference audit 驗證。
- [x] 四個 Specialists 已加入：Alchemist、Armorer、Artillerist、Battle Smith；Subclass timing 為 Artificer Class Level 3。
- [x] Specialist progression metadata 於 Lv3 / Lv5 / Lv9 / Lv15 出現；不要求 combat effect execution。
- [x] Existing Artificer Level Up 保留 live state 語意：新增 Hit Die / spell capacity，已消耗資源不自動回滿，合法 prepared spells 保留，Lv3 Specialist choice 出現。
- [x] 新增／首次 expose 的 user-visible rules presentation 同步提供 `zh-TW` / `en`；M02 localization regression 全綠。
- [x] Real-backend E2E 覆蓋 Artificer Lv1、Artificer Lv3 + Specialist、High-Level Artificer、Artificer/Wizard multiclass、Existing Artificer Level Up。

## Verification Evidence

2026-09-01 最終驗證，分支 `feat/m01-g-tce-artificer-core` HEAD `87f0e78`：

```text
.\.venv\Scripts\python.exe -m pytest apps/server/tests
356 passed, 1 warning in 96.89s

.\.venv\Scripts\python.exe -m unittest scripts.test_build_m02d_srd_locale_reviewed scripts.test_run_m02d_srd_locale_authoring
13 tests OK

cd apps/server
$env:DATABASE_URL='sqlite+pysqlite:///C:/Users/User/AppData/Local/Temp/adventure-table-m01g-fresh-after-pull.db'
..\..\.venv\Scripts\python.exe -m alembic upgrade head
fresh SQLite migration passed through 0006_character_archive

TCE installed reference audit
MISSING_TCE_REFS []

cd apps/web
npm test -- --run
15 test files / 76 tests passed

npm run build
TypeScript / Vite build passed

npm run test:e2e -- m01g-artificer.spec.ts
5 passed (1.1m)

npm run test:e2e
53 passed (2.7m)

docker compose config
passed
```

E2E 驗證使用 temp SQLite backend，先執行 migration 與 `python -m app.scripts.seed_p0_fighter_wizard` 建立 deterministic fixture，再以 Vite / Playwright 跑完整 suite。未在本機執行 `docker compose down -v` 清除 compose volume；`m01g-e2e.yml` 已補上 CI full-stack Docker flow。

唯一 warning 是 FastAPI TestClient 匯入時由 Starlette 發出的 `httpx` deprecation warning，未影響測試結果。

## Boundary

- 不完成 active Infusions；M01-H 才處理 known vs active state 與 advanced infusion boundary。
- 不建立 Steel Defender combat entity。
- 不建立 Eldritch Cannon combat entity。
- 不做 Experimental Elixir 完整 runtime。
- 不做 Soul of Artifice reaction resolution。
- 不建立 firearm equipment universe。
- 不為 Artificer 建第二套 Builder / spellcasting / multiclass engine。

## Handoff

M01-G 已完成並關門。下一個可開工 Subphase：**M01-H — TCE Artificer Advanced Features & Infusions**。

M01-H 繼續遵守 M02 localization Definition of Done：新增、修改或首次 expose 的 user-visible system / rules content，必須在同一 Subphase 同步 `zh-TW` / `en`。
