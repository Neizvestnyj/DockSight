import sharedStyles from '../../shared/ui/Shared.module.css';
import controlStyles from '../../shared/ui/Controls.module.css';
import { LanguageSwitch } from '../providers/LocaleProvider';
import { useLocale } from '../../shared/i18n/locale';
import { useEffect, useState } from 'react';
import { ArrowRight, ChevronDown, ChevronRight, FlaskConical, Menu, MessageSquarePlus } from 'lucide-react';
import type { Container, DiagnosticTarget, Host } from '../../shared/contracts/contracts';
import { DemoClient, demoAnswer, scenarios, type ScenarioId } from '../../infrastructure/demo/demo';
import { DemoControls } from './DemoControls';
import { Select } from '../../shared/ui/Select';
import { isMessageKey } from '../../shared/i18n/messages';
import { Investigation } from '../../modules/investigations';
import { Logo, Modal } from '../../shared/ui/ui';
import { Sidebar } from '../../modules/runtime';
import { utc } from '../../shared/lib/format';
import { useInvestigation } from '../../modules/investigations';
import { ContainerView } from '../../modules/runtime';
import { useSystemStatus } from '../../modules/system-status';
import { SystemStatusPanel, SystemStatusTrigger } from '../../modules/system-status';
import { useInventory } from '../../modules/runtime';
import { useGroups } from '../../modules/runtime';
import { GroupScope } from '../../modules/runtime';
import type { ModelSelection } from '../../shared/contracts/model-contracts';
import { ModelPicker, ModelTrigger } from '../../modules/model-selection';
import { useModelCatalog } from '../../modules/model-selection';
import { ApiClient } from '../../infrastructure/api/api';
import type { useWorkspace, useSavedInvestigations } from '../../modules/investigations';
import { SavedInvestigations } from '../../modules/investigations';
import { hostPickerTriggerId, type ConnectionState } from './types';
import styles from './WorkspacePage.module.css';

