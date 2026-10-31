import { z } from 'zod';
import type { ModelCatalog, ModelProviders, ModelSelection, ProviderId } from './model-contracts';

export const metricsSchema = z.object({
  cpu_percent: z.number().nullable(),
  memory_usage_bytes: z.number().nullable(),
  memory_limit_bytes: z.number().nullable(),
});
const containerHealthSchema = z.enum(['starting', 'healthy', 'unhealthy']).nullish();
export const containerSchema = z.object({
  host: z.string(),
  id: z.string(),
  name: z.string(),
  image: z.string(),
  state: z.enum(['created', 'running', 'paused', 'restarting', 'removing', 'exited', 'dead']),
  exit_code: z.number().int(),
  oom_killed: z.boolean(),
  restart_count: z.number().int().nonnegative(),
  started_at: z.string().nullable(),
  observed_at: z.string(),
  metrics: metricsSchema,
  environment: z.array(z.tuple([z.string(), z.string()])),
  compose_project: z.string().nullable(),
  health: containerHealthSchema,
});
export const actionSchema = z.object({
  id: z.string(),
  host: z.string(),
  container_id: z.string(),
  operation: z.enum(['restart', 'stop']),
  expires_at: z.string(),
  state: z.enum(['prepared', 'running', 'succeeded', 'failed', 'expired', 'indeterminate']),
  message: z.string(),
  confirmation_required: z.literal(true),
});
export const logSchema = z.object({
  entries: z.array(z.object({ message: z.string(), timestamp: z.string().nullable() })),
  truncated: z.boolean(),
});
export const groupTargetSchema = z.strictObject({
  kind: z.enum(['compose', 'swarm']),
  name: z
    .string()
    .min(1)
    .max(128)
    .regex(/^[a-zA-Z0-9][a-zA-Z0-9_.-]*$/),
});
export const containerTargetSchema = z.strictObject({
  kind: z.literal('container'),
  id: z.string().regex(/^[a-f0-9]{64}$/),
  name: z.string().min(1).max(256),
});
export const diagnosticTargetSchema = z.union([groupTargetSchema, containerTargetSchema]);
export const targetSelectionSchema = z.strictObject({
  candidates: z
    .array(diagnosticTargetSchema)
    .min(1)
    .max(32)
    .refine((rows) => new Set(rows.map(targetKey)).size === rows.length, 'Target candidates must be distinct.'),
});
export const stackSchema = z.object({
  name: z.string(),
  kind: z.enum(['compose', 'swarm']),
  total: z.number().int().nonnegative(),
  running: z.number().int().nonnegative(),
  container_ids: z.array(z.string()),
  members: z
    .array(
      z.object({
        id: z.string(),
        name: z.string(),
        kind: z.enum(['container', 'service']),
        state: z.string(),
        total: z.number().int().nonnegative(),
        running: z.number().int().nonnegative(),
        exit_code: z.number().int().nullable(),
        health: containerHealthSchema,
      }),
    )
    .max(200)
    .optional(),
  truncated: z.boolean().optional(),
});
const causeSchema = z.strictObject({
  immediate: z.string().min(1).max(600),
  underlying: z.string().min(1).max(600).nullable(),
  unknowns: z.array(z.string().min(1).max(240)).max(4),
  evidence_ids: z.array(z.string()).min(1).max(10),
});
export const groupInspectionSchema = z.strictObject({
  summary: stackSchema,
  evidence_id: z.string(),
  inventory_code: z.string().nullable().optional(),
  logs: z
    .array(
      z.strictObject({
        container_id: z.string(),
        name: z.string(),
        state: z.enum(['collected', 'failed', 'not_collected']),
        evidence_id: z.string().nullable(),
        code: z.string().nullable(),
      }),
    )
    .max(200),
});
const hostMemberSchema = z.strictObject({
  container_id: z.string().regex(/^[a-f0-9]{64}$/),
  name: z.string().min(1).max(4096),
  state: containerSchema.shape.state,
  health: containerHealthSchema.nonoptional(),
  exit_code: z.number().int(),
  oom_killed: z.boolean(),
  restart_count: z.number().int().nonnegative(),
  observed_at: z.iso.datetime({ offset: true }),
  group: groupTargetSchema.nullable(),
  attention: z.boolean(),
});
export const hostOverviewSchema = z
  .strictObject({
    host: z.string().min(1).max(64),
    evidence_id: z.string().min(1).max(128),
    total: z.number().int().min(0).max(200),
    running: z.number().int().min(0).max(200),
    attention: z.number().int().min(0).max(200),
    truncated: z.boolean(),
    discovery_code: z.string().min(1).max(64).nullable(),
    members: z.array(hostMemberSchema).max(32),
    targets: z.array(groupTargetSchema).max(32),
    logs: z.array(groupInspectionSchema.shape.logs.element).max(32),
  })
  .superRefine((overview, context) => {
    const members = new Set(overview.members.map((row) => row.container_id));
    const targets = new Set(overview.targets.map(targetKey));
    const logs = new Set(overview.logs.map((row) => row.container_id));
    if (
      members.size !== overview.members.length ||
      targets.size !== overview.targets.length ||
      logs.size !== overview.logs.length
    )
      context.addIssue({ code: 'custom', message: 'Host overview resources must be distinct.' });
    if (overview.running > overview.total || overview.attention > overview.total || members.size > overview.total)
      context.addIssue({ code: 'custom', message: 'Host overview counts exceed observed containers.' });
    if (
      overview.members.filter((row) => row.state === 'running').length > overview.running ||
      overview.members.filter((row) => row.attention).length > overview.attention
    )
      context.addIssue({ code: 'custom', message: 'Displayed members exceed host overview counts.' });
    if (overview.members.some((row) => row.group && !targets.has(targetKey(row.group))))
      context.addIssue({ code: 'custom', path: ['targets'], message: 'Member group is outside discovered targets.' });
    if (overview.logs.some((row) => !members.has(row.container_id)))
      context.addIssue({ code: 'custom', path: ['logs'], message: 'Log coverage is outside displayed members.' });
  });
