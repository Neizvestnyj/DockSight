import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { demoAnswer } from './demo';
import { widgetSchema } from './contracts';
import { WidgetCard } from './Widgets';

afterEach(cleanup);

describe('model recommendations and available operations', () => {
  it('keeps ordinary operations behind Actions and opens only the existing exact action for review', () => {
    const answer = demoAnswer('running', 'local');
    const widget = answer.widgets.find((row) => row.widget_type === 'container_status')!;
    const review = vi.fn();
    render(
      <WidgetCard
        widget={widget}
        evidence={answer.evidence}
        selected={null}
        inspect={() => undefined}
        review={review}
        outcomes={{}}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Review restart' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Review stop' })).toBeNull();
    const summary = screen.getByText('Actions', { exact: true });
    fireEvent.click(summary);
    fireEvent.click(screen.getByRole('button', { name: 'Review stop' }));
    expect(review).toHaveBeenCalledWith(widget.actions.find((action) => action.operation === 'stop'));
    expect(summary.closest('details')?.open).toBe(false);
    expect(document.activeElement).toBe(summary);
  });

  it('keeps only the explicitly recommended action visible and links its model reason to evidence', () => {
    const answer = demoAnswer('running', 'local');
    const widget = answer.widgets.find((row) => row.widget_type === 'container_status')!;
    const action = widget.actions.find((row) => row.operation === 'stop')!;
    const inspect = vi.fn();
    const review = vi.fn();
    render(
      <WidgetCard
        widget={{ ...widget, recommendation: { action_id: action.id, reason: 'Pause the worker for maintenance.' } }}
        evidence={answer.evidence}
        selected={null}
        inspect={inspect}
        review={review}
        outcomes={{}}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Review stop' }));
    expect(review).toHaveBeenCalledWith(action);
    expect(screen.queryByRole('button', { name: 'Review restart' })).toBeNull();
    expect(screen.getByText('Pause the worker for maintenance.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Supporting evidence' }));
    expect(inspect).toHaveBeenCalledWith(widget.evidence_ids[0]);
  });

  it('rejects a recommendation that does not reference an action on the card', () => {
    const widget = demoAnswer('running').widgets.find((row) => row.widget_type === 'container_status')!;
    expect(widgetSchema.safeParse({ ...widget, recommendation: { action_id: 'invented', reason: null } }).success).toBe(
      false,
    );
  });
});