interface WorkspaceProps {
  saved: ReturnType<typeof useWorkspace>;
  history: ReturnType<typeof useSavedInvestigations>;
  logout: () => void;
  modelSelection?: ModelSelection;
  chooseModel: (selection: ModelSelection) => void;
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
export function WorkspacePage({
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
  modelSelection,
  chooseModel,
  saved,
  history,
  logout,
}: WorkspaceProps) {
  const { t } = useLocale();
  const { client, demo } = connection;
  const demoClient = client instanceof DemoClient ? client : null;
  const [initial] = useState(() =>
    demoClient && showExample && host === 'demo-eu' ? demoClient.remember(demoAnswer('crash_loop', host)) : undefined,
  );
  const investigation = useInvestigation(
    client,
    host,
    initial,
    modelSelection,
    demo
      ? undefined
      : {
          ...saved,
          enabled: !saved.loading,
          conflict: saved.conflictWith,
          changed: () => {
            void history.refresh();
          },
        },
  );
  const [scopeTarget, setScopeTarget] = useState<DiagnosticTarget | null>(saved.detail?.workspace.target ?? null);
  const initialGroup = scopeTarget && scopeTarget.kind !== 'container' ? scopeTarget : undefined;
  const groupScope = useGroups(client, host, demo ? undefined : initialGroup);
  const availability = useSystemStatus(client, host, !hostLoading, !demo, modelSelection);
  const catalog = useModelCatalog(client);
  const [modelPickerOpen, setModelPickerOpen] = useState(false);
  const effectiveModel = selectedModel();
  const [statusOpen, setStatusOpen] = useState(false);
  const { inventory, loading, fetching, inventoryError, lastRefreshed, refreshAcknowledged, refresh } = useInventory(
    client,
    host,
    !demo,
  );
  const [selected, setSelected] = useState<Container>();
  const [viewingContainer, setViewingContainer] = useState(false);
  const [demoDraft, setDemoDraft] = useState('');
  const draft = demo ? demoDraft : saved.draft;
  const setDraft = demo ? setDemoDraft : saved.setDraft;
  const [scenario, setScenario] = useState<ScenarioId>(demoClient?.scenario ?? 'crash_loop');
  const [menu, setMenu] = useState(false);
  const [help, setHelp] = useState(false);
  const [composerVisible, setComposerVisible] = useState(false);
  const name = hostName();
  const configured = hosts.some((row) => row.id === host);
  const [targetAvailable, setTargetAvailable] = useState(scopeTarget?.kind !== 'container');
  const [selectionError, setSelectionError] = useState(false);
  const modelAvailable = modelIsAvailable();
  const groupAvailable = groupIsAvailable();
  const continuingBlocked = continuationIsBlocked();

  /** Display the explicit model or the backend's currently reported default. */
  function selectedModel() {
    return (
      modelSelection ??
      (availability.data ? { provider: availability.data.provider, model: availability.data.model } : undefined)
    );
  }

  /** Resolve only the configured host ID's current label. */
  function hostName() {
    return hosts.find((row) => row.id === host)?.name ?? host;
  }

  /** Require the exact saved model to remain in its configured catalog. */
  function modelIsAvailable() {
    return (
      !modelSelection ||
      Boolean(
        catalog.providers?.providers.some((row) => row.id === modelSelection.provider && row.configured) &&
        catalog.catalogs[modelSelection.provider]?.data?.models.some((row) => row.id === modelSelection.model),
      )
    );
  }

  /** Keep archived group scope readable until the same current group is selected. */
  function groupIsAvailable() {
    return !scopeTarget || scopeTarget.kind === 'container' || Boolean(groupScope.group);
  }

  /** Block continuation while its exact saved scope or revision is unavailable. */
  function continuationIsBlocked() {
    return (
      !demo &&
      (!configured ||
        !modelAvailable ||
        !targetAvailable ||
        !groupAvailable ||
        saved.loading ||
        !saved.detail ||
        saved.saveState === 'conflict' ||
        saved.saveState === 'error')
    );
  }

  const { loadProviders, loadCatalog, providers } = catalog;
  useEffect(() => {
    if (demo || !modelSelection) return;
    void loadProviders();
    if (providers?.providers.some((row) => row.id === modelSelection.provider && row.configured))
      void loadCatalog(modelSelection.provider);
  }, [demo, modelSelection, providers, loadProviders, loadCatalog]);

  useEffect(() => {
    if (demo || scopeTarget?.kind !== 'container') return;
    const controller = new AbortController();
    void client
      .container(host, scopeTarget.id, controller.signal)
      .then(() => {
        if (!controller.signal.aborted) setTargetAvailable(true);
      })
      .catch(() => {
        if (!controller.signal.aborted) setTargetAvailable(false);
      });
    return () => controller.abort();
  }, [client, host, demo, scopeTarget]);

  useEffect(() => {
    if (demo || !saved.detail || saved.detail.workspace.view !== 'containers' || hostLoading) return;
    const target = saved.detail.workspace.selected_container;
    if (!target || !configured) return;
    const controller = new AbortController();
    void client
      .container(host, target.id, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setSelected(value);
          setViewingContainer(true);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setSelectionError(true);
      });
    return () => controller.abort();
    // Restore exact selection only when this chat opens, never match by name.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, host, saved.detail?.id, hostLoading]);

  useEffect(() => {
    const input = document.getElementById('query');
    if (!input || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver(([entry]) => setComposerVisible(entry?.isIntersecting ?? false));
    observer.observe(input);
    return () => observer.disconnect();
  }, []);

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
    setSelectionError(false);
    if (!demo)
      saved.patch({
        selected_container: { kind: 'container', id: container.id, name: container.name },
        view: 'containers',
      });
    requestAnimationFrame(() => document.getElementById('container-title')?.focus({ preventScroll: true }));
  }

  /** Return to retained diagnostic results and place keyboard focus in the visible workspace. */
  function openInvestigation(focusQuery = false) {
    setViewingContainer(false);
    setMenu(false);
    if (!demo && saved.detail?.workspace.view !== 'diagnostics') saved.patch({ view: 'diagnostics' });
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
      demo ? undefined : { kind: 'container', id: container.id, name: container.name },
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

  /** Assemble the same host and chat navigation for desktop and mobile. */
  function sidebarProperties() {
    return {
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
        if (demo) {
          investigation.clear();
          setDraft('');
        } else if (configured)
          void saved.create(host).then(() => {
            void history.refresh();
            requestAnimationFrame(() => document.getElementById('query')?.focus());
          });
        openInvestigation(true);
      },
      openInvestigation: () => openInvestigation(),
      about: () => {
        setMenu(false);
        setHelp(true);
      },
      savedChats: !demo ? (
        <SavedInvestigations
          {...history}
          selected={saved.detail?.id}
          open={(id) => {
            setMenu(false);
            void saved.open(id);
          }}
          remove={(id) => {
            void history.remove(id).then((removed) => {
              if (removed && saved.detail?.id === id) {
                const next = history.items.find((row) => row.id !== id);
                if (next) void saved.open(next.id);
                else void saved.create(host);
              }
            });
          }}
        />
      ) : undefined,
      transient: client instanceof ApiClient && client.authentication === 'bearer',
    };
  }
  const sidebarProps = sidebarProperties();

  /** Render the host, connection, and model controls. */
  function workspaceHeader() {
    return (
      <>
        <header className={`${styles['topbar']}`}>
          <button
            className={`icon-button ${controlStyles['icon-button']} ${styles['mobile-menu']}`}
            aria-label={t('Open host and containers')}
            onClick={() => setMenu(true)}
          >
            <Menu size={19} />
          </button>
          <button
            type="button"
            className={`${styles['mobile-brand']} brand-link ${sharedStyles['brand-link']}`}
            aria-label={t('DockSight: return to diagnosis')}
            onClick={() => openInvestigation()}
          >
            <Logo />
          </button>
          <div className={`${styles.breadcrumb} breadcrumb`}>
            <button
              className={`${styles['workspace-trigger']}`}
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
          <div className={`${styles['connection-state']}`}>
            <span
              className={`scope-dot ${sharedStyles['scope-dot']}${demo ? ` demo-dot ${sharedStyles['demo-dot']}` : ''}`}
            />
            {t(demo ? 'Demo' : 'API mode')}
            <SystemStatusTrigger status={availability} open={openStatus} />
            <ModelTrigger
              selection={effectiveModel}
              state={availability.data?.model_check.state ?? 'not_checked'}
              running={investigation.running}
              open={() => setModelPickerOpen(true)}
            />
            <button className={`text-button ${controlStyles['text-button']}`} onClick={connect}>
              {t(demo ? 'Connect API' : 'Change connection')}
              <ArrowRight size={13} />
            </button>
            {!demo && (
              <button className={`text-button ${controlStyles['text-button']}`} onClick={logout}>
                {t('Sign out')}
              </button>
            )}
          </div>
        </header>
      </>
    );
  }

  /** Render the current workspace heading and navigation. */
  function pageHeading() {
    return (
      <>
        <div className={`${styles['page-heading']}`}>
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
          <div className={`${styles['heading-actions']}`}>
            <LanguageSwitch />
            {!viewingContainer && !composerVisible && (
              <button
                className={`secondary ${controlStyles['secondary']}`}
                aria-label={t('Ask DockSight')}
                onClick={() => openInvestigation(true)}
              >
                <MessageSquarePlus size={15} />
                {t('Ask DockSight')}
              </button>
            )}
          </div>
        </div>
      </>
    );
  }

  /** Explain host selection and saved-chat availability. */
  function hostNotices() {
    return (
      <>
        {!demo && (!host || !configured) && (
          <div className={`${styles['dependency-notice']}`} role="status">
            <p>{t('Choose a configured host to continue. Saved evidence remains readable.')}</p>
            <button className={`secondary ${controlStyles['secondary']}`} onClick={openHostPicker}>
              {t('Choose a host')}
            </button>
          </div>
        )}
        {!demo && !saved.detail && configured && (
          <button className={`secondary ${controlStyles['secondary']}`} onClick={() => void saved.create(host)}>
            {t('New investigation')}
          </button>
        )}
        {!demo && saved.loading && <p role="status">{t('Loading saved chat…')}</p>}
        {!demo && saved.error && (
          <p role="alert">
            {t(isMessageKey(saved.error) ? saved.error : 'Could not refresh saved chat. Retry the read.')}
          </p>
        )}
      </>
    );
  }

  /** Show draft acknowledgement and explicit conflict controls. */
  function draftStatus() {
    return (
      <>
        {!demo && saved.detail && (
          <div className={`${styles['workspace-save']}`} role="status">
            <span>
              {t(
                saved.saveState === 'saved'
                  ? 'Draft saved'
                  : saved.saveState === 'saving'
                    ? 'Saving draft…'
                    : saved.saveState === 'conflict'
                      ? 'This chat changed in another tab. Your draft is unsaved.'
                      : 'Draft unsaved',
              )}
            </span>
            {saved.saveState === 'conflict' && (
              <>
                <button className={`text-button ${controlStyles['text-button']}`} onClick={saved.reloadConflict}>
                  {t('Reload saved draft')}
                </button>
                <button className={`secondary ${controlStyles['secondary']}`} onClick={() => void saved.useDraft()}>
                  {t('Use this draft')}
                </button>
              </>
            )}
            {saved.saveState === 'error' && (
              <button className={`text-button ${controlStyles['text-button']}`} onClick={() => void saved.flush()}>
                {t('Retry save')}
              </button>
            )}
          </div>
        )}
      </>
    );
  }

  /** Keep exact scope selection and availability explanations together. */
  function scopeControls() {
    return (
      <>
        {!viewingContainer &&
          (scopeTarget?.kind === 'container' && !demo ? (
            <div className={`${styles['dependency-notice']}`}>
              <p>
                {t('Saved container scope')}: {scopeTarget.name} · <code>{scopeTarget.id}</code>
              </p>
              <button
                className={`secondary ${controlStyles['secondary']}`}
                onClick={() => {
                  setScopeTarget(null);
                  setTargetAvailable(true);
                  saved.patch({ target: null });
                }}
              >
                {t('Use host scope')}
              </button>
            </div>
          ) : (
            <GroupScope
              scope={{
                ...groupScope,
                changeKind: (kind) => {
                  groupScope.changeKind(kind);
                  if (!demo) {
                    setScopeTarget(null);
                    setTargetAvailable(true);
                    saved.patch({ target: null });
                  }
                },
                choose: (name) => {
                  groupScope.choose(name);
                  if (!demo && groupScope.kind !== 'all') {
                    const target = name ? { kind: groupScope.kind, name } : null;
                    setScopeTarget(target);
                    saved.patch({ target });
                  }
                },
              }}
              diagnose={diagnoseGroup}
              blocked={continuingBlocked || investigation.running || Boolean(availability.blockedReason)}
            />
          ))}
        {!demo && (!modelAvailable || !targetAvailable || !groupAvailable) && (
          <p className={`inline-warning ${controlStyles['inline-warning']}`} role="status">
            {t('A saved model or target is unavailable. Choose a current model or scope to continue.')}
          </p>
        )}
        {selectionError && (
          <p className={`inline-warning ${controlStyles['inline-warning']}`} role="status">
            {t('The saved container selection is unavailable. Select a current container by its exact ID.')}
          </p>
        )}
        {availability.blockedReason && (
          <div className={`${styles['dependency-notice']}`} role="status">
            <p>{t(availability.blockedReason)}</p>
            <button className={`text-button ${controlStyles['text-button']}`} onClick={openStatus}>
              {t('View system status')}
              <ArrowRight size={14} />
            </button>
          </div>
        )}
      </>
    );
  }

  /** Render Demo controls and host read failures. */
  function demoAndHostStatus() {
    return (
      <>
        {demo && (
          <div className={`${styles['demo-bar']} demo-bar${viewingContainer ? ` ${styles['demo-bar-compact']}` : ''}`}>
            <div>
              <FlaskConical size={15} />
              <strong>{t('Demo')}</strong>
              <span>{t('Example data from a fictional host. Connect an API to diagnose your Docker.')}</span>
            </div>
            {!viewingContainer && (
              <label>
                {t('Scenario')}
                <Select<ScenarioId>
                  label={t('Demo scenario')}
                  value={scenario}
                  onChange={chooseScenario}
                  onReselect={chooseScenario}
                  disabled={investigation.running}
                  options={scenarios.map((item) => ({ value: item.id, label: t(item.name) }))}
                />
              </label>
            )}
          </div>
        )}
        {demoClient && !viewingContainer && (
          <DemoControls client={demoClient} refresh={refresh} running={investigation.running} />
        )}
        {hostError && (
          <div className={`turn-error ${sharedStyles['turn-error']}`}>
            <p role="alert">{hostError}</p>
            <button className={`secondary ${controlStyles['secondary']}`} onClick={retryHosts}>
              {t('Retry connection')}
            </button>
          </div>
        )}
      </>
    );
  }

  /** Keep the current container and investigation mounted in their existing views. */
  function workspaceContent() {
    return (
      <>
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
            blocked={continuingBlocked || Boolean(availability.blockedReason)}
            group={groupScope.group ? { kind: groupScope.group.kind, name: groupScope.group.name } : undefined}
            target={!demo ? (scopeTarget ?? undefined) : undefined}
          />
        </div>
      </>
    );
  }

  /** Render the existing status, model, mobile, and help dialogs. */
  function workspaceDialogs() {
    return (
      <>
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
        {modelPickerOpen && (
          <ModelPicker
            catalog={catalog}
            selection={effectiveModel}
            demo={demo}
            close={() => setModelPickerOpen(false)}
            choose={(selection) => {
              if (investigation.running) return;
              chooseModel(selection);
              setModelPickerOpen(false);
            }}
          />
        )}
        {menu && (
          <Modal title={t('Host & containers')} close={() => setMenu(false)}>
            <div className={`${styles['mobile-sidebar']} mobile-sidebar`}>
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
                demo
                  ? 'Demo chats are simulated and live only in this tab.'
                  : 'Saved chats and acknowledged drafts stay on your backend. Continuing a chat gathers fresh Docker evidence.',
              )}
            </p>
            <p>
              {demo
                ? t('All current observations are fixture-based examples. Connect an API for real Docker evidence.')
                : t(
                    client instanceof ApiClient && client.authentication === 'cookie'
                      ? 'Your browser session uses an HttpOnly cookie. CSRF authority stays only in memory.'
                      : 'Your bearer token is held only in this tab’s memory and is discarded when you disconnect or reload.',
                  )}
            </p>
          </Modal>
        )}
      </>
    );
  }

  return (
    <div className={`${styles['app-shell']}`}>
      <a className={`${styles['skip-link']}`} href="#main">
        {t('Skip to investigation')}
      </a>
      <aside className={`${styles.sidebar} sidebar`} aria-label={t('Host and container inventory')}>
        <Sidebar {...sidebarProps} />
      </aside>
      {workspaceHeader()}
      <main id="main" className={`${styles['sheet']}`}>
        {pageHeading()}
        {hostNotices()}
        {draftStatus()}
        {scopeControls()}
        {demoAndHostStatus()}
        {workspaceContent()}
      </main>
      {workspaceDialogs()}
    </div>
  );
}
