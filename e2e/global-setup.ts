import { execFileSync } from 'node:child_process';
import { mkdirSync } from 'node:fs';
import { resolve } from 'node:path';

/** Put the demo back to its seeded state through real pipeline runs, then check the stack is up. */
export default async function globalSetup(): Promise<void> {
  mkdirSync(resolve(__dirname, '..', 'assets', 'screenshots'), { recursive: true });
  if (process.env.E2E_SKIP_RESET !== '1') {
    execFileSync(
      'docker',
      ['compose', 'exec', '-T', 'orchestrator', 'python', '-m', 'app.scripts.reset_demo', '--confirm'],
      { cwd: resolve(__dirname, '..'), stdio: 'inherit', timeout: 20 * 60 * 1000 },
    );
  }
  const base = process.env.E2E_BASE_URL ?? 'http://localhost:4200';
  const response = await fetch(`${base}/api/v1/readyz`);
  if (!response.ok) {
    throw new Error(`The stack is not ready: ${base}/api/v1/readyz answered ${response.status}`);
  }
}
