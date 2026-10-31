import { Box, Layers, Server } from 'lucide-react';
import type { Answer, Evidence } from './contracts';
import { evidenceNames, evidenceResource } from './evidence';
import { utc } from './format';
import { useLocale } from './locale';

/** Keep repeated observation types distinguishable by their exact historical resource and capture time. */
export function EvidenceTrail({
  answer,
  selected,
  inspect,
}: {
  answer: Answer;
  selected: string | null;
  inspect: (id: string) => void;
}) {
  const { t } = useLocale();
  const groups = new Map<string, { name: string; rows: Evidence[] }>();
  for (const row of answer.evidence) {
    const { key, name } = evidenceResource(row, answer);
    const group = groups.get(key) ?? { name, rows: [] };
    group.rows.push(row);
    groups.set(key, group);
  }
  return (
    <div className="evidence-picker" role="region" aria-label={t('Observation sources')} tabIndex={0}>
      {[...groups].map(([key, group]) => (
        <fieldset key={key} className="evidence-resource">
          <legend>
            {group.rows[0]?.container_id ? (
              <Box size={14} />
            ) : group.rows[0]?.kind === 'host' ? (
              <Server size={14} />
            ) : (
              <Layers size={14} />
            )}
            <span>{group.name}</span>
          </legend>
          {group.rows.map((row) => (
            <button
              key={row.id}
              onClick={() => inspect(row.id)}
              className={selected === row.id ? 'selected' : ''}
              aria-pressed={selected === row.id}
              aria-controls="evidence-observation"
              title={`${t('Observation ID')}: ${row.id}`}
            >
              <span>{t(evidenceNames[row.kind])}</span>
              <time dateTime={row.observed_at}>{utc(row.observed_at)}</time>
            </button>
          ))}
        </fieldset>
      ))}
    </div>
  );
}
