import { describe, expect, it } from 'vitest'

import { filenameFromDisposition } from './api'

describe('M03-B export filename parsing', () => {
  it('prefers the RFC 5987 UTF-8 form over the ASCII fallback', () => {
    expect(
      filenameFromDisposition(
        `attachment; filename="character-v1-test.json"; filename*=UTF-8''%E6%B8%AC%E8%A9%A6%20%E8%A7%92%E8%89%B2-v1-test.json`,
      ),
    ).toBe('測試 角色-v1-test.json')
  })

  it('falls back to the quoted ASCII filename when no UTF-8 form is sent', () => {
    expect(filenameFromDisposition('attachment; filename="Fighter-v1-20260904T000000Z.json"')).toBe(
      'Fighter-v1-20260904T000000Z.json',
    )
  })

  it('keeps the raw value when the UTF-8 form is not decodable', () => {
    expect(filenameFromDisposition("attachment; filename*=UTF-8''%E4%B8")).toBe('%E4%B8')
  })

  it('uses a safe default when the header is absent or unparseable', () => {
    expect(filenameFromDisposition(null)).toBe('character.json')
    expect(filenameFromDisposition('attachment')).toBe('character.json')
  })
})
