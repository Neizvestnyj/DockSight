import type { Answer, Evidence, Widget } from './contracts';

export const evidenceNames = {
  container: 'State',
  logs: 'Logs',
  env: 'Env',
  stats: 'Metrics',
  stack: 'Stack',
} as const;

/** Resolve resource identity from the retained answer rather than a changing live inventory. */
export function evidenceResource(row: Evidence, answer: Answer): { key: string; name: string } {
  if (row.container_id) {
    const card = answer.widgets.find(
      (widget) => widget.widget_type === 'container_status' && widget.snapshot.id === row.container_id,
    );
    const snapshot = answer.evidence.find(
      (item) =>
        item.kind === 'container' && item.container_id === row.container_id && typeof item.data.name === 'string',
    );
    const name =
      card?.widget_type === 'container_status'
        ? card.snapshot.name
        : typeof snapshot?.data.name === 'string'
          ? snapshot.data.name
          : answer.group?.logs.find((item) => item.container_id === row.container_id)?.name;
    return { key: `${row.host}/${row.container_id}`, name: name ?? `${row.container_id.slice(0, 12)}…` };
  }
  const stacks = row.kind === 'stack' && Array.isArray(row.data.stacks) ? row.data.stacks : [];
  const names = stacks.flatMap((item) =>
    item && typeof item === 'object' && 'name' in item && typeof item.name === 'string'
      ? [`${'kind' in item && item.kind === 'swarm' ? 'Swarm' : 'Compose'} / ${item.name}`]
      : [],
  );
  return {
    key: `${row.host}/${row.kind}/${[...names].sort().join('|')}`,
    name: names.length ? names.join(' · ') : row.host,
  };
}

/** Open the source matching the widget, independent of model reference order. */
export function widgetSource(widget: Widget, evidence: Evidence[]): string | undefined {
  const kind = {
    container_status: 'container',
    log_anomalies: 'logs',
    compose_stack: 'stack',
    env_inspector: 'env',
  }[widget.widget_type];
  const refs = evidence.filter((row) => widget.evidence_ids.includes(row.id));
  return (refs.find((row) => row.kind === kind) ?? refs.find((row) => row.container_id) ?? refs[0])?.id;
}
