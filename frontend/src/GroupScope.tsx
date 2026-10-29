import { MessageSquarePlus, RefreshCw } from 'lucide-react';
import { useLocale } from './locale';
import type { useGroups, GroupKind } from './useGroups';

/** Offer optional explicit scope beside the investigation, leaving named-group chat automatic. */
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
    <section className="group-scope" aria-label={t('Investigation scope')}>
      <label>
        {t('Investigation scope')}
        <select value={scope.kind} onChange={(event) => scope.changeKind(event.target.value as GroupKind)}>
          <option value="all">{t('Automatic')}</option>
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
              <MessageSquarePlus size={15} />
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
      <p className="scope-help">
        {t('Optional. Name a project or stack in your question; DockSight selects it automatically.')}
      </p>
    </section>
  );
}
