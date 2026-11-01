import { spawn } from 'node:child_process'
import { resolve } from 'node:path'

const base = import.meta.dirname
const vitePort = process.env.VITE_DEV_PORT || '5175'
const processes = [
  spawn(process.execPath, ['--env-file-if-exists=.env', 'server/index.mjs'], { cwd: base, stdio: 'inherit' }),
  spawn(process.execPath, [resolve(base, 'node_modules/vite/bin/vite.js'), '--port', vitePort], { cwd: base, stdio: 'inherit' }),
]
let stopping = false
function stop(code = 0) {
  if (stopping) return
  stopping = true
  for (const child of processes) child.kill('SIGTERM')
  setTimeout(() => process.exit(code), 250).unref()
}
for (const child of processes) child.on('exit', (code) => stop(code || 0))
process.on('SIGINT', () => stop(0))
process.on('SIGTERM', () => stop(0))
