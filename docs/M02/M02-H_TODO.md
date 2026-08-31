# M02-H TODO

## Structured system-owned localization messages

M02-G guarantees that normal `zh-TW` UI does not fall back to concatenating canonical English server prose. Every builder issue `code` the server emits (43 of 43) now has localized copy in both supported locales; unknown issue codes and every disabled-reason path use a Chinese-only safe fallback.

Disabled reasons are the remaining gap. The server sends them as free English prose with no machine code, so `DISABLED_REASON_MESSAGES` in `apps/web/src/i18n/systemMessages.ts` — including its `code + params` formatters — is written but unreachable at runtime. Every disabled option therefore reads `此選項目前無法選擇；請先完成相關條件。` in `zh-TW`, while `en` keeps the concrete reason. That asymmetry is accepted for M02-G closeout and must be closed here.

M02-H must finish the structured detail channel for dynamic system-owned messages:

- Server responses should emit a stable language-neutral `code` plus structured params instead of interpolating canonical English names into `message` / `disabled_reason`.
- Builder issues should expose `message_params` for dynamic values.
- Builder choice/option disabled states should expose `disabled_reason_code` plus `disabled_reason_params`.
- Params that identify rules content should use StableKeys (for example `class_ref`, `feat_ref`, `spell_ref`) so the frontend resolves their display names through the active locale before interpolation.
- Ability/prerequisite values should use language-neutral structured values rather than parsed English prose.
- Frontend localization must format `code + params`; it must not regex-match English server strings.
- Add coverage proving parameterized messages switch locale without changing machine identity and that `zh-TW` normal flows contain no avoidable English prose.

Until that contract is fully emitted by the server, the M02-G frontend intentionally prefers a Chinese-only generic fallback over mixed-language detail for unmapped messages.
