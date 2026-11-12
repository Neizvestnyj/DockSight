import feedbackStyles from '../../../shared/ui/Feedback.module.css';
import sharedStyles from '../../../shared/ui/Shared.module.css';
import controlStyles from '../../../shared/ui/Controls.module.css';
import { useEffect, useState } from 'react';
import { Check, ChevronDown, LoaderCircle, RefreshCw, Search } from 'lucide-react';
import { useLocale } from '../../../shared/i18n/locale';
import { Modal } from '../../../shared/ui/ui';
import { providerNames, type ModelSelection, type ProviderId } from '../../../shared/contracts/model-contracts';
import type { CheckState } from '../../../shared/contracts/contracts';
import type { useModelCatalog } from '../model/useModelCatalog';
import { Select } from '../../../shared/ui/Select';
import styles from './ModelPicker.module.css';
import checkStyles from '../../../shared/ui/CheckIndicator.module.css';

type Catalogs = ReturnType<typeof useModelCatalog>;

/** Name the model independently of infrastructure health and make the selection discoverable. */
export function ModelTrigger({
  selection,
  state,
  running,
  open,
}: {
  selection?: ModelSelection;
  state: CheckState;
  running: boolean;
  open: () => void;
}) {
  const { t } = useLocale();
  return (
    <button
      id="model-picker-trigger"
      className={`${styles['model-picker-trigger']}`}
      aria-label={`${t('Choose model')}${selection ? `: ${providerNames[selection.provider]} · ${selection.model}` : ''}`}
      aria-haspopup="dialog"
      disabled={running}
      title={running ? t('Model selection is available after this answer finishes.') : t('Choose model')}
      onClick={open}
    >
      <span className={`${checkStyles['check-dot']} ${checkStyles[`check-${state}`]}`} aria-hidden="true" />
      {selection ? (
        <>
          <span className={`${styles['model-provider-name']}`}>{providerNames[selection.provider]} · </span>
          <span className={`${styles['model-trigger-name']}`}>{selection.model}</span>
        </>
      ) : (
        <span>{t('Model')}</span>
      )}
      <ChevronDown size={13} aria-hidden="true" />
    </button>
  );
}

/** Offer configured provider catalogs without changing the active model until an explicit row selection. */
export function ModelPicker({
  catalog,
  selection,
  demo,
  choose,
  close,
}: {
  catalog: Catalogs;
  selection?: ModelSelection;
  demo: boolean;
  choose: (selection: ModelSelection) => void;
  close: () => void;
}) {
  const { t } = useLocale();
  const [providerOverride, setProvider] = useState<ProviderId>();
  const [search, setSearch] = useState('');
  const { providers, providerError, catalogs, loadProviders, loadCatalog } = catalog;
  const provider = providerOverride ?? selection?.provider ?? providers?.default.provider ?? 'ollama';
  const configured = providers?.providers.find((row) => row.id === provider)?.configured;
  const read = catalogs[provider];
  const rows = read?.data?.models.filter((row) => row.id.toLowerCase().includes(search.trim().toLowerCase())) ?? [];
  const failed = read?.error || (read?.data && read.data.code !== 'ok');

  useEffect(() => {
    void loadProviders();
  }, [loadProviders]);
  useEffect(() => {
    if (configured) void loadCatalog(provider);
  }, [provider, configured, loadCatalog]);

  return (
    <Modal
      title={t('Choose model')}
      close={close}
      returnFocusId="model-picker-trigger"
      className={`${styles['model-picker']}`}
    >
      {demo && <p className={`${styles['model-picker-demo']}`}>{t('Demo models · no provider requests')}</p>}
      {providerError ? (
        <div className={`${styles['model-catalog-error']}`} role="status">
          <p>{t('Could not load providers. Your current model is unchanged.')}</p>
          <button className={`text-button ${controlStyles['text-button']}`} onClick={() => void loadProviders()}>
            {t('Retry')}
          </button>
        </div>
      ) : !providers ? (
        <p className={`${styles['model-catalog-message']}`} role="status">
          <LoaderCircle size={15} className={`spin ${feedbackStyles['spin']}`} />
          {t('Loading providers…')}
        </p>
      ) : (
        <>
          <label className={`field ${controlStyles['field']} ${styles['model-provider-field']}`}>
            {t('Provider')}
            <Select<ProviderId>
              label={t('Provider')}
              value={provider}
              onChange={(next) => {
                setProvider(next);
                setSearch('');
              }}
              options={providers.providers.map((row) => ({
                value: row.id,
                label: `${row.name}${!row.configured ? ` · ${t('Not configured')}` : ''}`,
                disabled: !row.configured,
              }))}
            />
          </label>
          <div className={`${styles['model-search-row']}`}>
            <label className={`${styles['model-search']}`}>
              <Search size={15} aria-hidden="true" />
              <span className={`sr-only ${sharedStyles['sr-only']}`}>{t('Search models')}</span>
              <input
                type="search"
                placeholder={t('Search models')}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <button
              className={`icon-button ${controlStyles['icon-button']}`}
              aria-label={t('Refresh models')}
              title={t('Refresh models')}
              disabled={read?.loading || !configured}
              onClick={() => void loadCatalog(provider, true)}
            >
              <RefreshCw size={16} className={read?.loading ? `spin ${feedbackStyles['spin']}` : undefined} />
            </button>
          </div>
          <div className={`${styles['model-catalog-feedback']}`} role="status">
            {failed
              ? t('Could not refresh the catalog. Showing previously received or configured models.')
              : read?.loading
                ? t(read.data?.models.length ? 'Refreshing models…' : 'Loading models…')
                : t('Models: {count}', { count: read?.data?.models.length ?? 0 })}
          </div>
          <div className={`${styles['model-options']}`} aria-label={t('Models')} aria-busy={read?.loading ?? false}>
            {rows.map((row) => {
              const selected = selection?.provider === provider && selection.model === row.id;
              return (
                <button
                  key={row.id}
                  className={`${styles['model-option']}`}
                  aria-pressed={selected}
                  onClick={() => choose({ provider, model: row.id })}
                >
                  <span>{row.id}</span>
                  {selected && <Check size={16} aria-hidden="true" />}
                </button>
              );
            })}
            {!rows.length && !read?.loading && (
              <p className={`${styles['model-catalog-message']}`}>
                {t(search ? 'No matching models.' : 'No models were returned.')}
              </p>
            )}
          </div>
        </>
      )}
      <footer className={`${styles['model-picker-foot']}`}>
        {t('Applies to the next question. History is preserved.')}
      </footer>
    </Modal>
  );
}
