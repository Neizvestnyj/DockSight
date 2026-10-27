import { LocaleProvider, LanguageSwitch } from './LocaleProvider';
import { useLocale } from './locale';
import { useEffect, useState } from 'react';
import { ArrowRight, ChevronRight, FlaskConical, Menu, MessageSquarePlus } from 'lucide-react';
import type { Container, Host, Transport } from './contracts';
import { DemoClient, demoAnswer, demoHosts, scenarios, type ScenarioId } from './demo';
import { DemoControls } from './DemoControls';
import { isMessageKey } from './messages';
import { Connection } from './Connection';
import { Investigation } from './Investigation';
import { Mark, Modal } from './ui';
import { Sidebar } from './Sidebar';
import { utc } from './format';
import { useInvestigation } from './useInvestigation';

interface ConnectionState {
  client: Transport;
  demo: boolean;
  id: number;
}

/** Own the connection lifetime; a new backend or host gets a separate transient workspace. */
export default function App() {
  return (
    <LocaleProvider>
      <ConnectedApp />
    </LocaleProvider>
  );
}

/** Keep the active connection stable while presentation language changes. */
function ConnectedApp() {
  const { t } = useLocale();
  const [connection, setConnection] = useState<ConnectionState>(() => ({
    client: new DemoClient(),
    demo: true,
    id: 0,
  }));
  const [hosts, setHosts] = useState<Host[]>(demoHosts);
  const [host, setHost] = useState('demo-eu');
  const [showExample, setShowExample] = useState(true);
  const [hostError, setHostError] = useState('');
  const [hostLoading, setHostLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [connecting, setConnecting] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    connection.client
      .hosts(controller.signal)
      .then((rows) => {
        if (controller.signal.aborted) return;
        setHosts(rows);
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

  /** Drop old conversations and credentials when changing transport. */
  function changeConnection(client: Transport, demo: boolean) {
    setConnection((previous) => ({ client, demo, id: previous.id + 1 }));
    setHosts(demo ? demoHosts : []);
    setHost(demo ? 'demo-eu' : '');
    setHostError('');
    setHostLoading(true);
    setConnecting(false);
    setShowExample(demo);
  }

  return (
    <>
      <Workspace
        key={`${connection.id}-${host}`}
        connection={connection}
        hosts={
          connection.demo
            ? hosts.map((row) => ({ ...row, name: isMessageKey(row.name) ? t(row.name) : row.name }))
            : hosts
        }
        host={host}
        changeHost={(value) => {
          setHost(value);
          setShowExample(false);
        }}
        showExample={showExample}
        hostError={
          hostError ? t('Could not load configured hosts. Check the API endpoint, bearer token, and CORS.') : ''
        }
        hostLoading={hostLoading}
        retryHosts={() => {
          setHostLoading(true);
          setAttempt((value) => value + 1);
        }}
        connect={() => setConnecting(true)}
        returnDemo={() => changeConnection(new DemoClient(), true)}
      />
      {connecting && (
        <Connection close={() => setConnecting(false)} connect={(client) => changeConnection(client, false)} />
      )}
    </>
  );
}

interface WorkspaceProps {
  connection: ConnectionState;
  hosts: Host[];
  host: string;
  changeHost: (host: string) => void;
  hostError: string;
  hostLoading: boolean;
  retryHosts: () => void;
  connect: () => void;
  returnDemo: () => void;
  showExample: boolean;
}

/** Scope inventory, demo controls, and all diagnostic turns to one configured host. */
function Workspace({
  connection,
  hosts,
  host,
  changeHost,
  hostError,
  hostLoading,
  retryHosts,
  connect,
  returnDemo,
  showExample,
}: WorkspaceProps) {
  const { t } = useLocale();
  const { client, demo } = connection;
  const demoClient = client instanceof DemoClient ? client : null;
  const [initial] = useState(() =>
    demoClient && showExample && host === 'demo-eu' ? demoClient.remember(demoAnswer('crash_loop', host)) : undefined,
  );
  const investigation = useInvestigation(client, host, initial);
  const [inventory, setInventory] = useState<Container[]>([]);
  const [loading, setLoading] = useState(true);
  const [inventoryError, setInventoryError] = useState('');
  const [revision, setRevision] = useState(0);
  const [selected, setSelected] = useState(initial ? '1'.repeat(64) : '');
  const [draft, setDraft] = useState('');
  const [scenario, setScenario] = useState<ScenarioId>(demoClient?.scenario ?? 'crash_loop');
  const [menu, setMenu] = useState(false);
  const [help, setHelp] = useState(false);
  const name = hosts.find((row) => row.id === host)?.name ?? host;

  useEffect(() => {
    if (!host) return;
    const controller = new AbortController();
    client
      .containers(host, controller.signal)
      .then((rows) => {
        if (!controller.signal.aborted) {
          setInventory(rows);
          setInventoryError('');
          setLoading(false);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setInventoryError(error instanceof Error ? error.message : 'Could not read Docker inventory.');
          setLoading(false);
        }
      });
    return () => controller.abort();
  }, [client, host, revision]);

  /** Refresh only the read model, preserving historical diagnostic observations. */
  function refresh() {
    setLoading(true);
    setRevision((value) => value + 1);
  }

  /** Make fixture selection a clearly simulated example rather than a live diagnosis. */
  function chooseScenario(value: ScenarioId) {
    if (!demoClient) return;
    demoClient.setScenario(value);
    setScenario(value);
    const item = scenarios.find((row) => row.id === value)!;
    const answer = demoClient.example(host);
    setSelected(answer.widgets.find((row) => row.widget_type === 'container_status')?.snapshot.id ?? '');
    investigation.example(answer, item.query);
    setDraft('');
  }

  /** Offer a scoped question without sending it until the operator submits. */
  function chooseContainer(container: Container) {
    setSelected(container.id);
    setDraft(
      t('Investigate {name} ({id}). What happened, and what evidence supports it?', {
        name: container.name,
        id: container.id,
      }),
    );
    setMenu(false);
    const matched = scenarios.find((row) => row.container === container.name);
    if (demoClient && matched) {
      demoClient.setScenario(matched.id);
      setScenario(matched.id);
    }
  }

  const sidebarProps = {
    hosts,
    host,
    hostLoading,
    hostError,
    retryHosts,
    inventory,
    inventoryError,
    loading,
    selected,
    chooseContainer,
    refresh,
    demo,
    connect: () => {
      setMenu(false);
      connect();
    },
    returnDemo,
    changeHost: (value: string) => {
      changeHost(value);
      setMenu(false);
    },
    newInvestigation: () => {
      investigation.clear();
      setMenu(false);
    },
    about: () => {
      setMenu(false);
      setHelp(true);
    },
  };

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        {t('Skip to investigation')}
      </a>
      <aside className="sidebar" aria-label={t('Host and container inventory')}>
        <Sidebar {...sidebarProps} />
      </aside>
      <header className="topbar">
        <button
          className="icon-button mobile-menu"
          aria-label={t('Open host and containers')}
          onClick={() => setMenu(true)}
        >
          <Menu size={19} />
        </button>
        <span className="mobile-brand">
          <Mark />
          DockSight
        </span>
        <div className="breadcrumb">
          <span>{t('Workspace')}</span>
          <ChevronRight size={13} />
          <strong>{name || t('Docker hosts')}</strong>
        </div>
        <div className="connection-state">
          <span className={`scope-dot${demo ? ' demo-dot' : ''}`} />
          {t(demo ? 'Demo' : 'API mode')}
          <button className="text-button" onClick={connect}>
            {t(demo ? 'Connect API' : 'Change connection')}
            <ArrowRight size={13} />
          </button>
        </div>
      </header>
      <main id="main" className="sheet">
        <div className="page-heading">
          <div>
            <h1>{t('Container investigation')}</h1>
            <p>
              {inventory[0]
                ? t('Inventory observed {time} · snapshots, not a live feed', { time: utc(inventory[0].observed_at) })
                : t('Docker diagnostics · host-scoped sessions')}
            </p>
          </div>
          <div className="heading-actions">
            <LanguageSwitch />
            <button
              className="secondary"
              aria-label={t('Ask DockSight')}
              onClick={() => document.getElementById('query')?.focus()}
            >
              <MessageSquarePlus size={15} />
              {t('Ask DockSight')}
            </button>
          </div>
        </div>
        {demo && (
          <div className="demo-bar">
            <div>
              <FlaskConical size={15} />
              <strong>{t('Demo')}</strong>
              <span>{t('Example data from a fictional host. Connect an API to diagnose your Docker.')}</span>
            </div>
            <label>
              {t('Scenario')}
              <select
                aria-label={t('Demo scenario')}
                value={scenario}
                onChange={(event) => chooseScenario(event.target.value as ScenarioId)}
                disabled={investigation.running}
              >
                {scenarios.map((item) => (
                  <option key={item.id} value={item.id}>
                    {t(item.name)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        {demoClient && <DemoControls client={demoClient} refresh={refresh} running={investigation.running} />}
        {hostError && (
          <div className="turn-error">
            <p role="alert">{hostError}</p>
            <button className="secondary" onClick={retryHosts}>
              {t('Retry connection')}
            </button>
          </div>
        )}
        <Investigation
          investigation={investigation}
          client={client}
          demo={demo}
          containers={inventory}
          draft={draft}
          setDraft={setDraft}
          host={host}
        />
      </main>
      {menu && (
        <Modal title={t('Host & containers')} close={() => setMenu(false)}>
          <div className="mobile-sidebar">
            <Sidebar {...sidebarProps} />
          </div>
        </Modal>
      )}
      {help && (
        <Modal title={t('About this workspace')} close={() => setHelp(false)}>
          <p>
            {t(
              'DockSight gathers read-only Docker observations and returns a model explanation with typed cards. The backend decides permitted operations.',
            )}
          </p>
          <p>
            {t(
              'Conclusions are interpretations. Cards and the evidence trail show the observed facts and their UTC timestamps.',
            )}
          </p>
          <p>
            {t(
              "Changing hosts starts a separate session. Conversations are held in this tab's memory; the API has no past-dialogue listing. Backend sessions and actions disappear after a restart or expiry.",
            )}
          </p>
          <p>
            {demo
              ? t('All current observations are fixture-based examples. Connect an API for real Docker evidence.')
              : t(
                  'Your bearer token is held only in this tab’s memory and is discarded when you disconnect or reload.',
                )}
          </p>
        </Modal>
      )}
    </div>
  );
}