const references = { evidence_ids: z.array(z.string()) };
export const widgetSchema = z.discriminatedUnion('widget_type', [
  z
    .object({
      widget_type: z.literal('container_status'),
      snapshot: containerSchema,
      actions: z.array(actionSchema),
      actions_code: z
        .string()
        .min(1)
        .max(64)
        .regex(/^[a-z][a-z0-9_]*$/)
        .nullish(),
      recommendation: z
        .object({ action_id: z.string().min(1).max(128), reason: z.string().min(1).max(240).nullable() })
        .strict()
        .nullish(),
      ...references,
    })
    .superRefine((card, context) => {
      if (card.actions_code && card.actions.length)
        context.addIssue({ code: 'custom', path: ['actions'], message: 'Unavailable actions expose executable IDs.' });
      if (
        card.recommendation &&
        !card.actions.some(
          (action) =>
            action.id === card.recommendation!.action_id &&
            action.host === card.snapshot.host &&
            action.container_id === card.snapshot.id,
        )
      )
        context.addIssue({
          code: 'custom',
          path: ['recommendation'],
          message: 'Recommendation is outside the prepared card actions.',
        });
    }),
  z.object({
    widget_type: z.literal('log_anomalies'),
    host: z.string(),
    container_id: z.string(),
    logs: logSchema,
    ...references,
  }),
  z.object({ widget_type: z.literal('compose_stack'), host: z.string(), stacks: z.array(stackSchema), ...references }),
  z.object({
    widget_type: z.literal('env_inspector'),
    host: z.string(),
    container_id: z.string(),
    variables: z.record(z.string(), z.string()),
    read_only: z.literal(true),
    ...references,
  }),
]);
export const evidenceSchema = z.object({
  id: z.string(),
  kind: z.enum(['container', 'logs', 'stats', 'stack', 'env', 'host']),
  host: z.string(),
  container_id: z.string().nullable(),
  observed_at: z.string(),
  container_name: z.string().nullish(),
  data: z.record(z.string(), z.unknown()),
});
export const answerSchema = z
  .object({
    schema_version: z.literal(1),
    summary: z.string(),
    uncertain: z.boolean(),
    cause: causeSchema.nullish(),
    group: groupInspectionSchema.nullish(),
    host_overview: hostOverviewSchema.nullish(),
    evidence: z.array(evidenceSchema),
    widgets: z.array(widgetSchema).max(16),
  })
  .superRefine((answer, context) => {
    const byId = new Map(answer.evidence.map((row) => [row.id, row]));
    if (answer.cause?.evidence_ids.some((id) => !byId.has(id)))
      context.addIssue({ code: 'custom', path: ['cause'], message: 'Cause references unavailable evidence.' });
    if (answer.host_overview) {
      const overview = answer.host_overview;
      const source = byId.get(overview.evidence_id);
      if (source?.kind !== 'host' || source.host !== overview.host || source.container_id !== null)
        context.addIssue({
          code: 'custom',
          path: ['host_overview'],
          message: 'Host overview requires scoped host evidence.',
        });
      for (const row of overview.logs) {
        if (row.state !== 'collected') continue;
        const log = row.evidence_id ? byId.get(row.evidence_id) : undefined;
        if (log?.kind !== 'logs' || log.container_id !== row.container_id || log.host !== overview.host)
          context.addIssue({
            code: 'custom',
            path: ['host_overview', 'logs'],
            message: 'Log coverage is outside its host scope.',
          });
      }
    }
    if (!answer.group) return;
    const source = byId.get(answer.group.evidence_id);
    if (source?.kind !== 'stack')
      context.addIssue({ code: 'custom', path: ['group'], message: 'Group requires stack evidence.' });
    for (const row of answer.group.logs) {
      if (row.state !== 'collected') continue;
      const log = row.evidence_id ? byId.get(row.evidence_id) : undefined;
      if (log?.kind !== 'logs' || log.container_id !== row.container_id || log.host !== source?.host)
        context.addIssue({
          code: 'custom',
          path: ['group', 'logs'],
          message: 'Log coverage is outside its evidence scope.',
        });
    }
  });
