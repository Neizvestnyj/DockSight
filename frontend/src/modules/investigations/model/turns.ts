import type { Answer, DiagnosticTarget, TargetSelection, TraceStep } from '../../../shared/contracts/contracts';
import type { SavedTurn } from '../../../shared/contracts/investigation-contracts';

interface TurnTrace {
  provider: string | null;
  model: string | null;
  started_at: string | null;
  steps: TraceStep[];
}

interface ToolProgress {
  tool: string;
  state: 'running' | 'done' | 'failed';
}
export interface Turn {
  id: string;
  query: string;
  target?: DiagnosticTarget;
  exampleQuery?: true;
  state: 'running' | 'completed' | 'failed' | 'stopped' | 'awaiting_selection' | 'interrupted';
  progress: ToolProgress[];
  answer?: Answer;
  selection?: TargetSelection;
  error?: string;
  errorSource?: 'server' | 'client';
  code?: string;
  requestId?: string;
  serverTurnId?: string;
  trace?: TurnTrace;
  createdAt?: string;
  updatedAt?: string;
  attempts?: SavedTurn[];
}
