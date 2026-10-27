import fixtures from '../../backend/tests/fixtures/diagnostics.json' with { type: 'json' };
import {
  answerSchema,
  type Action,
  type Answer,
  type Container,
  type Host,
  type LogBatch,
  type Transport,
  type TurnInput,
  type TurnEvent,
} from './contracts';

export const scenarios = [
  {
    id: 'crash_loop',
    name: 'Crash loop',
    container: 'payments-api',
    image: 'ghcr.io/northstar/payments:2.8.1',
    query: 'Why does payments-api keep restarting?',
  },
  {
    id: 'oom',
    name: 'Out of memory',
    container: 'report-worker',
    image: 'ghcr.io/northstar/reports:1.6.0',
    query: 'Why did report-worker exit with code 137?',
  },
  {
    id: 'dependency',
    name: 'Dependency unavailable',
    container: 'checkout-api',
    image: 'ghcr.io/northstar/checkout:3.2.4',
    query: 'Why can checkout-api not start?',
  },
  {
    id: 'truncated_logs',
    name: 'Truncated logs',
    container: 'migration-runner',
    image: 'ghcr.io/northstar/migrations:4.0.0',
    query: 'What happened to migration-runner?',
  },
  {
    id: 'unconfirmed_sigkill',
    name: 'Unconfirmed exit',
    container: 'event-consumer',
    image: 'ghcr.io/northstar/events:1.12.0',
    query: 'Was event-consumer killed by the OOM killer?',
  },
  {
    id: 'running',
    name: 'Running / zero CPU',
    container: 'redis',
    image: 'redis:7.4-alpine',
    query: 'Is redis healthy in this observation?',
  },
] as const;
export type ScenarioId = (typeof scenarios)[number]['id'];
export type DemoFault = 'none' | 'offline' | 'stream' | 'empty';
export const demoHosts: Host[] = [
  { id: 'demo-eu', name: 'Demo host / EU' },
  { id: 'demo-empty', name: 'Demo host / Empty' },
];

/** Build a fixture-backed Docker snapshot, keeping missing metrics distinct from zero. */
export function demoContainer(index: number, host: string, observedAt: string): Container {
  const scenario = scenarios[index] ?? scenarios[0];
  const fixture = fixtures.find((row) => row.name === scenario.id)!;
  return {
    host,
    id: (index + 1).toString(16).repeat(64),
    name: scenario.container,
    image: scenario.image,
    state: fixture.state as Container['state'],
    exit_code: fixture.exit_code,
    oom_killed: fixture.oom_killed,
    restart_count: fixture.restart_count,
    started_at: new Date(Date.parse(observedAt) - 600_000).toISOString(),
    observed_at: observedAt,
    metrics:
      fixture.state === 'running'
        ? { cpu_percent: 0, memory_usage_bytes: 8_388_608, memory_limit_bytes: 134_217_728 }
        : { cpu_percent: null, memory_usage_bytes: null, memory_limit_bytes: null },
    environment: [
      ['APP_ENV', 'production'],
      ['LOG_LEVEL', 'info'],
      ['PORT', '8080'],
    ],
    compose_project: 'commerce',
  };
}

/** Share fixture log text between direct reads and diagnostics without preparing any actions. */
function demoLogs(scenarioId: ScenarioId, observedAt: string): LogBatch {
  const fixture = fixtures.find((row) => row.name === scenarioId)!;
  const messages = fixture.log
    ? [
        'Starting application bootstrap',
        'Loading runtime configuration from environment',
        fixture.log,
        ...(scenarioId === 'crash_loop'
          ? ['  at validateConfig (/app/config.py:42)', 'Application startup failed; process exiting with code 1']
          : []),
      ]
    : [];
  return {
    entries: messages.map((message, i) => ({
      timestamp: new Date(Date.parse(observedAt) - (messages.length - i) * 1000).toISOString(),
      message,
    })),
    truncated: fixture.truncated,
  };
}

