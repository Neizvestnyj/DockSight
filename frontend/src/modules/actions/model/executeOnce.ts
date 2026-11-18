import type { Action } from '../../../shared/contracts/contracts';
import type { Transport } from '../../../shared/contracts/transport';

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
