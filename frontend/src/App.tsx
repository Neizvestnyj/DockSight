import { LocaleProvider, LanguageSwitch } from './LocaleProvider';
import { useLocale } from './locale';
import { useEffect, useState } from 'react';
import { ArrowRight, ChevronDown, ChevronRight, FlaskConical, Menu, MessageSquarePlus } from 'lucide-react';
import type { Container, Host, Transport } from './contracts';
import { DemoClient, demoAnswer, demoHosts, scenarios, type ScenarioId } from './demo';
import { DemoControls } from './DemoControls';
import { isMessageKey } from './messages';
import { Connection } from './Connection';
import { Investigation } from './Investigation';
import { Logo, Modal } from './ui';
import { Sidebar } from './Sidebar';
import { HostPicker } from './HostPicker';
import { utc } from './format';
import { useInvestigation } from './useInvestigation';
import { ContainerView } from './ContainerView';
import { useSystemStatus } from './useSystemStatus';
import { SystemStatusPanel, SystemStatusTrigger } from './SystemStatus';
import { useInventory } from './useInventory';
import { useGroups } from './useGroups';
import { GroupScope } from './GroupScope';

interface ConnectionState {
  client: Transport;
  demo: boolean;
  id: number;
}

const hostPickerTriggerId = 'workspace-host-picker';

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
  const [choosingHost, setChoosingHost] = useState(false);
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
    setChoosingHost(false);
    setShowExample(demo);
  }

  /** Retry discovery without dismissing an open host picker. */
  function retryHosts() {
    setHostLoading(true);
    setAttempt((value) => value + 1);
  }

  return (
    <>
      <Workspace
        key={`${connection.id}-${host}`}
        connection={connection}
        hosts={displayHosts}
        host={host}
        changeHost={(value) => {
          setHost(value);
          setShowExample(false);
        }}
        showExample={showExample}
        hostError={translatedHostError}
        hostLoading={hostLoading}
        retryHosts={retryHosts}
        openHostPicker={() => setChoosingHost(true)}
        connect={() => setConnecting(true)}
        returnDemo={() => changeConnection(new DemoClient(), true)}
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
              setHost(value);
              setShowExample(false);
            }
          }}
          connect={() => {
            setChoosingHost(false);
            setConnecting(true);
          }}
        />
      )}
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
  openHostPicker: () => void;
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
  openHostPicker,
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
  const groupScope = useGroups(client, host);
  const availability = useSystemStatus(client, host, !hostLoading, !demo);
  const [statusOpen, setStatusOpen] = useState(false);
  const { inventory, loading, fetching, inventoryError, lastRefreshed, refreshAcknowledged, refresh } = useInventory(
    client,
    host,
    !demo,
  );
  const [selected, setSelected] = useState<Container>();
  const [viewingContainer, setViewingContainer] = useState(false);
  const [draft, setDraft] = useState('');
  const [scenario, setScenario] = useState<ScenarioId>(demoClient?.scenario ?? 'crash_loop');
  const [menu, setMenu] = useState(false);
  const [help, setHelp] = useState(false);
  const name = hosts.find((row) => row.id === host)?.name ?? host;

  /** Recheck stale availability before opening its retained observations. */
  function openStatus() {
    availability.refreshIfStale();
    setStatusOpen(true);
  }

  /** Make fixture selection a clearly simulated example rather than a live diagnosis. */
  function chooseScenario(value: ScenarioId) {
    if (!demoClient) return;
    demoClient.setScenario(value);
    setScenario(value);
    const item = scenarios.find((row) => row.id === value)!;
    const answer = demoClient.example(host);
    setViewingContainer(false);
    investigation.example(answer, item.query);
    setDraft('');
  }

  /** Open direct Docker reads without changing a draft or invoking diagnostic work. */
  function chooseContainer(container: Container) {
    setSelected(container);
    setViewingContainer(true);
    setMenu(false);
    requestAnimationFrame(() => document.getElementById('container-title')?.focus({ preventScroll: true }));
  }

  /** Return to retained diagnostic results and place keyboard focus in the visible workspace. */
  function openInvestigation(focusQuery = false) {
    setViewingContainer(false);
    setMenu(false);
    requestAnimationFrame(() => document.getElementById(focusQuery ? 'query' : 'workspace-title')?.focus());
  }

  /** Start an isolated model session for the exact container, preserving previous diagnostic snapshots. */
  function diagnoseContainer(container: Container) {
    if (investigation.running || availability.blockedReason) return;
    const matched = scenarios.find((row) => row.container === container.name);
    if (demoClient && matched) {
      demoClient.setScenario(matched.id);
      setScenario(matched.id);
    }
    openInvestigation();
    void investigation.run(
      t('Investigate {name} ({id}). What happened, and what evidence supports it?', {
        name: container.name,
        id: container.id,
      }),
      true,
    );
  }

  /** Start an explicitly scoped group investigation without changing historical observations. */
  function diagnoseGroup() {
    if (!groupScope.group || investigation.running || availability.blockedReason) return;
    const { kind, name: groupName } = groupScope.group;
    openInvestigation();
    void investigation.run(
      t('Investigate the {kind} group {name}. Check every member and explain the failures.', {
        kind: kind === 'compose' ? 'Compose' : 'Swarm',
        name: groupName,
      }),
      true,
      { kind, name: groupName },
    );
  }

  const sidebarProps = {
    hosts,
    host,
    hostLoading,
    hostError,
    retryHosts,
    inventory: groupScope.group
      ? inventory.filter((row) => groupScope.group!.container_ids.includes(row.id))
      : inventory,
    inventoryError,
    lastRefreshed,
    refreshAcknowledged: Boolean(refreshAcknowledged),
    loading,
    fetching,
    selected: viewingContainer ? (selected?.id ?? '') : '',
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
      openInvestigation();
    },
    openInvestigation: () => openInvestigation(),
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
          <Logo />
        </span>
        <div className="breadcrumb">
          <button
            className="workspace-trigger"
            id={hostPickerTriggerId}
            title={t('Workspace: choose host')}
            aria-haspopup="dialog"
            onClick={openHostPicker}
          >
            <span>{t('Workspace')}</span>
            <ChevronRight className="breadcrumb-divider" size={13} />
            <strong>{name || t('Docker hosts')}</strong>
            <ChevronDown size={13} />
          </button>
        </div>
        <div className="connection-state">
          <span className={`scope-dot${demo ? ' demo-dot' : ''}`} />
          {t(demo ? 'Demo' : 'API mode')}
          <SystemStatusTrigger status={availability} open={openStatus} />
          <button className="text-button" onClick={connect}>
            {t(demo ? 'Connect API' : 'Change connection')}
            <ArrowRight size={13} />
          </button>
        </div>
      </header>
      <main id="main" className="sheet">
        <div className="page-heading">
          <div>
            <h1 id="workspace-title" tabIndex={-1}>
              {t(viewingContainer ? 'Container overview' : 'Container investigation')}
            </h1>
            <p>
              {viewingContainer
                ? t('Read-only · no model request')
                : inventory[0]
                  ? t(
                      demo
                        ? 'Inventory observed {time} · snapshots, not a live feed'
                        : 'Inventory observed {time} · refreshes every 10 seconds',
                      { time: utc(inventory[0].observed_at) },
                    )
                  : t('Docker diagnostics · host-scoped sessions')}
            </p>
          </div>
          <div className="heading-actions">
            <LanguageSwitch />
            {!viewingContainer && (
              <button className="secondary" aria-label={t('Ask DockSight')} onClick={() => openInvestigation(true)}>
                <MessageSquarePlus size={15} />
                {t('Ask DockSight')}
              </button>
            )}
          </div>
        </div>
        {!viewingContainer && (
          <GroupScope
            scope={groupScope}
            diagnose={diagnoseGroup}
            blocked={investigation.running || Boolean(availability.blockedReason)}
          />
        )}
        {availability.blockedReason && (
          <div className="dependency-notice" role="status">
            <p>{t(availability.blockedReason)}</p>
            <button className="text-button" onClick={openStatus}>
              {t('View system status')}
              <ArrowRight size={14} />
            </button>
          </div>
        )}
        {demo && (
          <div className={`demo-bar${viewingContainer ? ' demo-bar-compact' : ''}`}>
            <div>
              <FlaskConical size={15} />
              <strong>{t('Demo')}</strong>
              <span>{t('Example data from a fictional host. Connect an API to diagnose your Docker.')}</span>
            </div>
            {!viewingContainer && (
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
            )}
          </div>
        )}
        {demoClient && !viewingContainer && (
          <DemoControls client={demoClient} refresh={refresh} running={investigation.running} />
        )}
        {hostError && (
          <div className="turn-error">
            <p role="alert">{hostError}</p>
            <button className="secondary" onClick={retryHosts}>
              {t('Retry connection')}
            </button>
          </div>
        )}
        {selected && (
          <div hidden={!viewingContainer}>
            <ContainerView
              key={selected.id}
              client={client}
              container={selected}
              running={investigation.running}
              blocked={Boolean(availability.blockedReason)}
              automatic={!demo}
              active={viewingContainer}
              back={() => openInvestigation()}
              diagnose={diagnoseContainer}
            />
          </div>
        )}
        <div hidden={viewingContainer}>
          <Investigation
            investigation={investigation}
            client={client}
            demo={demo}
            containers={inventory}
            draft={draft}
            setDraft={setDraft}
            host={host}
            blocked={Boolean(availability.blockedReason)}
            group={groupScope.group ? { kind: groupScope.group.kind, name: groupScope.group.name } : undefined}
          />
        </div>
      </main>
      {statusOpen && (
        <SystemStatusPanel
          status={availability}
          host={name || host}
          demo={demo}
          close={() => setStatusOpen(false)}
          connect={() => {
            setStatusOpen(false);
            connect();
          }}
        />
      )}
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
