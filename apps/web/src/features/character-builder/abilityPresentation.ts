export function formatSignedBonus(value: number): string {
  if (value === 0) return ''
  return value > 0 ? `+${value}` : String(value)
}
