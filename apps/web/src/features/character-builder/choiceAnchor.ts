const CHOICE_ISSUE_PATH_PREFIXES = [
  'draft_payload.choice_selections.',
  'draft_payload.starting_equipment_choices.',
]

export function choiceAnchorId(choiceId: string): string {
  return `builder-choice-${choiceId}`
}

export function issueChoiceId(path: string): string | null {
  for (const prefix of CHOICE_ISSUE_PATH_PREFIXES) {
    if (path.startsWith(prefix)) return path.slice(prefix.length) || null
  }
  return null
}
