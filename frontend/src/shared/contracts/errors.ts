/** Keep safe server error codes available for session-expiry recovery. */
export class ApiError extends Error {
  constructor(
    message: string,
    public readonly code: string,
    public readonly requestId?: string,
    public readonly source: 'server' | 'client' = 'server',
    public readonly httpStatus?: number,
    public readonly current?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}
