import { useState } from 'react';
import type { DemoClient, DemoFault } from './demo';
import { useLocale } from './locale';
import type { MessageKey } from './messages';

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
  return (
    <details className="demo-controls">
      <summary>{t('Test error states')}</summary>
      <div>
        <label>
          {t('Simulated connection')}
          <select
            aria-label={t('Simulated connection')}
            aria-describedby="demo-connection-help"
            value={fault}
            disabled={running}
            onChange={(event) => {
              const next = event.target.value as DemoFault;
              client.setFault(next);
              setFault(next);
              refresh();
            }}
          >
            <option value="none">{t('Normal')}</option>
            <option value="stream">{t('Turn fails after collection')}</option>
            <option value="offline">{t('Connection unavailable')}</option>
            <option value="empty">{t('Empty inventory')}</option>
          </select>
          <span id="demo-connection-help">{t(faultHelp[fault])}</span>
        </label>
        <label>
          {t('After action confirmation')}
          <select
            aria-label={t('After action confirmation')}
            aria-describedby="demo-action-help"
            defaultValue={client.outcome}
            disabled={running}
            onChange={(event) => client.setOutcome(event.target.value as DemoClient['outcome'])}
          >
            <option value="succeeded">{t('Succeeded')}</option>
            <option value="failed">{t('Failed')}</option>
            <option value="indeterminate">{t('Indeterminate')}</option>
            <option value="expired">{t('Expired')}</option>
          </select>
          <span id="demo-action-help">
            {t('Choose a result, review a container action, then confirm it. Shown cards stay unchanged.')}
          </span>
        </label>
      </div>
    </details>
  );
}
