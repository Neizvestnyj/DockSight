import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { useState } from 'react';
import { answerSchema, type Answer, type TurnInput } from './contracts';
import { DemoClient, demoAnswer } from './demo';
import { Investigation } from './Investigation';
import { useInvestigation } from './useInvestigation';
import { hostAnswer } from '../tests/fixtures/host-overview';
import { LocaleProvider, LanguageSwitch } from './LocaleProvider';

afterEach(() => {
  cleanup();
  localStorage.clear();
});

/** Render the real draft and session hooks so narrowing exercises the transport boundary. */
function Workspace({ client, initial }: { client: DemoClient; initial?: Answer }) {
  const investigation = useInvestigation(client, 'local', initial);
  const [draft, setDraft] = useState('What happened?');
  return (
    <LocaleProvider>
      <LanguageSwitch />
      <Investigation
        investigation={investigation}
        client={client}
        demo={false}
        containers={[]}
        draft={draft}
        setDraft={setDraft}
        host="local"
      />
    </LocaleProvider>
  );
}

describe('host overview transport', () => {
  it('preserves a bounded overview and accepts old answers without the additive field', () => {
    expect(answerSchema.safeParse(demoAnswer('oom')).success).toBe(true);
    expect(answerSchema.parse({ ...demoAnswer('oom'), host_overview: null }).host_overview).toBeNull();
    expect(hostAnswer().host_overview?.members).toHaveLength(5);
  });

  it('rejects unsupported states, invalid resource identities, and oversized observations', () => {
    const answer = hostAnswer();
    const overview = answer.host_overview!;
    for (const change of [
      { total: 201 },
      { running: 8 },
      { attention: 8 },
      { total: -1 },
      { running: 1 },
      { attention: 3 },
      { members: Array.from({ length: 33 }, () => overview.members[0]) },
      { members: [{ ...overview.members[0], container_id: 'abc' }] },
      { members: [{ ...overview.members[0], health: 'ready' }] },
      { members: [{ ...overview.members[0], state: 'failed' }] },
      { members: [{ ...overview.members[0], observed_at: 'yesterday' }] },
      { members: [{ ...overview.members[0], name: 'a'.repeat(4097) }] },
      { targets: [{ kind: 'compose', name: '../foreign' }] },
    ])
      expect(answerSchema.safeParse({ ...answer, host_overview: { ...overview, ...change } }).success).toBe(false);
  });

  it('requires host evidence and exact same-host log references', () => {
    const answer = hostAnswer();
    for (const change of [{ kind: 'stack' }, { host: 'foreign' }, { container_id: 'a'.repeat(64) }])
      expect(
        answerSchema.safeParse({ ...answer, evidence: [{ ...answer.evidence[0], ...change }, answer.evidence[1]] })
          .success,
      ).toBe(false);
    for (const change of [{ kind: 'container' }, { host: 'foreign' }, { container_id: 'b'.repeat(64) }])
      expect(
        answerSchema.safeParse({ ...answer, evidence: [answer.evidence[0], { ...answer.evidence[1], ...change }] })
          .success,
      ).toBe(false);
    expect(answerSchema.safeParse({ ...answer, evidence: [] }).success).toBe(false);
  });

  it('rejects duplicate resources, coverage outside members, and undiscovered narrowing targets', () => {
    const answer = hostAnswer();
    const overview = answer.host_overview!;
    for (const change of [
      { members: [overview.members[0], overview.members[0]] },
      { targets: [overview.targets[0], overview.targets[0]] },
      { logs: [overview.logs[0], overview.logs[0]] },
      { logs: [{ ...overview.logs[1], container_id: 'f'.repeat(64) }] },
      { targets: [] },
    ])
      expect(answerSchema.safeParse({ ...answer, host_overview: { ...overview, ...change } }).success).toBe(false);
  });
});

