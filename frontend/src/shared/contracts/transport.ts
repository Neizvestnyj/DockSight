import type {
  Action,
  Container,
  GroupTarget,
  Host,
  LogBatch,
  Metrics,
  Stack,
  SystemStatus,
  TurnEvent,
  TurnInput,
} from './contracts';
import type { HistoryTransport } from './investigation-contracts';
import type { ModelCatalog, ModelProviders, ModelSelection, ProviderId } from './model-contracts';
import type { ContainerSearchResult, SearchPage } from './search-contracts';

/** Expose the runtime and optional saved-history operations needed by the client. */
export interface Transport {
  readonly history?: HistoryTransport;
  systemStatus(host: string | null, signal: AbortSignal, selection?: ModelSelection): Promise<SystemStatus>;
  modelProviders(signal: AbortSignal): Promise<ModelProviders>;
  models(provider: ProviderId, signal: AbortSignal, refresh?: boolean): Promise<ModelCatalog>;
  hosts(signal: AbortSignal): Promise<Host[]>;
  containers(host: string, signal: AbortSignal): Promise<Container[]>;
  searchContainers(
    host: string,
    query: string,
    signal: AbortSignal,
    group?: GroupTarget,
    before?: string,
  ): Promise<SearchPage<ContainerSearchResult>>;
  stacks(host: string, kind: GroupTarget['kind'], signal: AbortSignal): Promise<Stack[]>;
  container(host: string, id: string, signal: AbortSignal): Promise<Container>;
  logs(host: string, id: string, signal: AbortSignal): Promise<LogBatch>;
  stats(host: string, id: string, signal: AbortSignal): Promise<Metrics>;
  diagnose(input: TurnInput, receive: (event: TurnEvent) => void, signal: AbortSignal): Promise<void>;
  action(id: string): Promise<Action>;
  execute(id: string, key: string): Promise<Action>;
}
