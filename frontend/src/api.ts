import { z } from 'zod';
import {
  actionSchema,
  containerSchema,
  hostsSchema,
  logSchema,
  metricsSchema,
  stackSchema,
  systemStatusSchema,
  type Transport,
  type TurnInput,
  type TurnEvent,
  type Action,
} from './contracts';
import { consumeEvents } from './stream';
import { modelCatalogSchema, modelProvidersSchema, type ModelSelection, type ProviderId } from './model-contracts';

/** Keep safe server error codes available for session-expiry recovery. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly requestId?: string,
    public readonly source: 'server' | 'client' = 'server',
    public readonly httpStatus?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

/** Read the bounded public error envelope without surfacing submitted credentials. */
async function rejectResponse(response: Response): Promise<never> {
  const result = z
    .object({ code: z.string(), message: z.string(), request_id: z.string().optional() })
    .safeParse(await response.json().catch(() => null));
  if (result.success)
    throw new ApiError(result.data.message, result.data.code, result.data.request_id, 'server', response.status);
  throw new ApiError(
    `API request failed (HTTP ${response.status}).`,
    'http_error',
    undefined,
    'client',
    response.status,
  );
}

/** Authenticate bounded requests; never store credentials or retry mutations. */
export class ApiClient implements Transport {
  constructor(
    private readonly base: string,
    private readonly token: string,
    private readonly fetcher: typeof fetch = fetch,
  ) {}

  private async send(path: string, options: RequestInit = {}, timeout = 20_000): Promise<Response> {
    const fetchRequest = this.fetcher;
    const response = await fetchRequest(`${this.base || '/api/v1'}${path}`, {
      ...options,
      signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(timeout)])
        : AbortSignal.timeout(timeout),
      headers: { Authorization: `Bearer ${this.token}`, 'Content-Type': 'application/json', ...options.headers },
      cache: 'no-store',
      redirect: 'error',
    });
    if (!response.ok) return rejectResponse(response);
    return response;
  }

  /** List configured hosts without accepting a Docker connection URL. */
  async hosts(signal: AbortSignal) {
    return hostsSchema.parse(await (await this.send('/hosts', { signal })).json());
  }

  /** Read metadata availability only, preserving authentication failures and exact host scope. */
  async systemStatus(host: string | null, signal: AbortSignal, selection?: ModelSelection) {
    const params = new URLSearchParams({ ...(host ? { host } : {}), ...selection });
    const query = params.size ? `?${params}` : '';
    const response = await this.send(`/system/status${query}`, { signal }, 8000);
    const result = systemStatusSchema.safeParse(await response.json().catch(() => null));
    if (
      !result.success ||
      result.data.host !== host ||
      (selection && (result.data.provider !== selection.provider || result.data.model !== selection.model))
    )
      throw new ApiError(
        'Unsupported system status response.',
        'status_unsupported',
        undefined,
        'client',
        response.status,
      );
    return result.data;
  }

  /** List configured connections without requesting any provider metadata. */
  async modelProviders(signal: AbortSignal) {
    return modelProvidersSchema.parse(await (await this.send('/model-providers', { signal }, 8000)).json());
  }

  /** Read the bounded backend catalog and reject a response for a different provider. */
  async models(provider: ProviderId, signal: AbortSignal, refresh = false) {
    const response = await this.send(
      `/model-providers/${encodeURIComponent(provider)}/models${refresh ? '?refresh=true' : ''}`,
      { signal },
      8000,
    );
    return modelCatalogSchema.refine((catalog) => catalog.provider === provider).parse(await response.json());
  }

  /** Read the selected host's bounded inventory. */
  async containers(host: string, signal: AbortSignal) {
    return z
      .array(containerSchema)
      .parse(await (await this.send(`/hosts/${encodeURIComponent(host)}/containers`, { signal })).json());
  }

  /** Read and verify the exact selected resource, including its allowlisted environment. */
  async container(host: string, id: string, signal: AbortSignal) {
    return containerSchema
      .refine(
        (snapshot) => snapshot.host === host && snapshot.id === id,
        'Container response is outside the selected scope.',
      )
      .parse(await (await this.send(containerPath(host, id), { signal })).json());
  }

  /** Discover Compose projects or manager-owned Swarm stacks without generation. */
  async stacks(host: string, kind: 'compose' | 'swarm', signal: AbortSignal) {
    const rows = z
      .array(stackSchema)
      .parse(
        await (
          await this.send(`/hosts/${encodeURIComponent(host)}/stacks?${new URLSearchParams({ kind })}`, { signal })
        ).json(),
      );
    if (rows.some((row) => row.kind !== kind)) throw new Error('Group response is outside the selected scope.');
    return rows;
  }

  /** Read at most 200 sanitized log lines without invoking the model. */
  async logs(host: string, id: string, signal: AbortSignal) {
    return logSchema.parse(await (await this.send(`${containerPath(host, id)}/logs?lines=200`, { signal })).json());
  }

  /** Read a current measurement, preserving nulls rather than inventing history or zeroes. */
  async stats(host: string, id: string, signal: AbortSignal) {
    return metricsSchema.parse(await (await this.send(`${containerPath(host, id)}/stats`, { signal })).json());
  }

  /** Stream one turn until its terminal event or explicit cancellation. */
  async diagnose(input: TurnInput, receive: (event: TurnEvent) => void, signal: AbortSignal) {
    const response = await this.send('/chat/turns', { method: 'POST', body: JSON.stringify(input), signal }, 240_000);
    if (!response.headers.get('content-type')?.includes('text/event-stream'))
      throw new Error('The API did not return a diagnostic event stream.');
    await consumeEvents(response, receive);
  }

  /** Check the existing action without preparing or executing a replacement. */
  async action(id: string) {
    return actionSchema.parse(await (await this.send(`/actions/${encodeURIComponent(id)}`)).json());
  }

  /** Send a separately confirmed action with the execution's original key. */
  async execute(id: string, key: string) {
    return actionSchema.parse(
      await (
        await this.send(
          `/actions/${encodeURIComponent(id)}/execute`,
          {
            method: 'POST',
            headers: { 'Idempotency-Key': key },
            body: JSON.stringify({ confirmed: true }),
          },
          90_000,
        )
      ).json(),
    );
  }
}

/** Encode the configured host and exact container identity into a read-only route. */
function containerPath(host: string, id: string): string {
  return `/hosts/${encodeURIComponent(host)}/containers/${encodeURIComponent(id)}`;
}

/** Resolve a lost execution response with a read, never an automatic mutation retry. */
export async function executeOnce(
  api: Pick<Transport, 'execute' | 'action'>,
  id: string,
  key: string,
): Promise<Action> {
  try {
    return await api.execute(id, key);
  } catch (executionError) {
    try {
      return await api.action(id);
    } catch {
      throw new Error(
        'Execution response unavailable. The Docker result is unconfirmed. Check this existing action before retrying.',
        { cause: executionError },
      );
    }
  }
}
