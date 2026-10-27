import { useEffect, useState } from 'react';
import { ArrowRight, ChevronRight, FlaskConical, Menu, MessageSquarePlus } from 'lucide-react';
import type { Container, Host, Transport } from './contracts';
import { DemoClient, demoAnswer, demoHosts, scenarios, type DemoFault, type ScenarioId } from './demo';
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
  const [connection, setConnection] = useState<ConnectionState>(() => ({
    client: new DemoClient(),
    demo: true,
    id: 0,
  }));
  const [hosts, setHosts] = useState<Host[]>(demoHosts);
  const [host, setHost] = useState('production-eu');
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
    setHost(demo ? 'production-eu' : '');
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
        hosts={hosts}
        host={host}
        changeHost={(value) => {
          setHost(value);
          setShowExample(false);
        }}
        showExample={showExample}
        hostError={hostError}
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
  const { client, demo } = connection;
  const demoClient = client instanceof DemoClient ? client : null;
  const [initial] = useState(() =>
    demoClient && showExample && host === 'production-eu'
      ? demoClient.remember(demoAnswer('crash_loop', host))
      : undefined,
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
    const index = scenarios.indexOf(item);
    setSelected((index + 1).toString(16).repeat(64));
    investigation.example(demoClient.remember(demoAnswer(value, host, demoClient.largeLogs)), item.query);
    setDraft('');
  }

  /** Offer a scoped question without sending it until the operator submits. */
  function chooseContainer(container: Container) {
    setSelected(container.id);
    setDraft(`Investigate ${container.name} (${container.id}). What happened, and what evidence supports it?`);
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
        Skip to investigation
      </a>
      <aside className="sidebar" aria-label="Host and container inventory">
        <Sidebar {...sidebarProps} />
      </aside>
      <header className="topbar">
        <button className="icon-button mobile-menu" aria-label="Open host and containers" onClick={() => setMenu(true)}>
          <Menu size={19} />
        </button>
        <span className="mobile-brand">
          <Mark />
          DockSight
        </span>
        <div className="breadcrumb">
          <span>Workspace</span>
          <ChevronRight size={13} />
          <strong>{name || 'Docker hosts'}</strong>
        </div>
        <div className="connection-state">
          <span className={`scope-dot${demo ? ' demo-dot' : ''}`} />
          {demo ? 'Demo' : 'API mode'}
          <button className="text-button" onClick={connect}>
            {demo ? 'Connect API' : 'Change connection'}
            <ArrowRight size={13} />
          </button>
        </div>
      </header>
      <main id="main" className="sheet">
        <div className="page-heading">
          <div>
            <h1>Container investigation</h1>
            <p>
              {inventory[0]
                ? `Inventory observed ${utc(inventory[0].observed_at)} · snapshots, not a live feed`
                : 'Docker diagnostics · host-scoped sessions'}
            </p>
          </div>
          <button
            className="secondary"
            aria-label="Ask DockSight"
            onClick={() => document.getElementById('query')?.focus()}
          >
            <MessageSquarePlus size={15} />
            Ask DockSight
          </button>
        </div>
        {demo && (
          <div className="demo-bar">
            <div>
              <FlaskConical size={15} />
              <strong>Demo</strong>
              <span>Simulated observations · no Docker changes</span>
            </div>
            <label>
              Scenario
              <select
                aria-label="Demo scenario"
                value={scenario}
                onChange={(event) => chooseScenario(event.target.value as ScenarioId)}
                disabled={investigation.running}
              >
                {scenarios.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
        {demoClient && (
          <details className="demo-controls">
            <summary>Demo controls</summary>
            <div>
              <label>
                Connection behavior
                <select
                  aria-label="Demo connection behavior"
                  defaultValue={demoClient.fault}
                  onChange={(event) => {
                    demoClient.setFault(event.target.value as DemoFault);
                    refresh();
                  }}
                >
                  <option value="none">Normal</option>
                  <option value="stream">Turn fails after collection</option>
                  <option value="offline">Connection unavailable</option>
                  <option value="empty">Empty inventory</option>
                </select>
              </label>
              <label>
                Action outcome
                <select
                  aria-label="Demo action outcome"
                  defaultValue={demoClient.outcome}
                  onChange={(event) => {
                    demoClient.setOutcome(event.target.value as DemoClient['outcome']);
                  }}
                >
                  <option value="succeeded">Succeeded</option>
                  <option value="failed">Failed</option>
                  <option value="indeterminate">Indeterminate</option>
                  <option value="expired">Expired</option>
                </select>
              </label>
              <label className="checkbox-label">
                <input
                  type="checkbox"
                  defaultChecked={demoClient.largeLogs}
                  onChange={(event) => {
                    demoClient.setLargeLogs(event.target.checked);
                    chooseScenario(scenario);
                  }}
                />
                200 log lines
              </label>
            </div>
          </details>
        )}
        {hostError && (
          <div className="turn-error">
            <p role="alert">{hostError}</p>
            <button className="secondary" onClick={retryHosts}>
              Retry connection
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
        <Modal title="Host & containers" close={() => setMenu(false)}>
          <div className="mobile-sidebar">
            <Sidebar {...sidebarProps} />
          </div>
        </Modal>
      )}
      {help && (
        <Modal title="About this workspace" close={() => setHelp(false)}>
          <p>
            DockSight gathers read-only Docker observations and returns a model explanation with typed cards. The
            backend decides permitted operations.
          </p>
          <p>
            Conclusions are interpretations. Cards and the evidence trail show the observed facts and their UTC
            timestamps.
          </p>
          <p>
            Changing hosts starts a separate session. Conversations are held in this tab's memory; the API has no
            past-dialogue listing. Backend sessions and actions disappear after a restart or expiry.
          </p>
          <p>
            {demo
              ? 'All current observations are fixture-based examples. Connect an API for real Docker evidence.'
              : 'Your bearer token is held only in this tab’s memory and is discarded when you disconnect or reload.'}
          </p>
        </Modal>
      )}
    </div>
  );
}
