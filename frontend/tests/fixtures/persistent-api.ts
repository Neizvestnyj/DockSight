import { test as base, expect, type Page } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import { mkdtemp, readFile, writeFile, unlink, rm } from 'node:fs/promises';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { InvestigationDetail, SavedTurn } from '../../src/investigation-contracts';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..');
const python = resolve(
  root,
  process.platform === 'win32' ? 'backend/.venv/Scripts/python.exe' : 'backend/.venv/bin/python',
);
const token = 'persistence-alice-test-token-0001';
const bobToken = 'persistence-bob-test-token-00002';
type Event = { event: string; container_id?: string };
type OriginMode = 'correct' | 'wrong' | 'unset';
type OwnedContainer = { id: string; name: string; owner: string };

/** Reserve an OS-assigned loopback port for the owned production preview. */
async function port() {
  const server = createServer();
  await new Promise<void>((done) => server.listen(0, '127.0.0.1', done));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('No allocated loopback port');
  await new Promise<void>((done, reject) => server.close((error) => (error ? reject(error) : done())));
  return address.port;
}

/** Own one process, discard sensitive HTTP data, and retain only safe server errors. */
function child(executable: string, args: string[], env: NodeJS.ProcessEnv, cwd = root) {
  const process = spawn(executable, args, { cwd, env, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] });
  let errors = '';
  process.stderr?.on('data', (chunk: Buffer) => (errors += chunk.toString()));
  process.on('error', (error) => (errors += `Owned process launch failed: ${error.name}`));
  process.stdout?.resume();
  return { process, errors: () => errors };
}

/** Reap only the PID created by this fixture. */
async function stop(process: ChildProcess) {
  if (process.pid === undefined) return;
  if (process.exitCode !== null || process.signalCode !== null) return;
  const closed = new Promise<void>((done) => process.once('exit', () => done()));
  process.kill('SIGKILL');
  await closed;
}

export class PersistentApi {
  readonly origin: string;
  backendOrigin = '';
  private backend?: ReturnType<typeof child>;
  private preview?: ReturnType<typeof child>;

  /** Keep all SQLite, IPC, and process ownership inside one allocated test directory. */
  constructor(
    readonly directory: string,
    readonly previewPort: number,
    readonly originMode: OriginMode,
    readonly liveModel = false,
  ) {
    this.origin = `http://127.0.0.1:${previewPort}`;
  }

  /** Start the actual Python backend before the Vite production preview. */
  async start() {
    if (this.liveModel) {
      await this.fixtureOperation('create');
      await writeFile(join(this.directory, 'live-model'), '');
    }
    await this.startBackend();
    this.preview = child(
      process.execPath,
      [
        join(root, 'frontend/node_modules/vite/bin/vite.js'),
        'preview',
        '--config',
        'tests/fixtures/persistence-vite.config.ts',
        '--host',
        '127.0.0.1',
        '--port',
        String(this.previewPort),
        '--strictPort',
      ],
      { ...process.env, DOCKSIGHT_TEST_BACKEND_ORIGIN: this.backendOrigin },
      join(root, 'frontend'),
    );
    await expect
      .poll(
        async () => {
          this.assertAlive();
          try {
            return (await fetch(this.origin, { signal: AbortSignal.timeout(2000) })).status;
          } catch {
            return 0;
          }
        },
        { timeout: 20_000 },
      )
      .toBe(200);
  }