describe('host overview presentation and narrowing', () => {
  it.each([
    ['model_context_limit', 'Контекстное окно модели заполнено.'],
    ['model_truncated', 'Ответ модели достиг лимита вывода.'],
  ])('localizes %s without attributing both failures to the output limit', async (code, message) => {
    const client = new DemoClient();
    client.diagnose = async (_input, receive) => {
      receive({
        schema_version: 1,
        request_id: 'r',
        turn_id: 't',
        type: 'turn.failed',
        code,
        message: 'Provider limit reached',
      });
    };
    render(<Workspace client={client} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Language' }), { target: { value: 'ru' } });
    fireEvent.click(screen.getByRole('button', { name: 'Исследовать' }));
    expect(await screen.findByText(new RegExp(message))).toBeVisible();
  });

  it('distinguishes an omitted preview from an empty host', () => {
    const answer = hostAnswer();
    answer.host_overview = { ...answer.host_overview!, members: [], logs: [] };
    render(<Workspace client={new DemoClient()} initial={answer} />);
    expect(screen.getByText('Container preview omitted by collection limits.')).toBeVisible();
    expect(screen.queryByText('No containers in this observation.')).not.toBeInTheDocument();
  });

  it('shows unavailable actions without hiding collected container facts', () => {
    const answer = demoAnswer('oom');
    answer.widgets = answer.widgets.map((card) =>
      card.widget_type === 'container_status'
        ? { ...card, actions: [], recommendation: null, actions_code: 'container_not_found' }
        : card,
    );
    render(<Workspace client={new DemoClient()} initial={answerSchema.parse(answer)} />);
    expect(screen.getByText(/Actions unavailable/)).toBeVisible();
    expect(screen.getByText('container_not_found')).toBeVisible();
    expect(screen.getByText('Exit code')).toBeVisible();
  });

  it('distinguishes observed counts, health, unknown grouping, and unread logs independently of cards', () => {
    render(<Workspace client={new DemoClient()} initial={hostAnswer()} />);
    const overview = screen.getByRole('region', { name: 'Host overview' });
    expect(within(overview).getByText('Observed containers').nextElementSibling).toHaveTextContent('7');
    expect(within(overview).getByText('Needs review', { selector: 'dt' }).nextElementSibling).toHaveTextContent('4');
    expect(within(overview).getByText('Unhealthy')).toBeVisible();
    expect(within(overview).getAllByText('No observed group')).toHaveLength(2);
    expect(within(overview).getByText('Log read failed')).toBeVisible();
    expect(within(overview).getAllByText('Collection limit reached')).toHaveLength(2);
    expect(within(overview).getByText('swarm_unavailable')).toBeVisible();
    expect(
      within(overview).getByText('Observation limits reached. More containers or group choices may exist.'),
    ).toBeVisible();
    fireEvent.click(within(overview).getByRole('button', { name: 'Source' }));
    expect(screen.getByRole('region', { name: 'Evidence observation' })).toHaveTextContent('Docker host inventory');
    expect(screen.getByRole('region', { name: 'Evidence observation' })).toHaveFocus();
    fireEvent.change(screen.getByRole('combobox', { name: 'Language' }), { target: { value: 'ru' } });
    expect(screen.getByRole('region', { name: 'Обзор хоста' })).toHaveTextContent('Сбой');
    expect(screen.getByRole('heading', { name: 'checkout-api' })).toBeVisible();
  });

  it.each(['container', 'compose', 'swarm'] as const)(
    'starts fresh %s turns and preserves the overview and unrelated draft',
    async (kind) => {
      const client = new DemoClient();
      const inputs: TurnInput[] = [];
      client.diagnose = async (input, receive) => {
        inputs.push(input);
        const base = { schema_version: 1 as const, request_id: 'r', turn_id: 't' };
        receive({ ...base, type: 'turn.started', session_id: '62f9fcc6-583e-4b3d-9678-10ffea8ae671' });
        receive({
          ...base,
          type: 'answer.ready',
          answer: inputs.length === 1 ? hostAnswer() : demoAnswer('oom', 'local'),
        });
        receive({ ...base, type: 'turn.completed' });
      };
      render(<Workspace client={client} />);
      fireEvent.click(screen.getByRole('button', { name: 'Investigate' }));
      const overview = await screen.findByRole('region', { name: 'Host overview' });
      fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Keep this unrelated draft' } });
      const choose = () =>
        kind === 'container'
          ? within(screen.getByRole('article', { name: 'checkout-api' })).getByRole('button', {
              name: 'Investigate container',
            })
          : within(screen.getByRole('region', { name: 'Host overview' })).getByRole('button', {
              name: kind === 'compose' ? 'Docker Compose commerce' : 'Docker Swarm infra',
            });
      fireEvent.click(choose());
      await screen.findByRole('region', { name: 'Container evidence: report-worker' });
      expect(overview).not.toBeInTheDocument();
      expect(inputs[1]?.session_id).toBeUndefined();
      expect(inputs[1]).toMatchObject(
        kind === 'container'
          ? { container_id: 'a'.repeat(64) }
          : { group: { kind, name: kind === 'compose' ? 'commerce' : 'infra' } },
      );
      expect(screen.getByRole('textbox')).toHaveValue('Keep this unrelated draft');
      fireEvent.click(screen.getByText('2 turns in this tab session'));
      fireEvent.click(screen.getByRole('button', { name: /What happened\?/ }));
      expect(screen.getByRole('region', { name: 'Host overview' })).toBeVisible();
      fireEvent.click(choose());
      await screen.findByText('3 turns in this tab session');
      expect(inputs[2]?.session_id).toBeUndefined();
      expect(screen.getByRole('textbox')).toHaveValue('Keep this unrelated draft');
    },
  );
});
