import '@testing-library/jest-dom/vitest';
import { act, cleanup, fireEvent, render, renderHook, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { DemoClient } from './demo';
import { useGroups } from './useGroups';
import { answerSchema } from './contracts';
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