/** Produce all four supported widgets using only fields in the backend contracts. */
export function demoAnswer(scenarioId: ScenarioId, host = 'demo-eu'): Answer {
  const index = scenarios.findIndex((row) => row.id === scenarioId);
  const now = new Date().toISOString();
  const snapshot = demoContainer(index, host, now);
  const fixture = fixtures.find((row) => row.name === scenarioId)!;
  const ref = (kind: string) => `demo-${kind}-${scenarioId}-${host}`;
  const summaries: Record<ScenarioId, string> = {
    crash_loop:
      'payments-api is caught in a restart loop. Docker reports 9 restarts and exit code 1. The startup logs report invalid application configuration. Review the configuration before restarting; stopping the loop is available for this observed state.',
    oom: 'Docker reports that report-worker was OOM-killed and exited with code 137. This supports an out-of-memory termination. Current memory usage is unavailable after exit; these observations do not establish which allocation caused it.',
    dependency:
      'checkout-api exited with code 1. Its logs report a refused database connection. This points to an unavailable dependency at startup; the database itself was not inspected, so its cause is not established.',
    truncated_logs:
      'migration-runner exited with code 1, but the available logs end during startup. The log batch is truncated. The evidence is insufficient to identify the failure; inspect the complete logs before choosing a fix.',
    unconfirmed_sigkill:
      'event-consumer exited with code 137. Docker does not report an OOM kill, and no log entries are available. Code 137 alone does not establish an out-of-memory cause. The reason for termination remains uncertain.',
    running:
      'redis is running in this observation. Current CPU usage is 0.0% and memory usage is 8.0 MiB of 128.0 MiB. No restarts or OOM kill are reported. These values are a single measurement, not a historical health guarantee.',
  };
  const logs = demoLogs(scenarioId, now);
  const operation = snapshot.state === 'restarting' ? 'stop' : 'restart';
  const action: Action = {
    id: crypto.randomUUID(),
    host,
    container_id: snapshot.id,
    operation,
    expires_at: new Date(Date.now() + 300_000).toISOString(),
    state: 'prepared',
    message: 'Confirmation required',
    confirmation_required: true,
  };
  const inventory = scenarios.map((_, i) => demoContainer(i, host, now));
  const stacks = [
    {
      name: 'commerce',
      kind: 'compose' as const,
      total: inventory.length,
      running: inventory.filter((row) => row.state === 'running').length,
      container_ids: inventory.map((row) => row.id),
    },
  ];
  return answerSchema.parse({
    schema_version: 1,
    summary: summaries[scenarioId],
    uncertain: Boolean(fixture.requires_uncertainty),
    evidence: [
      { id: ref('container'), kind: 'container', host, container_id: snapshot.id, observed_at: now, data: snapshot },
      { id: ref('logs'), kind: 'logs', host, container_id: snapshot.id, observed_at: now, data: logs },
      { id: ref('stack'), kind: 'stack', host, container_id: null, observed_at: now, data: { stacks } },
      {
        id: ref('env'),
        kind: 'env',
        host,
        container_id: snapshot.id,
        observed_at: now,
        data: { variables: Object.fromEntries(snapshot.environment) },
      },
    ],
    widgets: [
      {
        widget_type: 'container_status',
        snapshot,
        evidence_ids: [ref('container')],
        actions:
          snapshot.state === 'running' ? [action, { ...action, id: crypto.randomUUID(), operation: 'stop' }] : [action],
      },
      {
        widget_type: 'log_anomalies',
        host,
        container_id: snapshot.id,
        logs,
        evidence_ids: [ref('container'), ref('logs')],
      },
      { widget_type: 'compose_stack', host, stacks, evidence_ids: [ref('stack')] },
      {
        widget_type: 'env_inspector',
        host,
        container_id: snapshot.id,
        variables: Object.fromEntries(snapshot.environment),
        evidence_ids: [ref('env')],
        read_only: true,
      },
    ],
  });
}

/** Wait for simulated transport work while honoring the real cancellation signal. */
async function delay(signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  await new Promise<void>((resolve, reject) => {
    const abort = () => {
      clearTimeout(timer);
      reject(signal.reason);
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', abort);
      resolve();
    }, 480);
    signal.addEventListener('abort', abort, { once: true });
  });
}

/** Simulate the API boundary explicitly; no demo operation reaches Docker. */
export class DemoClient implements Transport {
  scenario: ScenarioId = 'crash_loop';
  fault: DemoFault = 'none';
  outcome: 'succeeded' | 'failed' | 'indeterminate' | 'expired' = 'succeeded';
  private readonly actions = new Map<string, Action>();
  private readonly keys = new Map<string, string>();

  /** Configure the next fixture without mutating React-owned data. */
  setScenario(value: ScenarioId) {
    this.scenario = value;
  }

  /** Select a simulated connection boundary. */
  setFault(value: DemoFault) {
    this.fault = value;
  }

