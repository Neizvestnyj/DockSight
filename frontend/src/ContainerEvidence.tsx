import type { ReactNode } from 'react';
import type { ContainerWidgetGroup } from './evidence';
import { useLocale } from './locale';

/** Frame a container's historical state and log sections as one diagnostic subject. */
export function ContainerEvidence({
  group,
  active,
  children,
}: {
  group: ContainerWidgetGroup;
  active: boolean;
  children: ReactNode;
}) {
  const { t } = useLocale();
  return (
    <section
      className={`container-evidence${active ? ' linked' : ''}`}
      aria-label={t('Container evidence: {name}', { name: group.name })}
    >
      <header className="container-evidence-heading">
        <h3>{group.name}</h3>
        <span>
          {group.host} <span aria-hidden="true">·</span> <code title={group.id}>{group.id.slice(0, 12)}</code>
        </span>
      </header>
      {!group.widgets.some((row) => row.widget_type === 'container_status') && (
        <p className="container-evidence-note">{t('State was not included in this answer.')}</p>
      )}
      {children}
      {!group.widgets.some((row) => row.widget_type === 'log_anomalies') && (
        <p className="container-evidence-note">{t('No log card was returned for this container.')}</p>
      )}
    </section>
  );
}
