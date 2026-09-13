const CHOICE_ISSUE_PATH_PREFIXES = [
  'draft_payload.choice_selections.',
  'draft_payload.starting_equipment_choices.',
]

export type IssueStep = 'basic' | 'origin' | 'abilities' | 'class' | 'spells' | 'equipment'

// Issues whose path names a draft field rather than a live choice still belong
// to one Builder step; longest prefix wins so `choice_selections.` (handled by
// issueChoiceId) is only reached here when no choice id follows it.
const ISSUE_STEP_PREFIXES: ReadonlyArray<readonly [string, IssueStep]> = [
  ['draft_payload.basic.', 'basic'],
  ['draft_payload.target_level', 'basic'],
  ['draft_payload.race_selection', 'origin'],
  ['draft_payload.subrace_selection', 'origin'],
  ['draft_payload.race_variant_selection', 'origin'],
  ['draft_payload.lineage_selection', 'origin'],
  ['draft_payload.background_selection', 'origin'],
  ['draft_payload.alignment_selection', 'origin'],
  ['draft_payload.ability_generation', 'abilities'],
  ['draft_payload.level_choices', 'class'],
  ['draft_payload.choice_selections', 'class'],
  ['draft_payload.spell_choices', 'spells'],
  ['draft_payload.starting_equipment_choices', 'equipment'],
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

export function issueStep(path: string): IssueStep | null {
  for (const [prefix, step] of ISSUE_STEP_PREFIXES) {
    if (path.startsWith(prefix)) return step
  }
  return null
}
