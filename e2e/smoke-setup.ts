import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

/** Restore the demo snapshot of the local production stack, then wait until it answers. */
export default async function smokeSetup(): Promise<void> {
  const base = process.env.E2E_BASE_URL ?? 'http://localhost:8300';
  if (process.env.E2E_SKIP_RESET !== '1') {
    execFileSync(
      'docker',
      ['compose', '-f', 'compose.prod.yaml', 'exec', '-T', 'app', 'python', '-m', 'app.scripts.reset_demo', '--confirm'],
      { cwd: resolve(__dirname, '..'), stdio: 'inherit', timeout: 5 * 60 * 1000 },
    );
  }
  // A free web service sleeps when idle; the first request wakes it.
  const deadline = Date.now() + 3 * 60 * 1000;
  for (;;) {
    try {
      const response = await fetch(`${base}/api/v1/readyz`);
      if (response.ok) {
        return;
      }
    } catch {
      // Not up yet.
    }
    if (Date.now() > deadline) {
      throw new Error(`${base} did not become ready`);
    }
    await new Promise((done) => setTimeout(done, 3000));
  }
}
