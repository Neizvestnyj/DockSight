import { z } from 'zod';
import {
  answerSchema,
  containerTargetSchema,
  diagnosticTargetSchema,
  targetSelectionSchema,
  traceStepSchema,
} from './contracts';
import { modelSelectionSchema } from './model-contracts';

const identifier = z.string().uuid();
const label = z.string().min(1).max(128);
const timestamp = z.iso.datetime({ offset: true });
export const revisionSchema = z.number().int().min(0).max(Number.MAX_SAFE_INTEGER);
export const browserSessionSchema = z.strictObject({
  actor: label,
  expires_at: timestamp,
  csrf_token: z.string().regex(/^[A-Za-z0-9_-]{43}$/),
});
export const investigationWorkspaceSchema = z.strictObject({
  revision: revisionSchema,
  draft: z.string().max(8000),
  target: diagnosticTargetSchema.nullable(),
  selected_container: containerTargetSchema.nullable(),
  view: z.enum(['diagnostics', 'containers']),
});
export const actorWorkspaceSchema = z.strictObject({
  revision: revisionSchema,
  last_investigation_id: identifier.nullable(),
  host: label.nullable(),
  model: modelSelectionSchema.nullable(),
});
const summaryFields = {
  id: identifier,
  host: label,
  title: z.string().max(120),
  created_at: timestamp,
  updated_at: timestamp,
  active_turn_id: identifier.nullable(),
  turn_count: z.number().int().min(0).max(200),
};
export const investigationSummarySchema = z.strictObject(summaryFields);
export const investigationViewSchema = z.strictObject({ ...summaryFields, workspace: investigationWorkspaceSchema });
export const savedTurnSchema = z.strictObject({
  schema_version: z.literal(1),
  id: identifier,
  investigation_id: identifier,
  actor: label,
  host: label,
  submission_id: identifier,
  request_id: label,
  query: z.string().min(1).max(8000),
  target: diagnosticTargetSchema.nullable(),
  model: modelSelectionSchema.nullable(),
  clarification_of: identifier.nullable(),
  resolved_by_turn_id: identifier.nullable(),
  state: z.enum(['running', 'completed', 'awaiting_selection', 'failed', 'stopped', 'interrupted']),
  revision: revisionSchema,
  created_at: timestamp,
  updated_at: timestamp,
  finished_at: timestamp.nullable(),
  progress: z.array(z.strictObject({ tool: label, state: z.enum(['running', 'succeeded', 'failed']) })).max(100),
  progress_truncated: z.boolean(),
  trace: z.array(traceStepSchema.refine((step) => step.response === null && !step.response_truncated)).max(133),
  answer: answerSchema.nullable(),
  selection: targetSelectionSchema.nullable(),
  error: z.strictObject({ code: z.string().min(1).max(64), message: z.string().min(1).max(512) }).nullable(),
});
export const unsupportedTurnSchema = z.strictObject({ id: identifier, code: z.literal('history_unsupported') });
const cursor = z.string().min(1).max(1024).nullable();
export const turnPageSchema = z.strictObject({
  items: z.array(z.union([savedTurnSchema, unsupportedTurnSchema])).max(50),
  next_cursor: cursor,
});
export const investigationPageSchema = z.strictObject({
  items: z.array(investigationSummarySchema).max(50),
  next_cursor: cursor,
});
export const investigationDetailSchema = investigationViewSchema.extend({ turns: turnPageSchema });
export const acceptedTurnSchema = z.strictObject({ snapshot: savedTurnSchema, created: z.boolean() });
const submissionFields = {
  submission_id: identifier,
  expected_revision: revisionSchema,
  model: modelSelectionSchema.nullable(),
};
export const startTurnSchema = z.discriminatedUnion('kind', [
  z.strictObject({
    ...submissionFields,
    kind: z.literal('question'),
    query: z.string().trim().min(1).max(4000),
    target: diagnosticTargetSchema.nullable(),
  }),
  z.strictObject({
    ...submissionFields,
    kind: z.literal('clarification'),
    clarification_of: identifier,
    expected_parent_revision: revisionSchema,
    target: diagnosticTargetSchema,
  }),
]);
export type BrowserSession = z.infer<typeof browserSessionSchema>;
export type InvestigationWorkspace = z.infer<typeof investigationWorkspaceSchema>;
export type ActorWorkspace = z.infer<typeof actorWorkspaceSchema>;
export type InvestigationSummary = z.infer<typeof investigationSummarySchema>;
export type InvestigationView = z.infer<typeof investigationViewSchema>;
export type InvestigationDetail = z.infer<typeof investigationDetailSchema>;
export type InvestigationPage = z.infer<typeof investigationPageSchema>;
export type SavedTurn = z.infer<typeof savedTurnSchema>;
export type TurnPage = z.infer<typeof turnPageSchema>;
export type StartTurn = z.infer<typeof startTurnSchema>;
export type WorkspaceChanges = Partial<Omit<InvestigationWorkspace, 'revision'>>;
export type ActorChanges = Partial<Omit<ActorWorkspace, 'revision'>>;

export interface HistoryTransport {
  actorWorkspace(signal?: AbortSignal): Promise<ActorWorkspace>;
  saveActorWorkspace(expected_revision: number, changes: ActorChanges): Promise<ActorWorkspace>;
  investigations(signal: AbortSignal, before?: string): Promise<InvestigationPage>;
  createInvestigation(id: string, host: string): Promise<InvestigationView>;
  investigation(id: string, signal: AbortSignal): Promise<InvestigationDetail>;
  olderTurns(id: string, before: string, signal: AbortSignal): Promise<TurnPage>;
  saveWorkspace(id: string, expected_revision: number, changes: WorkspaceChanges): Promise<InvestigationWorkspace>;
  deleteInvestigation(id: string): Promise<void>;
  startTurn(id: string, input: StartTurn, signal: AbortSignal): Promise<{ snapshot: SavedTurn; created: boolean }>;
  turn(id: string, signal: AbortSignal): Promise<SavedTurn>;
  observeTurn(id: string, receive: (snapshot: SavedTurn) => void, signal: AbortSignal): Promise<void>;
  cancelTurn(id: string): Promise<SavedTurn>;
}