  /** Run only the explicit owned-container fixture lifecycle command. */
  private async fixtureOperation(operation: 'create' | 'update' | 'remove') {
    const owned = child(
      python,
      ['-m', 'tests.integration.persistence.live', operation, '--directory', this.directory],
      {
        ...process.env,
        PYTHONPATH: [join(root, 'backend/src'), join(root, 'backend')].join(process.platform === 'win32' ? ';' : ':'),
      },
    );
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      const code = await new Promise<number | null>((done, reject) => {
        owned.process.once('exit', done);
        owned.process.once('error', reject);
        timeout = setTimeout(() => reject(new Error(`Owned Docker fixture ${operation} timed out`)), 30_000);
      });
      if (code !== 0) throw new Error(`Owned Docker fixture ${operation} failed: ${owned.errors()}`);
    } finally {
      clearTimeout(timeout);
      await stop(owned.process);
    }
  }

  /** Read only the fixture's exact label-bound Docker identity. */
  async container(): Promise<OwnedContainer> {
    return JSON.parse(await readFile(join(this.directory, 'live.json'), 'utf8')) as OwnedContainer;
  }

  /** Change the owned program's public test message and wait for its log acknowledgement. */
  async freshEvidence() {
    await this.fixtureOperation('update');
  }

  /** Restart a crashed backend at its original proxy destination and SQLite directory. */
  async restartBackend() {
    if (this.backend) await stop(this.backend.process);
    await unlink(join(this.directory, 'ready.json'));
    await this.startBackend(Number(new URL(this.backendOrigin).port));
  }

  /** Launch one production-wired API child with an explicit public proxy origin. */
  private async startBackend(port = 0) {
    const origin =
      this.originMode === 'correct' ? this.origin : this.originMode === 'wrong' ? 'http://127.0.0.1:1' : '';
    this.backend = child(
      python,
      [
        '-m',
        'tests.integration.persistence.server',
        '--directory',
        this.directory,
        '--origin',
        origin,
        '--port',
        String(port),
      ],
      {
        ...process.env,
        PYTHONPATH: [join(root, 'backend/src'), join(root, 'backend')].join(process.platform === 'win32' ? ';' : ':'),
      },
    );
    await this.marker('ready.json');
    this.backendOrigin = (
      JSON.parse(await readFile(join(this.directory, 'ready.json'), 'utf8')) as { origin: string }
    ).origin;
  }

  /** Fail readiness immediately when an owned server exits. */
  private assertAlive() {
    for (const owned of [this.backend, this.preview])
      if (owned && owned.process.exitCode !== null) throw new Error(`Owned server exited: ${owned.errors()}`);
  }

  /** Wait for a test-only file barrier rather than racing UI debounce or provider duration. */
  async marker(name: string) {
    await expect
      .poll(
        async () => {
          this.assertAlive();
          try {
            await readFile(join(this.directory, name));
            return true;
          } catch {
            return false;
          }
        },
        { timeout: 20_000 },
      )
      .toBe(true);
  }

  /** Arm the next model or mutation call before an explicit product action. */
  async block(name: 'model' | 'mutation') {
    await unlink(join(this.directory, `${name}.entered`)).catch((error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error;
    });
    await writeFile(join(this.directory, `${name}.block`), '');
  }

  /** Release only a barrier owned by this test. */
  async release(name: 'model' | 'mutation') {
    await unlink(join(this.directory, `${name}.block`));
  }

  /** Read safe operation counts without recording model messages or credentials. */
  async events(): Promise<Event[]> {
    try {
      return (await readFile(join(this.directory, 'events.jsonl'), 'utf8'))
        .trim()
        .split('\n')
        .filter(Boolean)
        .map((line) => JSON.parse(line) as Event);
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
      throw error;
    }
  }

  /** Call real saved endpoints with a synthetic fixture actor, independently of browser cookies. */
  async api<T = unknown>(path: string, method = 'GET', body?: unknown, actor: 'alice' | 'bob' = 'alice'): Promise<T> {
    const response = await fetch(`${this.backendOrigin}/api/v1${path}`, {
      method,
      signal: AbortSignal.timeout(15_000),
      headers: { Authorization: `Bearer ${actor === 'alice' ? token : bobToken}`, 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    if (!response.ok) throw new Error(`Fixture API ${method} ${path}: ${response.status} ${await response.text()}`);
    return (response.status === 204 ? undefined : await response.json()) as T;
  }

  /** Check missing/foreign ownership without leaking synthetic credentials into artifacts. */
  async status(path: string, actor: 'alice' | 'bob') {
    return (
      await fetch(`${this.backendOrigin}/api/v1${path}`, {
        signal: AbortSignal.timeout(15_000),
        headers: { Authorization: `Bearer ${actor === 'alice' ? token : bobToken}` },
      })
    ).status;
  }

  /** Change action time through test IPC, leaving browser session and turn clocks untouched. */
  async advanceActions(seconds: number) {
    await writeFile(join(this.directory, 'action-clock.txt'), String(seconds));
  }

  /** Read the actor's currently acknowledged investigation. */
  async current() {
    const workspace = await this.api<{ last_investigation_id: string }>('/me/workspace');
    return this.api<InvestigationDetail>(`/investigations/${workspace.last_investigation_id}`);
  }

  /** Acknowledge an exact fixture scope through the real revisioned workspace API. */
  async targetWorker(page: Page, selected = { kind: 'container', id: 'a'.repeat(64), name: 'worker' }) {
    const chat = await this.current();
    await this.api(`/investigations/${chat.id}/workspace`, 'PATCH', {
      expected_revision: chat.workspace.revision,
      target: selected,
    });
    await page.reload();
    await expect(page.getByText(`Saved container scope: ${selected.name} ·`)).toBeVisible();
  }

  /** Poll terminal state through authoritative reads only. */
  async terminal(id: string) {
    await expect.poll(async () => (await this.api<SavedTurn>(`/turns/${id}`)).state).not.toBe('running');
    return this.api<SavedTurn>(`/turns/${id}`);
  }

  /** Exchange the one-use synthetic token through the actual product login dialog. */
  async login(page: Page, actor: 'alice' | 'bob' = 'alice') {
    await page.goto(this.origin);
    await page.getByRole('button', { name: 'Connect API', exact: true }).click();
    await page.getByLabel('Bearer token', { exact: true }).fill(actor === 'alice' ? token : bobToken);
    await page.getByRole('button', { name: 'Connect', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);
    await expect(page.getByRole('textbox')).toBeVisible();
  }

  /** Reap owned processes, then verify the temporary target before recursive cleanup. */
  async close() {
    if (this.preview) await stop(this.preview.process);
    if (this.backend) await stop(this.backend.process);
    if (this.liveModel) {
      try {
        await readFile(join(this.directory, 'live.json'));
        await this.fixtureOperation('remove');
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
      }
    }
    const target = resolve(this.directory);
    if (!target.startsWith(resolve(tmpdir()) + sep) || !target.includes('docksight-persistence-'))
      throw new Error('Refusing cleanup outside the allocated persistence fixture directory');
    await rm(target, { recursive: true, force: true, maxRetries: 20, retryDelay: 100 });
  }
}

export const test = base.extend<{ persistent: PersistentApi; originMode: OriginMode; liveModel: boolean }>({
  originMode: ['correct', { option: true }],
  liveModel: [false, { option: true }],
  persistent: async ({ originMode, liveModel }, provide) => {
    const directory = await mkdtemp(join(tmpdir(), 'docksight-persistence-'));
    const api = new PersistentApi(directory, await port(), originMode, liveModel);
    try {
      await api.start();
      await provide(api);
    } finally {
      await api.close();
    }
  },
});
export { expect };
