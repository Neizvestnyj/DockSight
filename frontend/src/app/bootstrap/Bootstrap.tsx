import controlStyles from '../../shared/ui/Controls.module.css';
import { LanguageSwitch } from '../providers/LocaleProvider';
import { useLocale } from '../../shared/i18n/locale';
import { useEffect, useState } from 'react';
import { DemoClient } from '../../infrastructure/demo/demo';
import { Connection } from '../../modules/session';
import { Logo } from '../../shared/ui/ui';
import { ApiClient } from '../../infrastructure/api/api';
import { ApiError } from '../../shared/contracts/errors';
import { connectApi } from './connectApi';
import { ConnectedWorkspace } from '../workspace/ConnectedWorkspace';
import type { ConnectionState } from '../workspace/types';
import styles from './SessionEntry.module.css';

/** Keep the active connection stable while presentation language changes. */
export function Bootstrap() {
  const { t } = useLocale();
  const [connection, setConnection] = useState<ConnectionState>();
  const [state, setState] = useState<'loading' | 'signed-out' | 'error'>('loading');
  const [attempt, setAttempt] = useState(0);
  const [connecting, setConnecting] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    const client = new ApiClient();
    void client
      .session(controller.signal)
      .then(() => {
        if (!controller.signal.aborted) setConnection({ client, demo: false, id: 0 });
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted)
          setState(failure instanceof ApiError && failure.httpStatus === 401 ? 'signed-out' : 'error');
      });
    return () => controller.abort();
  }, [attempt]);
  if (connection)
    return (
      <ConnectedWorkspace
        key={connection.id}
        initialConnection={connection}
        replaceConnection={(client, demo) =>
          setConnection((previous) => ({ client, demo, id: (previous?.id ?? 0) + 1 }))
        }
        signOut={() => {
          setConnection(undefined);
          setState('signed-out');
        }}
      />
    );
  return (
    <main className={`${styles['session-entry']}`}>
      <header className={styles['entry-heading']}>
        <Logo />
        <LanguageSwitch />
      </header>
      <section>
        <h1>
          {t(
            state === 'loading'
              ? 'Restoring your workspace…'
              : state === 'signed-out'
                ? 'Sign in to DockSight'
                : 'Could not restore your session.',
          )}
        </h1>
        <p>{t('Saved chats stay on your DockSight backend. Sign in to reopen your workspace.')}</p>
        {state !== 'loading' && (
          <div className={`${styles['entry-actions']}`}>
            {state === 'error' && (
              <button
                className={`secondary ${controlStyles['secondary']}`}
                onClick={() => {
                  setState('loading');
                  setAttempt((value) => value + 1);
                }}
              >
                {t('Retry connection')}
              </button>
            )}
            <button className={`primary ${controlStyles['primary']}`} onClick={() => setConnecting(true)}>
              {t('Connect API')}
            </button>
            <button
              className={`secondary ${controlStyles['secondary']}`}
              onClick={() => setConnection({ client: new DemoClient(), demo: true, id: 0 })}
            >
              {t('Explore Demo')}
            </button>
          </div>
        )}
      </section>
      {connecting && (
        <Connection
          connectApi={connectApi}
          close={() => setConnecting(false)}
          connect={(client) => {
            setConnecting(false);
            setConnection({ client, demo: false, id: Date.now() });
          }}
        />
      )}
    </main>
  );
}
