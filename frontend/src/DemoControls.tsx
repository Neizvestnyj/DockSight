import { useState } from 'react';
import type { DemoClient, DemoFault } from './demo';
import { useLocale } from './locale';
import type { MessageKey } from './messages';
import { Select } from './Select';

const faultHelp: Record<DemoFault, MessageKey> = {
  none: 'Requests succeed normally.',
  stream: 'Submit a question to simulate a failure after collecting evidence.',
  offline: 'The container list cannot load; submitting a question also fails.',
  empty: 'The container list is empty; new questions return no container evidence.',
};

/** Explain when each simulated failure applies without changing existing evidence. */
export function DemoControls({
  client,
  refresh,
  running,
}: {
  client: DemoClient;
  refresh: () => void;
  running: boolean;
}) {
  const { t } = useLocale();
  const [fault, setFault] = useState(client.fault);
  const [outcome, setOutcome] = useState(client.outcome);
  return (
    <details className="demo-controls">
      <summary>{t('Test error states')}</summary>
      <div>
        <label>
          {t('Simulated connection')}
          <Select<DemoFault>
            label={t('Simulated connection')}
            describedBy="demo-connection-help"
            value={fault}
            disabled={running}
            onChange={(next) => {
              client.setFault(next);
              setFault(next);
              refresh();
            }}
            options={[
              { value: 'none', label: t('Normal') },
              { value: 'stream', label: t('Turn fails after collection') },
              { value: 'offline', label: t('Connection unavailable') },
              { value: 'empty', label: t('Empty inventory') },
            ]}
          />
          <span id="demo-connection-help">{t(faultHelp[fault])}</span>
        </label>
        <label>
          {t('After action confirmation')}
          <Select<DemoClient['outcome']>
            label={t('After action confirmation')}
            describedBy="demo-action-help"
            value={outcome}
            disabled={running}
            onChange={(next) => {
              client.setOutcome(next);
              setOutcome(next);
            }}
            options={[
              { value: 'succeeded', label: t('Succeeded') },
              { value: 'failed', label: t('Failed') },
              { value: 'indeterminate', label: t('Indeterminate') },
              { value: 'expired', label: t('Expired') },
            ]}
          />
          <span id="demo-action-help">
            {t('Choose a result, review a container action, then confirm it. Shown cards stay unchanged.')}
          </span>
        </label>
      </div>
    </details>
  );
}
