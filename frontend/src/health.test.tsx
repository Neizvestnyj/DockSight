import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { containerSchema, stackSchema, type Container } from './contracts';
import { DemoClient, demoAnswer, demoContainer } from './demo';
import { GroupReport } from './GroupReport';
import { LocaleContext } from './locale';
import { translate, type Locale } from './messages';
import { WidgetCard } from './Widgets';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

/** Render an observed card in either layout and language without a live provider. */
function renderCard(
  health: 'healthy' | 'unhealthy' | 'starting' | null | undefined,
  embedded = false,
  locale: Locale = 'en',
  lifecycle?: Pick<Container, 'state' | 'exit_code'>,
) {
  const answer = demoAnswer('dependency');
  const original = answer.widgets.find((row) => row.widget_type === 'container_status')!;
  const widget = {
    ...original,
    actions: [],
    snapshot: { ...original.snapshot, state: 'running' as const, health, ...lifecycle },
  };
  return render(
    <LocaleContext
      value={{
        locale,
        preference: locale,
        setPreference: () => undefined,
        t: (key, values) => translate(locale, key, values),
      }}
    >
      <WidgetCard
        widget={widget}
        embedded={embedded}
        evidence={answer.evidence}
        selected={null}
        inspect={() => undefined}
        review={() => undefined}
        outcomes={{}}
      />
    </LocaleContext>,
  );
}

