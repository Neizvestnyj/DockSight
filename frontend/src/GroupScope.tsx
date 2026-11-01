import { MessageSquarePlus, RefreshCw } from 'lucide-react';
import { useLocale } from './locale';
import type { useGroups, GroupKind } from './useGroups';
import { Select } from './Select';
import { Hint } from './Hint';

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
      <div className="scope-field">
        <div className="scope-caption">
          <span>{t('Investigation scope')}</span>
          <Hint label={t('About investigation scope')}>
            {t(
              'Leave Automatic to investigate the host. Name a project, stack, or container in your question to narrow the scope.',
            )}
          </Hint>
        </div>
        <Select<GroupKind>
          label={t('Investigation scope')}
          value={scope.kind}
          onChange={scope.changeKind}
          options={[
            { value: 'all', label: t('Automatic') },
            { value: 'compose', label: t('Compose projects') },
            { value: 'swarm', label: t('Swarm stacks') },
          ]}
        />
      </div>
      {scope.kind !== 'all' && (
        <>
          <label>
            {t('Group')}
            <Select
              label={t('Group')}
              value={scope.group?.name ?? ''}
              disabled={scope.loading || scope.error}
              onChange={scope.choose}
              options={[
                { value: '', label: t(scope.loading ? 'Reading groups…' : 'Choose a group') },
                ...scope.groups.map((row) => ({ value: row.name, label: row.name })),
              ]}
            />
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
    </section>
  );
}
