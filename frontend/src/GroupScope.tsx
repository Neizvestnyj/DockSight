import { RefreshCw } from 'lucide-react';
import { useLocale } from './locale';
import type { useGroups, GroupKind } from './useGroups';

/** Keep group discovery explicit and distinguish project containers from Swarm task replicas. */
export function GroupScope({
  scope,
  diagnose,
  blocked,
}: {
  scope: ReturnType<typeof useGroups>;
  diagnose: () => void;
  blocked: boolean;
}) {
  const { t } = useLocale();
  return (
    <div className="group-scope">
      <label>
        {t('Inventory scope')}
        <select value={scope.kind} onChange={(event) => scope.changeKind(event.target.value as GroupKind)}>
          <option value="all">{t('All containers')}</option>
          <option value="compose">{t('Compose projects')}</option>
          <option value="swarm">{t('Swarm stacks')}</option>
        </select>
      </label>
      {scope.kind !== 'all' && (
        <>
          <label>
            {t('Group')}
            <select
              value={scope.group?.name ?? ''}
              disabled={scope.loading || scope.error}
              onChange={(event) => scope.choose(event.target.value)}
            >
              <option value="">{t(scope.loading ? 'Reading groups…' : 'Choose a group')}</option>
              {scope.groups.map((row) => (
                <option key={row.name} value={row.name}>
                  {row.name}
                </option>
              ))}
            </select>
          </label>
          <div className="group-scope-actions">
            <button
              className="secondary"
              disabled={!scope.group || blocked || scope.loading || scope.error}
              onClick={diagnose}
            >
              {t('Diagnose group')}
            </button>
            <button
              className="icon-button"
              aria-label={t('Refresh groups')}
              disabled={scope.loading}
              onClick={scope.refresh}
            >
              <RefreshCw size={14} className={scope.loading ? 'spin' : ''} />
            </button>
          </div>
          {scope.error ? (
            <p role="alert">
              {t(
                scope.kind === 'swarm'
                  ? 'Could not read stacks. Swarm requires a manager on this host.'
                  : 'Could not read Compose projects. Retry the group read.',
              )}
            </p>
          ) : (
            !scope.loading && !scope.groups.length && <p>{t('No groups of this kind were returned.')}</p>
          )}
          {scope.group?.truncated && <p className="warning-text">{t('Group inventory may be incomplete.')}</p>}
        </>
      )}
    </div>
  );
}
