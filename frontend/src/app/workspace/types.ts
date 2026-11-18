import type { Transport } from '../../shared/contracts/transport';

export interface ConnectionState {
  client: Transport;
  demo: boolean;
  id: number;
}

export const hostPickerTriggerId = 'workspace-host-picker';