const envelope = { schema_version: z.literal(1), request_id: z.string(), turn_id: z.string() };
export const traceStepSchema = z
  .object({
    id: z.string().min(1).max(16),
    kind: z.enum(['model', 'tool', 'validation']),
    operation: z.string().min(1).max(128),
    state: z.enum(['running', 'succeeded', 'failed']),
    started_at: z.iso.datetime({ offset: true }),
    finished_at: z.iso.datetime({ offset: true }).nullable(),
    duration_ms: z.number().int().nonnegative().nullable(),
    input_tokens: z.number().int().nonnegative().nullable(),
    output_tokens: z.number().int().nonnegative().nullable(),
    code: z.string().max(64).nullable(),
    issues: z
      .array(
        z
          .object({ type: z.string().max(64), loc: z.array(z.union([z.string().max(64), z.number().int()])).max(8) })
          .strict(),
      )
      .max(8),
    response: z.string().max(16_384).nullable(),
    response_truncated: z.boolean(),
  })
  .strict();
export const eventSchema = z.discriminatedUnion('type', [
  z.object({ ...envelope, type: z.literal('turn.started'), session_id: z.string().uuid() }),
  z
    .object({
      ...envelope,
      type: z.literal('trace.started'),
      provider: z.string().max(32).nullable(),
      model: z.string().max(256).nullable(),
      started_at: z.iso.datetime({ offset: true }),
    })
    .strict(),
  z.object({ ...envelope, type: z.literal('trace.step'), step: traceStepSchema }).strict(),
  z.object({ ...envelope, type: z.literal('tool.started'), tool: z.string() }),
  z.object({ ...envelope, type: z.literal('tool.completed'), tool: z.string(), ok: z.boolean() }),
  z.object({ ...envelope, type: z.literal('answer.ready'), answer: answerSchema }),
  z.strictObject({ ...envelope, type: z.literal('clarification.required'), selection: targetSelectionSchema }),
  z.object({ ...envelope, type: z.literal('turn.completed') }),
  z.object({
    ...envelope,
    turn_id: z.string().nullable(),
    type: z.literal('turn.failed'),
    code: z.string(),
    message: z.string(),
  }),
]);
export const hostsSchema = z.array(z.object({ id: z.string(), name: z.string() }));
export const checkStateSchema = z.enum(['available', 'unavailable', 'not_checked']);
export const checkCodeSchema = z.enum([
  'ok',
  'host_not_selected',
  'timeout',
  'connection_failed',
  'runtime_unavailable',
  'credentials_rejected',
  'metadata_forbidden',
  'unsupported',
  'model_not_found',
  'model_not_listed',
  'rate_limited',
  'upstream_error',
  'invalid_response',
  'probe_not_configured',
  'check_failed',
  'provider_unavailable',
]);
const dependencyCheckSchema = z.strictObject({
  state: checkStateSchema,
  code: checkCodeSchema,
  message: z.string().max(256),
  checked_at: z.iso.datetime({ offset: true }),
});
export const systemStatusSchema = z.strictObject({
  schema_version: z.literal(1),
  host: z.string().max(64).nullable(),
  provider: z.enum(['ollama', 'openai', 'anthropic', 'compatible', 'gemini']),
  model: z.string().min(1).max(256),
  docker: dependencyCheckSchema,
  provider_check: dependencyCheckSchema,
  model_check: dependencyCheckSchema,
});
export type CheckState = z.infer<typeof checkStateSchema>;
export type CheckCode = z.infer<typeof checkCodeSchema>;
export type DependencyCheck = z.infer<typeof dependencyCheckSchema>;
export type SystemStatus = z.infer<typeof systemStatusSchema>;
export type Host = z.infer<typeof hostsSchema>[number];
export type Container = z.infer<typeof containerSchema>;
export type Metrics = z.infer<typeof metricsSchema>;
export type LogBatch = z.infer<typeof logSchema>;
export type Action = z.infer<typeof actionSchema>;
export type Widget = z.infer<typeof widgetSchema>;
export type Evidence = z.infer<typeof evidenceSchema>;
export type Answer = z.infer<typeof answerSchema>;
export type GroupTarget = z.infer<typeof groupTargetSchema>;
export type DiagnosticTarget = z.infer<typeof diagnosticTargetSchema>;
export type TargetSelection = z.infer<typeof targetSelectionSchema>;
export type Stack = z.infer<typeof stackSchema>;
export type GroupInspection = z.infer<typeof groupInspectionSchema>;
export type HostOverview = z.infer<typeof hostOverviewSchema>;
export type TurnEvent = z.infer<typeof eventSchema>;
export type TraceStep = z.infer<typeof traceStepSchema>;
export interface TurnInput {
  host: string;
  query: string;
  session_id?: string;
  group?: GroupTarget;
  container_id?: string;
  model_selection?: ModelSelection;
}

/** Compare containers by exact identity and groups by their observed namespace and name. */
export function targetKey(target: DiagnosticTarget): string {
  return `${target.kind}:${target.kind === 'container' ? target.id : target.name}`;
}
export interface Transport {
  systemStatus(host: string | null, signal: AbortSignal, selection?: ModelSelection): Promise<SystemStatus>;
  modelProviders(signal: AbortSignal): Promise<ModelProviders>;
  models(provider: ProviderId, signal: AbortSignal, refresh?: boolean): Promise<ModelCatalog>;
  hosts(signal: AbortSignal): Promise<Host[]>;
  containers(host: string, signal: AbortSignal): Promise<Container[]>;
  stacks(host: string, kind: GroupTarget['kind'], signal: AbortSignal): Promise<Stack[]>;
  container(host: string, id: string, signal: AbortSignal): Promise<Container>;
  logs(host: string, id: string, signal: AbortSignal): Promise<LogBatch>;
  stats(host: string, id: string, signal: AbortSignal): Promise<Metrics>;
  diagnose(input: TurnInput, receive: (event: TurnEvent) => void, signal: AbortSignal): Promise<void>;
  action(id: string): Promise<Action>;
  execute(id: string, key: string): Promise<Action>;
}
