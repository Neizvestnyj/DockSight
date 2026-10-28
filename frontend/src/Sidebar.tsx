import { useLocale } from './locale';
import { useId } from 'react';
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Box,
  Cable,
  Check,
  CircleHelp,
  Plus,
  RefreshCw,
  Server,
} from 'lucide-react';
import type { Container, Host } from './contracts';
import { Logo, Status } from './ui';
import { utc } from './format';

interface Props {
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
}: Props) {
  const { t } = useLocale();
  const hostSelectId = useId();
  return (
    <>
      <div className="brand">
        <Logo />
        <span className="brand-sub">{t('Docker diagnostics')}</span>
      </div>
      <div className="host-switch">
        <label htmlFor={hostSelectId}>
          <Server size={14} />
          {t('Configured host')}
        </label>
        <select
          id={hostSelectId}
          aria-label={t('Configured host')}
          value={host}
          onChange={(event) => {
            changeHost(event.target.value);
          }}
          disabled={hostLoading || !hosts.length}
        >
          {!hosts.length && <option value="">{t(hostLoading ? 'Loading hosts…' : 'No configured hosts')}</option>}
          {hosts.map((row) => (
            <option value={row.id} key={row.id}>
              {row.name}
            </option>
          ))}
        </select>
        <span className="host-id">{host || t('Connect a backend to begin')}</span>
      </div>
      {hostError && (
        <div className="sidebar-error" role="alert">
          <p>{hostError}</p>
          <button className="text-button" onClick={retryHosts}>
            {t('Retry hosts')}
          </button>
        </div>
      )}
      <div className="workspace-nav">
        <Activity size={16} />
        <button className="text-button" onClick={openInvestigation}>
          {t('Investigations')}
        </button>
        <button
          className="icon-button"
          aria-label={t('New investigation')}
          title={t('New investigation')}
          onClick={() => {
            newInvestigation();
          }}
        >
          <Plus size={17} />
        </button>
      </div>
      <section className="inventory">
        <header>
          <h2>{t('Containers')}</h2>
          <span>{inventory.length}</span>
          <button
            className={`icon-button${fetching ? ' refreshing' : ''}`}
            aria-busy={fetching}
            aria-label={t('Refresh container inventory')}
            title={t(refreshAcknowledged ? 'Container list refreshed' : 'Refresh container inventory')}
            onClick={refresh}
            disabled={loading || !host}
          >
            {refreshAcknowledged && !fetching ? <Check size={14} /> : <RefreshCw size={14} />}
          </button>
        </header>
        <div className="inventory-feedback" role="status" aria-live="polite" aria-atomic="true">
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
        {inventoryError && (
          <div className="sidebar-error">
            <p>{t('Could not read Docker inventory.')}</p>
            <p role="alert">{inventoryError}</p>
            <button className="text-button" onClick={refresh}>
              {t('Retry inventory')}
            </button>
          </div>
        )}
        {loading && host && !inventory.length ? (
          <div className="inventory-loading" aria-hidden="true">
            <div />
            <div />
            <div />
          </div>
        ) : inventory.length ? (
          <div className="container-list" aria-busy={loading}>
            {inventory.map((container) => (
              <button
                className={`container-row${selected === container.id ? ' selected' : ''}`}
                key={container.id}
                onClick={() => chooseContainer(container)}
                title={container.name}
                aria-pressed={selected === container.id}
              >
                <span className="container-name">
                  <Box size={14} />
                  <span>{container.name}</span>
                </span>
                <Status state={container.state} />
              </button>
            ))}
          </div>
        ) : !inventoryError && !loading ? (
          <p className="empty-note">{t('No containers on this host.')}</p>
        ) : null}
      </section>
      <div className="sidebar-bottom">
        <p>
          {t('Sessions live in this tab.')}
          <br />
          {t('Backend state is temporary.')}
        </p>
        <button className="text-button" onClick={about}>
          <CircleHelp size={15} />
          {t('About this workspace')}
          <ArrowRight size={14} />
        </button>
        <button className="connection-button" onClick={demo ? connect : returnDemo}>
          <Cable size={16} />
          {t(demo ? 'Connect your API' : 'Return to demo')}
          <ArrowUpRight size={14} />
        </button>
      </div>
    </>
  );
}
