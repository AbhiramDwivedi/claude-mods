import { expect, test } from 'claude-code/testing'

import { CONTRACT, nudgeNote, refusal, windDownNote, withContract } from '../hooks/register'

// scripts/ctx_study.py finds this mod's notes in transcripts by their wording. Reword a note without
// updating the script and its weekly report quietly counts zero. Tests can't run Python, so these are
// copies of the script's patterns (CONTRACT_HEADS, CONTRACT_BODY, NUDGE_RE, WIND_RE, REFUSE_RE):
// if this test fails, change the script to match the new wording, then change these copies.

const LIMITS = { nudge: 300_000, stop: 450_000 }
const MARK_RE = String.raw`\[(?:subagent-limits|pit-stop)\]`
const TOK = String.raw`(\d+(?:\.\d)?)([KM])`
const CONTRACT_HEAD = '[subagent-limits] Context budget.'
const CONTRACT_BODY = 'Every request you make re-sends your whole context'
const NUDGE_RE = new RegExp(MARK_RE + ' Your context has reached ' + TOK + ' tokens')
const WIND_RE = new RegExp(MARK_RE + ' Your context is ' + TOK + ' tokens, past the ' + TOK + ' limit')
const REFUSE_RE = new RegExp(MARK_RE + String.raw` Refused: your context \(` + TOK + String.raw` tokens\) is past the ` + TOK + ' limit')

test('scripts/ctx_study.py still recognises every note this mod writes', () => {
  for (const brief of [CONTRACT, withContract('Fix the parser in src/parse.ts.')]) {
    expect(brief).toContain(CONTRACT_HEAD)
    expect(brief).toContain(CONTRACT_BODY)
  }
  expect(nudgeNote(312_000, LIMITS)).toMatch(NUDGE_RE)
  expect(windDownNote(461_000, 3, LIMITS)).toMatch(WIND_RE)
  expect(windDownNote(470_000, 0, LIMITS)).toMatch(WIND_RE)
  expect(refusal(1_200_000, LIMITS)).toMatch(REFUSE_RE)
})
