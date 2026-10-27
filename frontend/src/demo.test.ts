import { describe, expect, it } from 'vitest';
import { DemoClient, demoAnswer } from './demo';

describe('demo evidence integrity', () => {
  it('does not invent containers when the selected host inventory is empty', async () => {
    const client = new DemoClient();
    const answers: unknown[] = [];
    await client.diagnose(
      { host: 'demo-empty', query: 'Check this host' },
      (event) => {
        if (event.type === 'answer.ready') answers.push(event.answer);
      },
      new AbortController().signal,
    );
    expect(answers).toEqual([expect.objectContaining({ uncertain: true, evidence: [], widgets: [] })]);
  });
  it('keeps every bounded log timestamp at or before its observation', () => {
    const answer = demoAnswer('crash_loop', 'demo-eu');
    const log = answer.widgets.find((row) => row.widget_type === 'log_anomalies')!;
    const observation = answer.evidence.find((row) => row.kind === 'logs')!;
    expect(log.logs.entries.every((row) => Date.parse(row.timestamp!) <= Date.parse(observation.observed_at))).toBe(
      true,
    );
    const status = answer.widgets.find((row) => row.widget_type === 'container_status')!;
    expect(Date.parse(status.snapshot.started_at!)).toBeLessThanOrEqual(Date.parse(status.snapshot.observed_at));
  });

  it('computes stack membership and running counts from the same inventory', async () => {
    const client = new DemoClient();
    const containers = await client.containers('demo-eu');
    const stacks = demoAnswer('crash_loop').widgets.find((row) => row.widget_type === 'compose_stack')!.stacks;
    expect(stacks[0]?.total).toBe(containers.length);
    expect(stacks[0]?.running).toBe(containers.filter((row) => row.state === 'running').length);
    expect(stacks[0]?.container_ids).toEqual(containers.map((row) => row.id));
  });

  it.each(['oom', 'unconfirmed_sigkill'] as const)('preserves the empty log observation for %s', (scenario) => {
    const answer = demoAnswer(scenario);
    const card = answer.widgets.find((row) => row.widget_type === 'log_anomalies')!;
    expect(card.logs).toEqual({ entries: [], truncated: false });
    expect(answer.evidence.find((row) => row.kind === 'logs')?.data).toEqual(card.logs);
  });
});
