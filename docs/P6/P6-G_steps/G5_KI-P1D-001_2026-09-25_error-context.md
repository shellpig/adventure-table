# KI-P1D-001 重現證據（2026-09-25，P6-G G5）

Playwright 產生的 error-context 原文，只保留測試資訊、錯誤與頁面快照；測試原始碼見 `apps/web/e2e/m01m-mtf-tiefling.spec.ts`。判讀與 DB 狀態見 [已知問題.md](../../../已知問題.md) KI-P1D-001 的 2026-09-25 重現紀錄。

## Test info

- Name: m01m-mtf-tiefling.spec.ts >> M01-M rejects a forged MTF bloodline plus SCAG variant payload
- Location: e2e\m01m-mtf-tiefling.spec.ts:386:1

## Error details

```
Error: expect(received).toBeGreaterThan(expected)

Expected: > 2
Received:   2

Call Log:
- Timeout 5000ms exceeded while waiting on the predicate
```

## Page snapshot

```yaml
- generic [ref=f2e2]:
  - group "Language" [ref=f2e3]:
    - button "Traditional Chinese" [ref=f2e4] [cursor=pointer]: 繁中
    - button "English" [pressed] [ref=f2e5] [cursor=pointer]: EN
  - main [ref=f2e6]:
    - generic [ref=f2e7]:
      - generic [ref=f2e8]:
        - generic [ref=f2e9]:
          - link "← Character Workshop" [ref=f2e10] [cursor=pointer]:
            - /url: /rooms/e73e7151-724b-446f-b122-6649b623e472/characters
          - heading "M01-M Forged Hero" [level=1] [ref=f2e12]
          - generic [ref=f2e13]: M02-B · Create Character
        - generic [ref=f2e14]:
          - generic [ref=f2e15]: Draft revision 2
          - strong [ref=f2e16]: Saving…
      - generic [ref=f2e17]:
        - complementary "Character creation steps" [ref=f2e18]:
          - button "01 Basic Name & target" [ref=f2e19] [cursor=pointer]:
            - generic [ref=f2e20]: "01"
            - generic [ref=f2e21]:
              - strong [ref=f2e22]: Basic
              - generic [ref=f2e23]: Name & target
          - button "02 Origin Race & background" [ref=f2e24] [cursor=pointer]:
            - generic [ref=f2e25]: "02"
            - generic [ref=f2e26]:
              - strong [ref=f2e27]: Origin
              - generic [ref=f2e28]: Race & background
          - button "03 Abilities Scores & starting choices" [ref=f2e29] [cursor=pointer]:
            - generic [ref=f2e30]: "03"
            - generic [ref=f2e31]:
              - strong [ref=f2e32]: Abilities
              - generic [ref=f2e33]: Scores & starting choices
          - button "04 Class Level-by-level rail" [ref=f2e34] [cursor=pointer]:
            - generic [ref=f2e35]: "04"
            - generic [ref=f2e36]:
              - strong [ref=f2e37]: Class
              - generic [ref=f2e38]: Level-by-level rail
          - button "05 Spellcasting Access & resources" [ref=f2e39] [cursor=pointer]:
            - generic [ref=f2e40]: "05"
            - generic [ref=f2e41]:
              - strong [ref=f2e42]: Spellcasting
              - generic [ref=f2e43]: Access & resources
          - button "06 Equipment Gear & roleplay" [ref=f2e44] [cursor=pointer]:
            - generic [ref=f2e45]: "06"
            - generic [ref=f2e46]:
              - strong [ref=f2e47]: Equipment
              - generic [ref=f2e48]: Gear & roleplay
          - button "07 Review Build snapshot & confirm" [ref=f2e49] [cursor=pointer]:
            - generic [ref=f2e50]: "07"
            - generic [ref=f2e51]:
              - strong [ref=f2e52]: Review
              - generic [ref=f2e53]: Build snapshot & confirm
        - generic [ref=f2e55]:
          - generic [ref=f2e56]:
            - paragraph [ref=f2e57]: STEP 02
            - heading "Choose an origin" [level=2] [ref=f2e58]
            - paragraph [ref=f2e59]: Selectors come from server-generated eligible content. Subrace is preserved as its own choice.
          - generic [ref=f2e60]:
            - generic [ref=f2e61]: Race
            - generic [ref=f2e62]:
              - combobox "Race" [disabled] [ref=f2e63]
              - 'button "Race: expand list" [disabled] [ref=f2e64]': ▾
          - generic [ref=f2e65]:
            - generic [ref=f2e66]: Lineage
            - generic [ref=f2e67]:
              - combobox "Lineage" [disabled] [ref=f2e68]
              - 'button "Lineage: expand list" [disabled] [ref=f2e69]': ▾
          - generic [ref=f2e70]:
            - generic [ref=f2e71]: Background
            - generic [ref=f2e72]:
              - combobox "Background" [disabled] [ref=f2e73]
              - 'button "Background: expand list" [disabled] [ref=f2e74]': ▾
          - generic [ref=f2e75]:
            - generic [ref=f2e76]: Alignment · optional
            - generic [ref=f2e77]:
              - combobox "Alignment · optional" [disabled] [ref=f2e78]
              - 'button "Alignment · optional: expand list" [disabled] [ref=f2e79]': ▾
          - generic [ref=f2e80]:
            - generic [ref=f2e81]: Resolved grants
            - strong [ref=f2e82]: "0"
            - generic [ref=f2e83]: Traits, languages and proficiencies are resolved by the server.
        - complementary [ref=f2e84]:
          - generic [ref=f2e85]:
            - generic [ref=f2e86]:
              - text: LIVE SUMMARY
              - heading "M01-M Forged Hero" [level=2] [ref=f2e87]
            - strong [ref=f2e88]: LV 1
          - generic [ref=f2e89]:
            - generic [ref=f2e90]:
              - term [ref=f2e91]: Race
              - definition [ref=f2e92]: —
            - generic [ref=f2e93]:
              - term [ref=f2e94]: Background
              - definition [ref=f2e95]: —
            - generic [ref=f2e96]:
              - term [ref=f2e97]: Class
              - definition [ref=f2e98]: —
            - generic [ref=f2e99]:
              - term [ref=f2e100]: Alignment
              - definition [ref=f2e101]: Optional
          - heading "Resolved grants" [level=3] [ref=f2e103]
          - generic [ref=f2e104]:
            - generic [ref=f2e105]:
              - heading "Validation" [level=3] [ref=f2e106]
              - generic [ref=f2e107]: 4 blocking
            - list [ref=f2e108]:
              - listitem [ref=f2e109]:
                - button "missing race Race selection is required before Confirm." [ref=f2e110] [cursor=pointer]:
                  - strong [ref=f2e111]: missing race
                  - generic [ref=f2e112]: Race selection is required before Confirm.
              - listitem [ref=f2e113]:
                - button "missing background Background selection is required before Confirm." [ref=f2e114] [cursor=pointer]:
                  - strong [ref=f2e115]: missing background
                  - generic [ref=f2e116]: Background selection is required before Confirm.
              - listitem [ref=f2e117]:
                - button "missing ability generation Ability generation is required before Confirm." [ref=f2e118] [cursor=pointer]:
                  - strong [ref=f2e119]: missing ability generation
                  - generic [ref=f2e120]: Ability generation is required before Confirm.
              - listitem [ref=f2e121]:
                - button "incomplete level progression Every target character level must have one ordered class progression choice." [ref=f2e122] [cursor=pointer]:
                  - strong [ref=f2e123]: incomplete level progression
                  - generic [ref=f2e124]: Every target character level must have one ordered class progression choice.
            - paragraph [ref=f2e125]: Starting equipment and final server Review are validated before Confirm becomes available.
          - button "Cancel Draft" [disabled] [ref=f2e126]
```
