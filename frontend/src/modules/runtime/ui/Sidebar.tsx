import feedbackStyles from '../../../shared/ui/Feedback.module.css';
import sharedStyles from '../../../shared/ui/Shared.module.css';
import controlStyles from '../../../shared/ui/Controls.module.css';
import { useLocale } from '../../../shared/i18n/locale';
import { Select } from '../../../shared/ui/Select';
import { useId, useRef, useState } from 'react';
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Box,
  Cable,
  Check,
  CircleHelp,
  Plus,
  Search,
  RefreshCw,
  Server,
} from 'lucide-react';
import { targetKey, type Container, type GroupTarget, type Host } from '../../../shared/contracts/contracts';
import type { Transport } from '../../../shared/contracts/transport';
import { ContainerSearch } from './ContainerSearch';
import { Logo, ContainerStatus } from '../../../shared/ui/ui';
import { utc } from '../../../shared/lib/format';
import type { ReactNode } from 'react';
import styles from './Sidebar.module.css';

interface Props {
  savedChats?: ReactNode;
  searchClient?: Transport;
  searchGroup?: GroupTarget;
  transient?: boolean;
  hosts: Host[];
  host: string;
  changeHost: (host: string) => void;
  hostLoading: boolean;
  hostError: string;
  retryHosts: () => void;
  inventory: Container[];
  inventoryError: string;
  lastRefreshed?: string;
  refreshAcknowledged: boolean;
  loading: boolean;
  fetching: boolean;
  selected: string;
  chooseContainer: (container: Container) => void;
  refresh: () => void;
  demo: boolean;
  newInvestigation: () => void;
  openInvestigation: () => void;
  about: () => void;
  connect: () => void;
  returnDemo: () => void;
}

