import { mkdtempSync, rmdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { build } from 'vite'

// Empty, dedicated env directory; do not read project or developer .env files.
const envDir = mkdtempSync(join(tmpdir(), 'yayi-offline-build-'))
process.env.YAYI_OFFLINE_BUILD = '1'
process.env.VITE_TITLE = 'YAYI 科研助手'
process.env.VITE_API_BASE = '/api'
try {
  await build({ mode: 'offline', envDir })
} finally {
  // Non-recursive removal of the exact empty directory created above.
  rmdirSync(envDir)
}
