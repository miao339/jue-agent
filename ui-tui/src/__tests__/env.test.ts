import { afterEach, describe, expect, it, vi } from 'vitest'

const loadEnv = async () => {
  vi.resetModules()

  return import('../config/env.js')
}

describe('env config', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('reads startup resume id from JUE_TUI_RESUME', async () => {
    vi.stubEnv('JUE_TUI_RESUME', '20260409_000001_abc123')

    const env = await loadEnv()

    expect(env.STARTUP_RESUME_ID).toBe('20260409_000001_abc123')
  })
})
