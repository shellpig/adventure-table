const CHOICE_ISSUE_PATH_PREFIX = 'draft_payload.choice_selections.'

export function choiceAnchorId(choiceId: string): string {
  return `builder-choice-${choiceId}`
}

export function issueChoiceId(path: string): string | null {
  if (!path.startsWith(CHOICE_ISSUE_PATH_PREFIX)) return null
  return path.slice(CHOICE_ISSUE_PATH_PREFIX.length) || null
}
