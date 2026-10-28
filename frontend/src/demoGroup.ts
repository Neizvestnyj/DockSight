import { answerSchema, type Answer, type Container, type Stack } from './contracts';

/** Build an explicitly partial group simulation using existing fixture evidence and original log text. */
export function demoGroupAnswer(answer: Answer, inventory: Container[], summary: Stack): Answer {
  const stack = answer.evidence.find((row) => row.kind === 'stack')!;
  const logs = answer.evidence.find((row) => row.kind === 'logs')!;
  const problems = inventory.filter((row) => row.state !== 'running');
  return answerSchema.parse({
    ...answer,
    summary:
      'The project has several affected containers. checkout-api failed to connect to its database. Other member states are shown below; their logs were not collected in this simulated turn.',
    uncertain: true,
    cause: {
      immediate: 'checkout-api failed during startup because its database connection was refused.',
      underlying: null,
      unknowns: ['Why the database connection was refused, and why the other affected members stopped.'],
      evidence_ids: [logs.id],
    },
    evidence: answer.evidence.map((row) => (row.id === stack.id ? { ...row, data: { stacks: [summary] } } : row)),
    group: {
      summary,
      evidence_id: stack.id,
      inventory_code: null,
      logs: problems.map((row) => ({
        container_id: row.id,
        name: row.name,
        state: row.id === logs.container_id ? 'collected' : 'not_collected',
        evidence_id: row.id === logs.container_id ? logs.id : null,
        code: row.id === logs.container_id ? null : 'group_log_limit',
      })),
    },
    widgets: answer.widgets.filter((row) => row.widget_type !== 'compose_stack' && row.widget_type !== 'env_inspector'),
  });
}
