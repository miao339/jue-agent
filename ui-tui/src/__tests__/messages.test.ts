import { describe, expect, it } from 'vitest'

import { toTranscriptMessages } from '../domain/messages.js'
import { upsert } from '../lib/messages.js'

describe('upsert', () => {
  it('appends when last role differs', () => {
    expect(upsert([{ role: 'user', text: 'hi' }], 'assistant', 'hello')).toHaveLength(2)
  })

  it('replaces when last role matches', () => {
    expect(upsert([{ role: 'assistant', text: 'partial' }], 'assistant', 'full')[0]!.text).toBe('full')
  })

  it('appends to empty', () => {
    expect(upsert([], 'user', 'first')).toEqual([{ role: 'user', text: 'first' }])
  })

  it('does not mutate', () => {
    const prev = [{ role: 'user' as const, text: 'hi' }]

    upsert(prev, 'assistant', 'yo')

    expect(prev).toHaveLength(1)
  })

  describe('toTranscriptMessages', () => {
    it('formats resumed history with full users, two-line assistants, and folded tools', () => {
      const rows = [
        { role: 'user', text: 'first line\nsecond line\nthird line' },
        { role: 'tool', name: 'read_file', context: '/tmp/a.txt' },
        { role: 'tool', name: 'search_files', context: 'query' },
        { role: 'assistant', text: 'answer line 1\nanswer line 2\nanswer line 3' }
      ]

      expect(toTranscriptMessages(rows)).toEqual([
        { role: 'user', text: 'first line\nsecond line\nthird line' },
        { role: 'assistant', text: '[2 tool calls: read_file, search_files]' },
        { role: 'assistant', text: 'answer line 1\nanswer line 2...' }
      ])
    })
  })
})
