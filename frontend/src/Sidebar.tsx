import { useId } from 'react';
import { Activity, ArrowRight, ArrowUpRight, Box, Cable, CircleHelp, Plus, RefreshCw, Server } from 'lucide-react';
import type { Container, Host } from './contracts';
import { Mark, Status } from './ui';

interface Props {
  hosts: Host[];
  host: string;
  changeHost: (host: string) => void;
  hostLoading: boolean;
  hostError: string;
  retryHosts: () => void;
  inventory: Container[];
  inventoryError: string;
  loading: boolean;
  selected: string;
  chooseContainer: (container: Container) => void;
  refresh: () => void;
  demo: boolean;
  newInvestigation: () => void;
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
  loading,
  selected,
  chooseContainer,
  refresh,
  demo,
  newInvestigation,
  about,
  connect,
  returnDemo,
}: Props) {
  const hostSelectId = useId();
  return (
    <>
      <div className="brand">
        <Mark />
        <span>
          DockSight<span className="brand-sub">Docker diagnostics</span>
        </span>
      </div>
      <div className="host-switch">
        <label htmlFor={hostSelectId}>
          <Server size={14} />
          Configured host
        </label>
        <select
          id={hostSelectId}
          aria-label="Configured host"
          value={host}
          onChange={(event) => {
            changeHost(event.target.value);
          }}
          disabled={hostLoading || !hosts.length}
        >
          {!hosts.length && <option value="">{hostLoading ? 'Loading hosts…' : 'No configured hosts'}</option>}
          {hosts.map((row) => (
            <option value={row.id} key={row.id}>
              {row.name}
            </option>
          ))}
        </select>
        <span className="host-id">{host || 'Connect a backend to begin'}</span>
      </div>
      {hostError && (
        <div className="sidebar-error" role="alert">
          <p>{hostError}</p>
          <button className="text-button" onClick={retryHosts}>
            Retry hosts
          </button>
        </div>
      )}
      <div className="workspace-nav">
        <Activity size={16} />
        <span>Investigations</span>
        <button
          className="icon-button"
          aria-label="New investigation"
          title="New investigation"
          onClick={() => {
            newInvestigation();
          }}
        >
          <Plus size={17} />
        </button>
      </div>
      <section className="inventory">
        <header>
          <h2>Containers</h2>
          <span>{inventory.length}</span>
          <button
            className={`icon-button${loading ? ' refreshing' : ''}`}
            aria-label="Refresh container inventory"
            onClick={refresh}
            disabled={loading || !host}
          >
            <RefreshCw size={14} />
          </button>
        </header>
        {inventoryError ? (
          <div className="sidebar-error">
            <p role="alert">{inventoryError}</p>
            <button className="text-button" onClick={refresh}>
              Retry inventory
            </button>
          </div>
        ) : loading && host ? (
          <div className="inventory-loading" role="status">
            Reading Docker inventory…
            <div />
            <div />
            <div />
          </div>
        ) : inventory.length ? (
          <div className="container-list">
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
        ) : (
          <p className="empty-note">No containers on this host.</p>
        )}
      </section>
      <div className="sidebar-bottom">
        <p>
          Sessions live in this tab.
          <br />
          Backend state is temporary.
        </p>
        <button className="text-button" onClick={about}>
          <CircleHelp size={15} />
          About this workspace
          <ArrowRight size={14} />
        </button>
        <button className="connection-button" onClick={demo ? connect : returnDemo}>
          <Cable size={16} />
          {demo ? 'Connect your API' : 'Return to demo'}
          <ArrowUpRight size={14} />
        </button>
      </div>
    </>
  );
}
