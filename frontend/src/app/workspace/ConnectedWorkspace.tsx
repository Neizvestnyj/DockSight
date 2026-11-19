import controlStyles from '../../shared/ui/Controls.module.css';
import { useLocale } from '../../shared/i18n/locale';
import { useEffect, useRef, useState } from 'react';
import type { Host } from '../../shared/contracts/contracts';
import type { Transport } from '../../shared/contracts/transport';
import { DemoClient, demoHosts } from '../../infrastructure/demo/demo';
import { isMessageKey } from '../../shared/i18n/messages';
import { Connection } from '../../modules/session';
import { Logo } from '../../shared/ui/ui';
import { HostPicker } from '../../modules/runtime';
import type { ModelSelection } from '../../shared/contracts/model-contracts';
import { ApiClient } from '../../infrastructure/api/api';
import { useWorkspace } from '../../modules/investigations';
import { useSavedInvestigations } from '../../modules/investigations';
import { connectApi } from '../bootstrap/connectApi';
import { WorkspacePage } from './WorkspacePage';
import { hostPickerTriggerId, type ConnectionState } from './types';
import sessionStyles from '../bootstrap/SessionEntry.module.css';

/** Keep the active connection stable while presentation language changes. */
export function ConnectedWorkspace({
  initialConnection,
  signOut,
  replaceConnection,
}: {
  initialConnection: ConnectionState;
  signOut: () => void;
  replaceConnection: (client: Transport, demo: boolean) => void;
}) {
  const { t } = useLocale();
  const connection = initialConnection;
  const [hosts, setHosts] = useState<Host[]>(initialConnection.demo ? demoHosts : []);
  const [selectedHost, setHost] = useState(initialConnection.demo ? 'demo-eu' : '');
  const [showExample, setShowExample] = useState(initialConnection.demo);
  const [hostError, setHostError] = useState('');
  const [hostLoading, setHostLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [connecting, setConnecting] = useState(false);
  const [choosingHost, setChoosingHost] = useState(false);
  const [modelSelection, setModelSelection] = useState<ModelSelection>();
  const history = useSavedInvestigations(connection.client.history);
  const saved = useWorkspace(connection.client.history, history.refresh);
  const host = workspaceHost(connection.demo, selectedHost, saved.chat?.host);
  const restored = useRef<number | undefined>(undefined);
  const choseInitialHost = useRef(false);
  const displayHosts = connection.demo
    ? hosts.map((row) => ({ ...row, name: isMessageKey(row.name) ? t(row.name) : row.name }))
    : hosts;
  const translatedHostError = hostError
    ? t('Could not load configured hosts. Check the API endpoint, bearer token, and CORS.')
    : '';

  useEffect(() => {
    const controller = new AbortController();
    connection.client
      .hosts(controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        setHosts(rows);
        if (connection.demo)
          setHost((previous) => (rows.some((row) => row.id === previous) ? previous : (rows[0]?.id ?? '')));
        setHostError('');
        setHostLoading(false);
      })
      .catch(() => {
        if (!controller.signal.aborted) {
          setHostError('Could not load configured hosts. Check the API endpoint, bearer token, and CORS.');
          setHostLoading(false);
        }
      });
    return () => controller.abort();
  }, [connection, attempt]);

  useEffect(() => {
    if (!saved.ready || connection.demo || restored.current === connection.id) return;
    restored.current = connection.id;
    setHost(saved.detail?.host ?? saved.actor?.host ?? '');
    setModelSelection(saved.actor?.model ?? undefined);
  }, [saved.ready, saved.detail?.host, saved.actor, connection]);

  useEffect(() => {
    if (
      connection.demo ||
      !saved.ready ||
      saved.detail ||
      saved.actor?.host ||
      hosts.length !== 1 ||
      choseInitialHost.current
    )
      return;
    choseInitialHost.current = true;
    void saved.create(hosts[0]!.id).then(() => history.refresh());
  }, [connection.demo, saved, hosts, history]);

  /** Drop old conversations and credentials when changing transport. */
  function changeConnection(client: Transport, demo: boolean) {
    replaceConnection(client, demo);
  }

  /** Retry discovery without dismissing an open host picker. */
  function retryHosts() {
    setHostLoading(true);
    setAttempt((value) => value + 1);
  }

  /** Start a separate saved host scope without replacing any previous chat. */
  function changeHost(value: string) {
    if (value === host) return;
    if (connection.demo) setHost(value);
    setShowExample(false);
    if (!connection.demo) void saved.create(value).then(() => history.refresh());
  }

  /** Revoke first-party authority or discard transient bearer authority explicitly. */
  async function logout() {
    try {
      if (connection.client instanceof ApiClient && connection.client.authentication === 'cookie')
        await connection.client.logout();
      signOut();
    } catch {
      setHostError('Could not sign out. Retry the connection.');
    }
  }

  if (!connection.demo && !saved.ready)
    return (
      <main className={sessionStyles['session-entry']}>
        <Logo />
        <h1>{t('Restoring your workspace…')}</h1>
        {saved.error && (
          <>
            <p role="alert">{t('Could not restore saved workspace. Retry the read.')}</p>
            <button className={`secondary ${controlStyles['secondary']}`} onClick={saved.retry}>
              {t('Retry')}
            </button>
            <button className={`text-button ${controlStyles['text-button']}`} onClick={() => void logout()}>
              {t('Sign out')}
            </button>
          </>
        )}
      </main>
    );

  return (
    <>
      <WorkspacePage
        key={`${connection.id}-${host}-${saved.chat?.id ?? 'new'}`}
        connection={connection}
        hosts={displayHosts}
        host={host}
        changeHost={changeHost}
        showExample={showExample}
        hostError={translatedHostError}
        hostLoading={hostLoading}
        retryHosts={retryHosts}
        openHostPicker={() => setChoosingHost(true)}
        connect={() => setConnecting(true)}
        returnDemo={() => changeConnection(new DemoClient(), true)}
        modelSelection={modelSelection}
        chooseModel={(value) => {
          if (connection.demo) setModelSelection(value);
          else
            void saved.savePreferences({ model: value }).then((acknowledged) => {
              if (acknowledged) setModelSelection(value);
            });
        }}
        saved={saved}
        history={history}
        logout={() => void logout()}
      />
      {choosingHost && (
        <HostPicker
          hosts={displayHosts}
          host={host}
          loading={hostLoading}
          error={translatedHostError}
          retry={retryHosts}
          returnFocusId={hostPickerTriggerId}
          close={() => setChoosingHost(false)}
          choose={(value) => {
            setChoosingHost(false);
            if (value !== host) {
              changeHost(value);
            }
          }}
          connect={() => {
            setChoosingHost(false);
            setConnecting(true);
          }}
        />
      )}
      {connecting && (
        <Connection
          close={() => setConnecting(false)}
          connectApi={connectApi}
          connect={(client) => changeConnection(client, false)}
        />
      )}
    </>
  );
}

/** Keep a saved investigation bound to its own host until an explicit scope change. */
function workspaceHost(demo: boolean, selected: string, savedHost: string | undefined): string {
  return demo ? selected : (savedHost ?? selected);
}
