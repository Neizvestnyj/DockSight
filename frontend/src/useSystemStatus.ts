import { useEffect, useState } from 'react';
import { ApiError } from './api';
import type { CheckCode, CheckState, SystemStatus, Transport } from './contracts';
import type { MessageKey } from './messages';

export const checkReasons: Record<CheckCode, MessageKey> = {
  ok: 'Availability check succeeded.',
  host_not_selected: 'Select a configured host to check Docker.',
  timeout: 'The availability check timed out.',
  connection_failed: 'Could not connect to the provider.',
  runtime_unavailable: 'Could not connect to the selected Docker host.',
  credentials_rejected: 'The provider rejected its server-configured credentials.',
  metadata_forbidden: 'Model metadata access is denied; generation access was not tested.',
  unsupported: 'The provider does not expose a supported model metadata endpoint.',
  model_not_found: 'The configured model was not found by the provider.',
  model_not_listed: 'The model is not in the returned catalog; aliases and generation were not tested.',
  rate_limited: 'The provider rate-limited the availability check.',
  upstream_error: 'The provider could not complete the availability check.',
  invalid_response: 'The provider returned unsupported or oversized metadata.',
  probe_not_configured: 'Metadata checks are not configured for this model adapter.',
  check_failed: 'The availability check could not finish.',
  provider_unavailable: 'Model availability was not checked because the provider check failed.',
};
export interface ApiObservation {
  state: CheckState;
  reason: MessageKey;
  checkedAt?: string;
}
interface Observation {
  client: Transport;
  host: string;
  data?: SystemStatus;
  api: ApiObservation;
  loading: boolean;
}

/** Classify HTTP authorization separately from network and unsupported status contracts. */
function failedApi(error: unknown): ApiObservation {
  const checkedAt = new Date().toISOString();
  if (error instanceof ApiError) {
    if (error.httpStatus === 401)
      return { state: 'unavailable', reason: 'The API rejected the bearer token.', checkedAt };
    if (error.httpStatus === 403)
      return {
        state: 'unavailable',
        reason: 'API access is denied. Check permissions and allowed origins.',
        checkedAt,
      };
    if (error.code === 'status_unsupported' || error.httpStatus === 404)
      return { state: 'not_checked', reason: 'Status checks are not supported by this API.', checkedAt };
    return { state: 'unavailable', reason: 'The API could not complete the status check.', checkedAt };
  }
  return { state: 'unavailable', reason: 'No connection to the API. Check the endpoint and network.', checkedAt };
}

/** Check once per selected host and on demand; retain last observations without polling or retrying. */
export function useSystemStatus(client: Transport, host: string, enabled = true) {
  const initial: Observation = { client, host, loading: true, api: { state: 'not_checked', reason: 'Not checked' } };
  const [observation, setObservation] = useState<Observation>(initial);
  const [revision, setRevision] = useState(0);
  const current = observation.client === client && observation.host === host ? observation : initial;
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    client
      .systemStatus(host || null, controller.signal)
      .then((data) => {
        if (!controller.signal.aborted)
          setObservation({
            client,
            host,
            data,
            loading: false,
            api: { state: 'available', reason: 'API and authorization verified.', checkedAt: new Date().toISOString() },
          });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          setObservation((previous) => ({
            client,
            host,
            loading: false,
            api: failedApi(error),
            data: previous.client === client && previous.host === host ? previous.data : undefined,
          }));
      });
    return () => controller.abort();
  }, [client, host, enabled, revision]);

  /** Leave prior timestamps in place until the manual attempt returns a new observation. */
  function refresh() {
    setObservation({ ...current, loading: true });
    setRevision((value) => value + 1);
  }

  let blockedReason: MessageKey | undefined;
  if (current.api.state === 'unavailable') blockedReason = current.api.reason;
  if (current.api.state === 'available' && current.data) {
    if (current.data.docker.state === 'unavailable')
      blockedReason =
        'Docker is unavailable for this host. Diagnosis cannot collect evidence. Check the connection and try again.';
    else if (current.data.provider_check.state === 'unavailable')
      blockedReason = 'The model provider is unavailable. You can still inspect Docker directly.';
    else if (current.data.model_check.state === 'unavailable')
      blockedReason = 'The configured model is unavailable. You can still inspect Docker directly.';
  }
  return { data: current.data, api: current.api, loading: current.loading, refresh, blockedReason };
}
