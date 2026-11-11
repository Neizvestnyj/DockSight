import type { Transport } from '../../shared/contracts/contracts';

export interface ConnectionState {
  client: Transport;
  demo: boolean;
  id: number;
}

export const hostPickerTriggerId = 'workspace-host-picker';