/** Keep configured hosts and Docker inventory in the same scoped navigation on every device. */
export function Sidebar({
  hosts,
  host,
  changeHost,
  hostLoading,
  hostError,
  retryHosts,
  inventory,
  inventoryError,
  lastRefreshed,
  refreshAcknowledged,
  loading,
  fetching,
  selected,
  chooseContainer,
  refresh,
  demo,
  newInvestigation,
  openInvestigation,
  about,
  connect,
  returnDemo,
  savedChats,
  transient,
  searchClient,
  searchGroup,
}: Props) {
  const { t } = useLocale();
  const hostSelectId = useId();
  const [searchOpen, setSearchOpen] = useState(false);
  const searchTrigger = useRef<HTMLButtonElement>(null);
  /** Report inventory refresh progress and retained observations. */
  function inventoryFeedback() {
    return (
      <>
        <div
          className={`${styles['inventory-feedback']} inventory-feedback`}
          role="status"
          aria-live="polite"
          aria-atomic="true"
        >
          {loading && host ? (
            t('Refreshing container list…')
          ) : inventoryError ? (
            <>
              {t('Refresh failed')}
              {lastRefreshed && <span>{t('Showing the last received list.')}</span>}
            </>
          ) : lastRefreshed ? (
            <span key={lastRefreshed}>
              {refreshAcknowledged && <strong>{t('Container list refreshed')}</strong>}
              {t('List received at {time}', { time: utc(lastRefreshed) })}
            </span>
          ) : null}
        </div>
      </>
    );
  }

  /** Render exact observed container identities and states. */
  function containerList() {
    return (
      <>
        {loading && host && !inventory.length ? (
          <div className={`${styles['inventory-loading']}`} aria-hidden="true">
            <div />
            <div />
            <div />
          </div>
        ) : inventory.length ? (
          <div className={`${styles['container-list']} container-list`} aria-busy={loading}>
            {inventory.map((container) => (
              <button
                className={`${styles['container-row']}${selected === container.id ? ' selected' : ''}`}
                key={container.id}
                onClick={() => chooseContainer(container)}
                title={container.name}
                aria-pressed={selected === container.id}
              >
                <span className={`${styles['container-name']}`}>
                  <Box size={14} />
                  <span>{container.name}</span>
                </span>
                <ContainerStatus state={container.state} health={container.health} />
                {container.state === 'exited' && container.exit_code !== 0 && (
                  <span className={`${styles['container-exit']} negative ${feedbackStyles['negative']}`}>
                    {t('Exit code')} {container.exit_code}
                  </span>
                )}
                {container.compose_project && (
                  <span className={`${styles['container-group']}`}>{container.compose_project}</span>
                )}
              </button>
            ))}
          </div>
        ) : !inventoryError && !loading ? (
          <p className={`empty-note ${controlStyles['empty-note']}`}>{t('No containers on this host.')}</p>
        ) : null}
      </>
    );
  }

  /** Select only from configured hosts. */
  function hostSwitch() {
    return (
      <>
        <div className={`${styles['host-switch']}`}>
          <label htmlFor={hostSelectId}>
            <Server size={14} />
            {t('Configured host')}
          </label>
          <Select
            id={hostSelectId}
            label={t('Configured host')}
            value={host}
            onChange={changeHost}
            disabled={hostLoading || !hosts.length}
            options={
              hosts.length
                ? hosts.map((row) => ({ value: row.id, label: row.name }))
                : [{ value: '', label: t(hostLoading ? 'Loading hosts…' : 'No configured hosts') }]
            }
          />
          <span className={`${styles['host-id']}`}>{host || t('Connect a backend to begin')}</span>
        </div>
      </>
    );
  }

  /** Explain the active session and offer its connection controls. */
  function connectionDetails() {
    return (
      <>
        <div className={`${styles['sidebar-bottom']}`}>
          {transient && <p>{t('Reconnect after refreshing this tab.')}</p>}
          <button className={`text-button ${controlStyles['text-button']}`} onClick={about}>
            <CircleHelp size={15} />
            {t('About this workspace')}
            <ArrowRight size={14} />
          </button>
          <button className={`${styles['connection-button']}`} onClick={demo ? connect : returnDemo}>
            <Cable size={16} />
            {t(demo ? 'Connect your API' : 'Return to demo')}
            <ArrowUpRight size={14} />
          </button>
        </div>
      </>
    );
  }

  return (
    <>
      <div className={`${styles['brand']}`}>
        <button
          type="button"
          className={`brand-link ${sharedStyles['brand-link']}`}
          aria-label={t('DockSight: return to diagnosis')}
          onClick={openInvestigation}
        >
          <Logo />
        </button>
        <span className={`${styles['brand-sub']}`}>{t('Docker diagnostics')}</span>
      </div>
      {hostSwitch()}
      {hostError && (
        <div className={`sidebar-error ${sharedStyles['sidebar-error']}`} role="alert">
          <p>{hostError}</p>
          <button className={`text-button ${controlStyles['text-button']}`} onClick={retryHosts}>
            {t('Retry hosts')}
          </button>
        </div>
      )}
      <div className={`${styles['workspace-nav']} workspace-nav`}>
        <Activity size={16} />
        <button className={`text-button ${controlStyles['text-button']}`} onClick={newInvestigation}>
          {t('Diagnostics')}
        </button>
        <button
          className={`icon-button ${controlStyles['icon-button']}`}
          aria-label={t('New investigation')}
          title={t('New investigation')}
          onClick={() => {
            newInvestigation();
          }}
        >
          <Plus size={17} />
        </button>
      </div>
      {savedChats}
      <section className={`${styles['inventory']}`}>
        <header>
          <h2>{t('Containers')}</h2>
          {!searchOpen && <span>{inventory.length}</span>}
          {searchClient && (
            <button
              ref={searchTrigger}
              type="button"
              className={controlStyles['icon-button']}
              aria-label={t('Search containers')}
              aria-expanded={searchOpen}
              onClick={() => setSearchOpen((open) => !open)}
            >
              <Search size={14} aria-hidden="true" />
            </button>
          )}
          <button
            className={`icon-button ${controlStyles['icon-button']}${fetching ? ` refreshing ${feedbackStyles['refreshing']}` : ''}`}
            aria-busy={fetching}
            aria-label={t('Refresh container inventory')}
            title={t(refreshAcknowledged ? 'Container list refreshed' : 'Refresh container inventory')}
            onClick={refresh}
            disabled={loading || !host}
          >
            {refreshAcknowledged && !fetching ? <Check size={14} /> : <RefreshCw size={14} />}
          </button>
        </header>
        {inventoryFeedback()}
        {inventoryError && (
          <div className={`sidebar-error ${sharedStyles['sidebar-error']}`}>
            <p>{t('Could not read Docker inventory.')}</p>
            <p role="alert">{inventoryError}</p>
            <button className={`text-button ${controlStyles['text-button']}`} onClick={refresh}>
              {t('Retry inventory')}
            </button>
          </div>
        )}
        {searchOpen && searchClient ? (
          <ContainerSearch
            key={searchGroup ? targetKey(searchGroup) : host}
            client={searchClient}
            host={host}
            group={searchGroup}
            selected={selected}
            choose={chooseContainer}
            close={() => {
              setSearchOpen(false);
              searchTrigger.current?.focus();
            }}
            browsing={containerList()}
          />
        ) : (
          containerList()
        )}
      </section>
      {connectionDetails()}
    </>
  );
}
