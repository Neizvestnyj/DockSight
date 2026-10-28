import { z } from 'zod';

export const metricsSchema = z.object({
  cpu_percent: z.number().nullable(),
  memory_usage_bytes: z.number().nullable(),
  memory_limit_bytes: z.number().nullable(),
});
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
const stackSchema = z.object({
  name: z.string(),
  kind: z.enum(['compose', 'swarm']),
  total: z.number().int().nonnegative(),
  running: z.number().int().nonnegative(),
  container_ids: z.array(z.string()),
});
const references = { evidence_ids: z.array(z.string()) };
export const widgetSchema = z.discriminatedUnion('widget_type', [
  z.object({
    widget_type: z.literal('container_status'),
    snapshot: containerSchema,
    actions: z.array(actionSchema),
    ...references,
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
  kind: z.enum(['container', 'logs', 'stats', 'stack', 'env']),
  host: z.string(),
  container_id: z.string().nullable(),
  observed_at: z.string(),
  data: z.record(z.string(), z.unknown()),
});
export const answerSchema = z.object({
  schema_version: z.literal(1),
  summary: z.string(),
  uncertain: z.boolean(),
  evidence: z.array(evidenceSchema),
  widgets: z.array(widgetSchema).max(8),
});
const envelope = { schema_version: z.literal(1), request_id: z.string(), turn_id: z.string() };
export const eventSchema = z.discriminatedUnion('type', [
  z.object({ ...envelope, type: z.literal('turn.started'), session_id: z.string().uuid() }),
  z.object({ ...envelope, type: z.literal('tool.started'), tool: z.string() }),
  z.object({ ...envelope, type: z.literal('tool.completed'), tool: z.string(), ok: z.boolean() }),
  z.object({ ...envelope, type: z.literal('answer.ready'), answer: answerSchema }),
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
  provider: z.enum(['ollama', 'openai', 'anthropic', 'compatible']),
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
export type TurnEvent = z.infer<typeof eventSchema>;
export interface TurnInput {
  host: string;
  query: string;
  session_id?: string;
}
export interface Transport {
  systemStatus(host: string | null, signal: AbortSignal): Promise<SystemStatus>;
  hosts(signal: AbortSignal): Promise<Host[]>;
  containers(host: string, signal: AbortSignal): Promise<Container[]>;
  container(host: string, id: string, signal: AbortSignal): Promise<Container>;
  logs(host: string, id: string, signal: AbortSignal): Promise<LogBatch>;
  stats(host: string, id: string, signal: AbortSignal): Promise<Metrics>;
  diagnose(input: TurnInput, receive: (event: TurnEvent) => void, signal: AbortSignal): Promise<void>;
  action(id: string): Promise<Action>;
  execute(id: string, key: string): Promise<Action>;
}
