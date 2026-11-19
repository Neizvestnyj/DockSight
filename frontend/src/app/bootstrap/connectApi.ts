import { ApiClient } from '../../infrastructure/api/api';

/** Construct one API authority and authenticate it before handing it to the workspace. */
export async function connectApi({ base, token }: { base: string; token: string }): Promise<ApiClient> {
  const url = new URL(base, window.location.origin);
  const sameOrigin = url.origin === window.location.origin;
  const client = new ApiClient(sameOrigin ? url.pathname : base, sameOrigin ? '' : token);
  if (sameOrigin) await client.login(token);
  else await client.hosts(new AbortController().signal);
  return client;
}
