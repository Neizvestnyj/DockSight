import { useCallback, useEffect, useRef, useState, type ReactNode, type RefObject } from 'react';
import { Box } from 'lucide-react';
import type { Container, GroupTarget } from '../../../shared/contracts/contracts';
import type { ContainerSearchResult } from '../../../shared/contracts/search-contracts';
import type { Transport } from '../../../shared/contracts/transport';
import { useLocale } from '../../../shared/i18n/locale';
import { stateLabel } from '../../../shared/i18n/messages';
import { ListSearch } from '../../../shared/ui/ListSearch';
import controlStyles from '../../../shared/ui/Controls.module.css';
import styles from './Sidebar.module.css';

interface Props {
  client: Transport;
  host: string;
  group?: GroupTarget;
  selected: string;
  choose: (container: Container) => void;
  close: () => void;
  trigger?: RefObject<HTMLButtonElement | null>;
  browsing: ReactNode;
}

/** Search lightweight Docker summaries and inspect only the selected exact identity. */
export function ContainerSearch({ client, host, group, selected, choose, close, trigger, browsing }: Props) {
  const { t } = useLocale();
  const [opening, setOpening] = useState<string>();
  const [failed, setFailed] = useState<string>();
  const active = useRef<AbortController | null>(null);
  const kind = group?.kind;
  const name = group?.name;
  const load = useCallback(
    (query: string, signal: AbortSignal, before?: string) =>
      client.searchContainers(host, query, signal, kind && name ? { kind, name } : undefined, before),
    [client, host, kind, name],
  );
  useEffect(() => () => active.current?.abort(), []);

  /** Replace a pending detail read when the operator chooses another result. */
  async function open(id: string) {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setOpening(id);
    setFailed(undefined);
    try {
      const container = await client.container(host, id, controller.signal);
      if (!controller.signal.aborted) choose(container);
    } catch {
      if (!controller.signal.aborted) setFailed(id);
    } finally {
      if (!controller.signal.aborted) setOpening(undefined);
    }
  }

  /** Render current state and group directly from the summary. */
  function row(container: ContainerSearchResult) {
    const groupName = container.compose_project ?? container.swarm_stack;
    const busy = opening === container.id;
    return (
      <div key={container.id}>
        <button
          className={styles['container-row']}
          type="button"
          aria-pressed={selected === container.id}
          aria-busy={busy}
          disabled={busy}
          title={container.image}
          onClick={() => void open(container.id)}
        >
          <span className={styles['container-name']}>
            <Box size={14} aria-hidden="true" />
            <span>{container.name}</span>
          </span>
          <span className={styles['container-group']}>
            {stateLabel(container.state, t)}
            {groupName ? ` · ${groupName}` : ''}
          </span>
        </button>
        {failed === container.id && (
          <p role="alert" className={controlStyles['section-note']}>
            {t('Could not open this container.')}
          </p>
        )}
      </div>
    );
  }

  return (
    <ListSearch
      label="Search containers"
      empty="No matching containers."
      scope={name ? `${host} / ${name}` : host}
      load={load}
      row={row}
      close={close}
      trigger={trigger}
      browsing={browsing}
      onQueryChange={() => {
        active.current?.abort();
        setOpening(undefined);
        setFailed(undefined);
      }}
    />
  );
}
