import type { Answer, Evidence, Widget } from './contracts';

export const evidenceNames = {
  container: 'State',
  logs: 'Logs',
  env: 'Env',
  stats: 'Metrics',
  stack: 'Stack',
  host: 'Host overview',
} as const;

/** Resolve resource identity from the retained answer rather than a changing live inventory. */
export function evidenceResource(row: Evidence, answer: Answer): { key: string; name: string } {
  if (row.container_id) {
    const card = answer.widgets.find(
      (widget) =>
        widget.widget_type === 'container_status' &&
        widget.snapshot.id === row.container_id &&
        widget.snapshot.host === row.host,
    );
    const snapshot = answer.evidence.find(
      (item) =>
        item.kind === 'container' &&
        item.host === row.host &&
        item.container_id === row.container_id &&
        typeof item.data.name === 'string',
    );
    const name =
      row.container_name ??
      (card?.widget_type === 'container_status'
        ? card.snapshot.name
        : typeof snapshot?.data.name === 'string'
          ? snapshot.data.name
          : (answer.group?.logs.find((item) => item.container_id === row.container_id)?.name ??
            answer.host_overview?.members.find((item) => item.container_id === row.container_id)?.name));
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

export interface ContainerWidgetGroup {
  key: string;
  host: string;
  id: string;
  name: string;
  widgets: Exclude<Widget, { widget_type: 'compose_stack' }>[];
}

/** Group one retained answer by exact resource, keeping every observation and its original values. */
export function containerWidgetGroups(answer: Answer): ContainerWidgetGroup[] {
  const groups = new Map<string, ContainerWidgetGroup>();
  for (const widget of answer.widgets) {
    if (widget.widget_type === 'compose_stack') continue;
    const { host, id } =
      widget.widget_type === 'container_status' ? widget.snapshot : { host: widget.host, id: widget.container_id };
    const key = JSON.stringify([host, id]);
    const source = answer.evidence.find((row) => row.host === host && row.container_id === id);
    const name =
      widget.widget_type === 'container_status'
        ? widget.snapshot.name
        : source
          ? evidenceResource(source, answer).name
          : `${id.slice(0, 12)}…`;
    const group = groups.get(key) ?? { key, host, id, name, widgets: [] };
    group.widgets.push(widget);
    groups.set(key, group);
  }
  const order = { container_status: 0, log_anomalies: 1, env_inspector: 2 };
  for (const group of groups.values()) group.widgets.sort((a, b) => order[a.widget_type] - order[b.widget_type]);
  return [...groups.values()];
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
