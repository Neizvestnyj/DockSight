import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DemoClient } from './demo';
import { useGroups } from './useGroups';
import { answerSchema, eventSchema } from './contracts';
import { demoAnswer } from './demo';
import { GroupReport } from './GroupReport';
import { LocaleProvider } from './LocaleProvider';
import { Investigation } from './Investigation';
import { useInvestigation } from './useInvestigation';
import { WidgetCard } from './Widgets';
import type { Answer } from './contracts';

afterEach(cleanup);

/** Render an immutable completed turn without a live transport or provider. */
function ObservedAnswer({ answer }: { answer: Answer }) {
  const client = new DemoClient();
  const investigation = useInvestigation(client, 'demo-eu', answer);
  return (
    <Investigation
      investigation={investigation}
      client={client}
      demo={false}
      containers={[]}
      draft=""
      setDraft={() => undefined}
      host="demo-eu"
    />
  );
}

describe('group selection', () => {
  it('retains a typed group clarification after completion without manufacturing an answer', async () => {
    const client = new DemoClient();
    vi.spyOn(client, 'diagnose').mockImplementation(async (_input, receive) => {
      const envelope = { schema_version: 1 as const, request_id: 'r', turn_id: 't' };
      receive({
        ...envelope,
        type: 'clarification.required',
        selection: {
          candidates: [
            { kind: 'compose', name: 'vintoria-infra' },
            { kind: 'swarm', name: 'vintoria-infra' },
          ],
        },
      });
      receive({ ...envelope, type: 'turn.completed' });
    });
    const { result } = renderHook(() => useInvestigation(client, 'demo-eu'));
    await act(async () => result.current.run('Which infrastructure?'));
    expect(result.current.turns[0]?.state).toBe('awaiting_selection');
    expect(result.current.turns[0]?.selection?.candidates).toHaveLength(2);
    expect(result.current.turns[0]?.answer).toBeUndefined();
    expect(result.current.running).toBe(false);
  });

  it('rejects duplicate or host-overriding group choices at the event boundary', () => {
    const candidate = { kind: 'compose', name: 'vintoria-infra' };
    const event = {
      schema_version: 1,
      request_id: 'r',
      turn_id: 't',
      type: 'clarification.required',
      selection: { candidates: [candidate] },
    };
    expect(eventSchema.safeParse(event).success).toBe(true);
    expect(eventSchema.safeParse({ ...event, selection: { candidates: [candidate, candidate] } }).success).toBe(false);
    expect(
      eventSchema.safeParse({ ...event, selection: { candidates: [{ ...candidate, host: 'foreign' }] } }).success,
    ).toBe(false);
  });

  it('groups shuffled state, logs and environment by historical container without changing answer data', () => {
    const answer = demoAnswer('dependency');
    const other = demoAnswer('oom');
    const state = answer.widgets.find((row) => row.widget_type === 'container_status')!;
    const logs = answer.widgets.find((row) => row.widget_type === 'log_anomalies')!;
    answer.widgets = [
      logs,
      ...other.widgets.map((row) => ({ ...row, evidence_ids: row.evidence_ids.map((ref) => `other-${ref}`) })),
      ...answer.widgets.filter((row) => row !== logs),
    ];
    answer.evidence.push(...other.evidence.map((row) => ({ ...row, id: `other-${row.id}` })));
    Object.freeze(answer.widgets);
    render(<ObservedAnswer answer={answer} />);
    const panel = screen.getByRole('region', { name: 'Container evidence: checkout-api' });
    expect(within(panel).getByRole('group', { name: 'Container status' })).toBeVisible();
    expect(within(panel).getByRole('group', { name: 'Container logs' })).toBeVisible();
    expect(within(panel).getByRole('group', { name: 'Environment' })).toBeVisible();
    expect(within(panel).queryByText('report-worker', { exact: true })).toBeNull();
    expect(within(panel).getByText(state.snapshot.image)).toBeVisible();
    expect(screen.getByRole('region', { name: 'Container evidence: report-worker' })).toBeVisible();
  });

  it('keeps identical container IDs from different hosts in separate panels', () => {
    const answer = demoAnswer('dependency');
    const state = answer.widgets.find((row) => row.widget_type === 'container_status')!;
    answer.widgets.push({ ...state, snapshot: { ...state.snapshot, host: 'other-host', name: 'other-worker' } });
    render(<ObservedAnswer answer={answer} />);
    expect(screen.getByRole('region', { name: 'Container evidence: checkout-api' })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Container evidence: other-worker' })).toHaveTextContent('other-host');
  });

  it('reopens collapsed logs from the explanation and retains the exact observed source', () => {
    const answer = demoAnswer('dependency');
    render(<ObservedAnswer answer={answer} />);
    const panel = screen.getByRole('region', { name: 'Container evidence: checkout-api' });
    fireEvent.click(within(panel).getByRole('button', { name: 'Collapse logs' }));
    expect(within(panel).getByRole('button', { name: 'Expand logs' })).toHaveAttribute('aria-expanded', 'false');
    expect(within(panel).queryByRole('group', { name: 'Timestamped container logs' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'View log evidence' }));
    expect(within(panel).getByRole('group', { name: 'Timestamped container logs' })).toBeVisible();
    expect(screen.getByRole('region', { name: 'Evidence observation' })).toHaveTextContent('Docker logs');
    expect(screen.getByRole('region', { name: 'Evidence observation' })).toHaveFocus();
  });

  it('names a log-only panel from retained evidence and never invents a state snapshot', () => {
    const answer = demoAnswer('dependency');
    answer.widgets = answer.widgets.filter((row) => row.widget_type === 'log_anomalies');
    render(<ObservedAnswer answer={answer} />);
    const panel = screen.getByRole('region', { name: 'Container evidence: checkout-api' });
    expect(within(panel).getByText('State was not included in this answer.')).toBeVisible();
    expect(within(panel).queryByRole('group', { name: 'Container status' })).toBeNull();
  });

  it('names log-only evidence from captured metadata when the answer omits the status observation', () => {
    const original = demoAnswer('dependency');
    const answer = answerSchema.parse({
      ...original,
      widgets: original.widgets.filter((row) => row.widget_type === 'log_anomalies'),
      evidence: original.evidence
        .filter((row) => row.kind === 'logs')
        .map((row) => ({ ...row, container_name: 'monitoring-grafana-1' })),
    });
    render(<ObservedAnswer answer={answer} />);
    const panel = screen.getByRole('region', { name: 'Container evidence: monitoring-grafana-1' });
    expect(within(panel).getByRole('heading', { name: 'monitoring-grafana-1' })).toBeVisible();
    expect(within(panel).queryByRole('group', { name: 'Container status' })).toBeNull();
    const source = screen.getByRole('group', { name: 'monitoring-grafana-1' });
    fireEvent.click(within(source).getByRole('button', { name: /^Logs/ }));
    expect(screen.getByRole('region', { name: 'Evidence observation' })).toHaveTextContent('monitoring-grafana-1');
  });

  it('retains repeated state observations and their distinct timestamps in one container panel', () => {
    const answer = demoAnswer('dependency');
    const status = answer.widgets.find((row) => row.widget_type === 'container_status')!;
    answer.widgets = [
      { ...status, snapshot: { ...status.snapshot, observed_at: '2026-10-28T10:00:00Z', restart_count: 2 } },
      { ...status, snapshot: { ...status.snapshot, observed_at: '2026-10-28T10:05:00Z', restart_count: 3 } },
    ];
    render(<ObservedAnswer answer={answer} />);
    const panel = screen.getByRole('region', { name: 'Container evidence: checkout-api' });
    const states = within(panel).getAllByRole('group', { name: 'Container status' });
    expect(states).toHaveLength(2);
    expect(within(states[0]!).getByText('10:00:00 UTC')).toBeVisible();
    expect(within(states[1]!).getByText('10:05:00 UTC')).toBeVisible();
    expect(within(states[0]!).getByText('2', { exact: true })).toBeVisible();
    expect(within(states[1]!).getByText('3', { exact: true })).toBeVisible();
    expect(within(panel).getByText('No log card was returned for this container.')).toBeVisible();
  });
  it('distinguishes sources by their historical container even without current inventory', () => {
    const answer = demoAnswer('dependency');
    const state = answer.evidence.find((row) => row.kind === 'container')!;
    const status = answer.widgets.find((row) => row.widget_type === 'container_status')!;
    answer.evidence.push({
      ...state,
      id: 'other-state',
      container_id: 'f'.repeat(64),
      data: { ...state.data, name: 'monitoring-grafana-1' },
    });
    answer.widgets.push({
      ...status,
      snapshot: { ...status.snapshot, id: 'f'.repeat(64), name: 'monitoring-grafana-1' },
      evidence_ids: ['other-state'],
      actions: [],
    });
    render(<ObservedAnswer answer={answer} />);
    const worker = screen.getByRole('group', { name: 'checkout-api' });
    const grafana = screen.getByRole('group', { name: 'monitoring-grafana-1' });
    expect(within(worker).getByRole('button', { name: /^State/ })).toBeVisible();
    expect(within(worker).getByRole('button', { name: /^Logs/ })).toBeVisible();
    fireEvent.click(within(grafana).getByRole('button', { name: /^State/ }));
    const observation = screen.getByRole('region', { name: 'Evidence observation' });
    expect(observation).toHaveTextContent('monitoring-grafana-1');
    expect(observation).toHaveFocus();
  });

  it('opens the container observation when a status card references group evidence first', () => {
    const answer = demoAnswer('dependency');
    const status = answer.widgets.find((row) => row.widget_type === 'container_status')!;
    const state = answer.evidence.find((row) => row.kind === 'container')!;
    const stack = answer.evidence.find((row) => row.kind === 'stack')!;
    const inspect = vi.fn();
    render(
      <WidgetCard
        widget={{ ...status, evidence_ids: [stack.id, state.id] }}
        evidence={answer.evidence}
        selected={null}
        inspect={inspect}
        review={() => undefined}
        outcomes={{}}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'View container status source' }));
    expect(inspect).toHaveBeenCalledWith(state.id);
  });
  it('keeps local-container log outcomes visible beside Swarm service members', () => {
    const answer = demoAnswer('dependency');
    const log = answer.evidence.find((row) => row.kind === 'logs')!;
    const stack = answer.evidence.find((row) => row.kind === 'stack')!;
    const inspect = vi.fn();
    render(
      <LocaleProvider>
        <GroupReport
          evidence={answer.evidence}
          inspect={inspect}
          report={{
            evidence_id: stack.id,
            inventory_code: null,
            summary: {
              name: 'infra',
              kind: 'swarm',
              total: 3,
              running: 1,
              container_ids: [log.container_id!],
              members: [
                {
                  id: 'service-1',
                  name: 'infra_api',
                  kind: 'service',
                  state: 'degraded',
                  total: 3,
                  running: 1,
                  exit_code: null,
                },
              ],
            },
            logs: [
              {
                container_id: log.container_id!,
                name: 'api-task-1',
                state: 'collected',
                evidence_id: log.id,
                code: null,
              },
              {
                container_id: 'b'.repeat(64),
                name: 'api-task-2',
                state: 'failed',
                evidence_id: null,
                code: 'runtime_unavailable',
              },
            ],
          }}
        />
      </LocaleProvider>,
    );
    expect(screen.getByText('api-task-2')).toBeInTheDocument();
    expect(screen.getByText('Log read failed')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Logs' }));
    expect(inspect).toHaveBeenCalledWith(log.id);
    expect(within(screen.getByRole('region', { name: 'Group observations' })).getByText('infra_api')).toBeVisible();
  });
  it('rejects a cause assessment with nonexistent evidence', () => {
    const answer = demoAnswer('dependency');
    expect(
      answerSchema.safeParse({
        ...answer,
        cause: { immediate: 'Connection failed', underlying: null, unknowns: [], evidence_ids: ['invented'] },
      }).success,
    ).toBe(false);
  });
  it('discovers explicit Compose membership without invoking diagnosis', async () => {
    const client = new DemoClient();
    const { result } = renderHook(() => useGroups(client, 'demo-eu'));
    expect(result.current.kind).toBe('all');
    act(() => result.current.changeKind('compose'));
    await waitFor(() => expect(result.current.groups).toHaveLength(1));
    expect(result.current.groups[0]!.name).toBe('commerce');
    expect(result.current.group).toBeUndefined();
    act(() => result.current.choose('commerce'));
    expect(result.current.group?.container_ids).toHaveLength(6);
    act(() => result.current.changeKind('all'));
    expect(result.current.group).toBeUndefined();
  });
});