describe('container health observations', () => {
  it('accepts only reported health states while allowing null and older snapshots without health', () => {
    const snapshot = demoContainer(2, 'demo-eu', '2026-10-27T12:00:00Z');
    expect(containerSchema.safeParse(snapshot).success).toBe(true);
    for (const health of ['starting', 'healthy', 'unhealthy', null])
      expect(containerSchema.parse({ ...snapshot, health })).toHaveProperty('health', health);
    for (const health of ['none', 'running', '', 1, { Status: 'healthy' }])
      expect(containerSchema.safeParse({ ...snapshot, health }).success).toBe(false);
  });

  it('validates Compose member health without requiring it from older servers', () => {
    const member = {
      id: 'a'.repeat(64),
      name: 'api',
      kind: 'container',
      state: 'running',
      total: 1,
      running: 1,
      exit_code: 0,
    };
    const stack = { name: 'app', kind: 'compose', total: 1, running: 1, container_ids: [member.id], members: [member] };
    expect(stackSchema.safeParse(stack).success).toBe(true);
    for (const health of ['starting', 'healthy', 'unhealthy', null])
      expect(stackSchema.parse({ ...stack, members: [{ ...member, health }] }).members?.[0]).toHaveProperty(
        'health',
        health,
      );
    expect(stackSchema.safeParse({ ...stack, members: [{ ...member, health: 'ready' }] }).success).toBe(false);
  });

  it.each([false, true])('shows a running unhealthy card with a distinct failure signal (embedded=%s)', (embedded) => {
    const { container } = renderCard('unhealthy', embedded);
    expect(screen.getByText('running', { exact: true })).toBeVisible();
    expect(screen.getByText('Unhealthy')).toBeVisible();
    expect(screen.getByText('Unhealthy')).toHaveClass('negative');
    expect(screen.getByText('Healthcheck').nextElementSibling).toHaveTextContent('Unhealthy');
    const heading = container.querySelector(embedded ? '.widget-head' : '.container-heading')!;
    expect(within(heading as HTMLElement).queryByText('Unhealthy')).not.toBeInTheDocument();
    expect(container.querySelectorAll('.actions button')).toHaveLength(0);
  });

  it.each([
    ['healthy', 'Healthy', 'positive'],
    ['starting', 'Starting', 'warning'],
    [null, 'Not reported', 'neutral'],
    [undefined, 'Not reported', 'neutral'],
  ] as const)('presents health %s honestly', (health, label, tone) => {
    renderCard(health);
    expect(screen.getByText(label)).toBeVisible();
    expect(screen.getByText(label)).toHaveClass(tone);
  });

  it.each([
    ['healthy', 'В норме'],
    ['unhealthy', 'Сбой'],
    ['starting', 'Проверяется'],
    [null, 'Нет данных'],
  ] as const)('localizes health %s without translating external observations', (health, label) => {
    renderCard(health, true, 'ru');
    expect(screen.getByText(label)).toBeVisible();
    expect(screen.getByText(label)).toHaveAttribute('title', 'Проверка здоровья Docker');
    expect(screen.getByText('ghcr.io/northstar/checkout:3.2.4')).toBeVisible();
  });

  it.each([false, true])('separates a stopped process from its last healthcheck (embedded=%s)', (embedded) => {
    const { container } = renderCard('unhealthy', embedded, 'ru', { state: 'exited', exit_code: 0 });
    const heading = container.querySelector(embedded ? '.widget-head' : '.container-heading')!;
    expect(within(heading as HTMLElement).getByText('завершён')).toHaveClass('neutral');
    expect(within(heading as HTMLElement).queryByText('Сбой')).not.toBeInTheDocument();
    expect(screen.getByText('Последняя проверка').nextElementSibling).toHaveTextContent('Сбой');
    expect(screen.getByText('Сбой')).toHaveClass('negative');
  });

  it.each([0, 1])('distinguishes exit code %s from a neutral exited process', (exit_code) => {
    renderCard(null, true, 'en', { state: 'exited', exit_code });
    expect(screen.getByText('exited', { exact: true })).toHaveClass('neutral');
    const exit = screen.getByText('Exit code').nextElementSibling;
    expect(exit).toHaveTextContent(String(exit_code));
    if (exit_code) expect(exit).toHaveClass('negative');
    else expect(exit).not.toHaveClass('negative');
    expect(screen.getByText('Last healthcheck').nextElementSibling).toHaveTextContent('Not reported');
  });

  it('shows the same running unhealthy observation in inventory and direct container facts', async () => {
    const snapshot = {
      ...demoContainer(2, 'demo-eu', '2026-10-27T12:00:00Z'),
      state: 'running' as const,
      health: 'unhealthy' as const,
    };
    vi.spyOn(DemoClient.prototype, 'containers').mockResolvedValue([snapshot]);
    vi.spyOn(DemoClient.prototype, 'container').mockResolvedValue(snapshot);
    render(<App />);
    const row = await screen.findByTitle(snapshot.name);
    expect(within(row).getByText('Unhealthy')).toBeVisible();
    expect(within(row).getByText('Healthcheck')).toBeVisible();
    fireEvent.click(row);
    const facts = await screen.findByRole('region', { name: 'Container facts' });
    expect(await within(facts).findByText('Unhealthy')).toBeVisible();
    expect(within(facts).getByText('running', { exact: true })).toBeVisible();
  });

  it('keeps failed exits distinguishable from normal completion in compact inventory', async () => {
    const failed = {
      ...demoContainer(2, 'demo-eu', '2026-10-27T12:00:00Z'),
      state: 'exited' as const,
      exit_code: 1,
      health: null,
    };
    const completed = { ...failed, id: 'b'.repeat(64), name: 'batch-completed', exit_code: 0 };
    vi.spyOn(DemoClient.prototype, 'containers').mockResolvedValue([failed, completed]);
    render(<App />);
    const failedRow = await screen.findByTitle(failed.name);
    expect(within(failedRow).getByText('exited', { exact: true })).toHaveClass('neutral');
    expect(within(failedRow).getByText('Exit code 1')).toHaveClass('negative');
    const completedRow = screen.getByTitle(completed.name);
    expect(within(completedRow).getByText('exited', { exact: true })).toHaveClass('neutral');
    expect(within(completedRow).queryByText('Exit code 0')).not.toBeInTheDocument();
  });

  it('retains running totals while showing unhealthy Compose members and unknown health', () => {
    render(
      <GroupReport
        evidence={[]}
        inspect={() => undefined}
        report={{
          evidence_id: 'stack',
          summary: {
            name: 'app',
            kind: 'compose',
            total: 2,
            running: 2,
            container_ids: ['a', 'b'],
            members: [
              {
                id: 'a',
                name: 'api',
                kind: 'container',
                state: 'running',
                total: 1,
                running: 1,
                exit_code: 0,
                health: 'unhealthy',
              },
              { id: 'b', name: 'db', kind: 'container', state: 'running', total: 1, running: 1, exit_code: 0 },
            ],
          },
          logs: [],
        }}
      />,
    );
    expect(screen.getByText('Unhealthy')).toHaveClass('negative');
    expect(screen.getByText('Not reported')).toBeVisible();
    expect(screen.getByText('containers running').parentElement).toHaveTextContent('2 / 2');
  });
});