  /** Select a simulated Docker outcome before confirming an operation. */
  setOutcome(value: DemoClient['outcome']) {
    this.outcome = value;
  }

  /** Retain simulated prepared IDs exactly as a server would. */
  remember(answer: Answer): Answer {
    answer.widgets.forEach((widget) => {
      if (widget.widget_type === 'container_status')
        widget.actions.forEach((action) => this.actions.set(action.id, action));
    });
    return answer;
  }

  /** Keep selected examples consistent with empty-host and empty-inventory simulations. */
  example(host: string): Answer {
    if (host === 'demo-empty' || this.fault === 'empty')
      return {
        schema_version: 1,
        summary: 'No containers were returned on this host. There is no container evidence to establish a cause.',
        uncertain: true,
        evidence: [],
        widgets: [],
      };
    return this.remember(demoAnswer(this.scenario, host));
  }

  /** Return only configured simulated host IDs. */
  async hosts() {
    return demoHosts;
  }

  /** Keep inventory counts derived from the returned rows. */
  async containers(host: string) {
    if (this.fault === 'offline') throw new Error('Demo: host connection unavailable.');
    if (this.fault === 'empty' || host === 'demo-empty') return [];
    const now = new Date().toISOString();
    return scenarios.map((_, i) => demoContainer(i, host, now));
  }

  /** Inspect a fixture by exact identity; reading never prepares an action or calls a model. */
  async container(host: string, id: string, signal: AbortSignal): Promise<Container> {
    await delay(signal);
    const snapshot = (await this.containers(host)).find((row) => row.id === id);
    if (!snapshot) throw new Error('Demo: container not found.');
    return snapshot;
  }

  /** Return the selected fixture's original bounded logs, independent of the scenario control. */
  async logs(host: string, id: string, signal: AbortSignal): Promise<LogBatch> {
    const snapshot = await this.container(host, id, signal);
    const scenario = scenarios.find((row) => row.container === snapshot.name)!;
    return demoLogs(scenario.id, snapshot.observed_at);
  }

  /** Return a single fixture measurement without generating a time series. */
  async stats(host: string, id: string, signal: AbortSignal) {
    return (await this.container(host, id, signal)).metrics;
  }

  /** Emit the same six event types as the streaming backend. */
  async diagnose(input: TurnInput, receive: (event: TurnEvent) => void, signal: AbortSignal) {
    if (this.fault === 'offline') throw new Error('Demo: connection lost before the diagnostic stream opened.');
    const envelope = { schema_version: 1 as const, request_id: crypto.randomUUID(), turn_id: crypto.randomUUID() };
    receive({ ...envelope, type: 'turn.started', session_id: input.session_id ?? crypto.randomUUID() });
    const empty = input.host === 'demo-empty' || this.fault === 'empty';
    const tools = empty
      ? ['list_containers']
      : ['inspect_container', 'get_container_logs', 'list_stacks', 'get_container_env'];
    for (const tool of tools) {
      receive({ ...envelope, type: 'tool.started', tool });
      await delay(signal);
      receive({ ...envelope, type: 'tool.completed', tool, ok: true });
    }
    if (this.fault === 'stream') {
      receive({
        ...envelope,
        type: 'turn.failed',
        code: 'model_timeout',
        message: 'Demo: model timed out after collecting evidence.',
      });
      return;
    }
    receive({
      ...envelope,
      type: 'answer.ready',
      answer: this.example(input.host),
    });
    receive({ ...envelope, type: 'turn.completed' });
  }

  /** Read a retained simulation without changing its target. */
  async action(id: string) {
    const action = this.actions.get(id);
    if (!action) throw new Error('Demo action not found. Run a fresh diagnosis.');
    return action;
  }

  /** Deduplicate simulated executions and expose selectable failure boundaries. */
  async execute(id: string, key: string) {
    const current = await this.action(id);
    if (this.keys.has(id)) {
      if (this.keys.get(id) !== key) throw new Error('Action uses another idempotency key.');
      return current;
    }
    this.keys.set(id, key);
    const state = Date.now() >= Date.parse(current.expires_at) ? 'expired' : this.outcome;
    const result: Action = {
      ...current,
      state,
      message: `Demo operation ${state}. Runtime observations have not been refreshed.`,
    };
    await new Promise((resolve) => setTimeout(resolve, 650));
    this.actions.set(id, result);
    return result;
  }
}
