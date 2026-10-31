import { useEffect, useState } from 'react';
import { Check, ChevronDown, LoaderCircle, RefreshCw, Search } from 'lucide-react';
import { useLocale } from './locale';
import { Modal } from './ui';
import { providerNames, type ModelSelection, type ProviderId } from './model-contracts';
import type { CheckState } from './contracts';
import type { useModelCatalog } from './useModelCatalog';

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
      className="model-picker-trigger"
      aria-label={`${t('Choose model')}${selection ? `: ${providerNames[selection.provider]} · ${selection.model}` : ''}`}
      aria-haspopup="dialog"
      disabled={running}
      title={running ? t('Model selection is available after this answer finishes.') : t('Choose model')}
      onClick={open}
    >
      <span className={`check-dot check-${state}`} aria-hidden="true" />
      {selection ? (
        <>
          <span className="model-provider-name">{providerNames[selection.provider]} · </span>
          <span className="model-trigger-name">{selection.model}</span>
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
    <Modal title={t('Choose model')} close={close} returnFocusId="model-picker-trigger" className="model-picker">
      {demo && <p className="model-picker-demo">{t('Demo models · no provider requests')}</p>}
      {providerError ? (
        <div className="model-catalog-error" role="status">
          <p>{t('Could not load providers. Your current model is unchanged.')}</p>
          <button className="text-button" onClick={() => void loadProviders()}>
            {t('Retry')}
          </button>
        </div>
      ) : !providers ? (
        <p className="model-catalog-message" role="status">
          <LoaderCircle size={15} className="spin" />
          {t('Loading providers…')}
        </p>
      ) : (
        <>
          <label className="field model-provider-field">
            {t('Provider')}
            <select
              value={provider}
              onChange={(event) => {
                setProvider(event.target.value as ProviderId);
                setSearch('');
              }}
            >
              {providers.providers.map((row) => (
                <option key={row.id} value={row.id} disabled={!row.configured}>
                  {row.name}
                  {!row.configured ? ` · ${t('Not configured')}` : ''}
                </option>
              ))}
            </select>
          </label>
          <div className="model-search-row">
            <label className="model-search">
              <Search size={15} aria-hidden="true" />
              <span className="sr-only">{t('Search models')}</span>
              <input
                type="search"
                placeholder={t('Search models')}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </label>
            <button
              className="icon-button"
              aria-label={t('Refresh models')}
              title={t('Refresh models')}
              disabled={read?.loading || !configured}
              onClick={() => void loadCatalog(provider, true)}
            >
              <RefreshCw size={16} className={read?.loading ? 'spin' : undefined} />
            </button>
          </div>
          <div className="model-catalog-feedback" role="status">
            {failed
              ? t('Could not refresh the catalog. Showing previously received or configured models.')
              : read?.loading
                ? t(read.data?.models.length ? 'Refreshing models…' : 'Loading models…')
                : t('Models: {count}', { count: read?.data?.models.length ?? 0 })}
          </div>
          <div className="model-options" aria-label={t('Models')} aria-busy={read?.loading ?? false}>
            {rows.map((row) => {
              const selected = selection?.provider === provider && selection.model === row.id;
              return (
                <button
                  key={row.id}
                  className="model-option"
                  aria-pressed={selected}
                  onClick={() => choose({ provider, model: row.id })}
                >
                  <span>{row.id}</span>
                  {selected && <Check size={16} aria-hidden="true" />}
                </button>
              );
            })}
            {!rows.length && !read?.loading && (
              <p className="model-catalog-message">{t(search ? 'No matching models.' : 'No models were returned.')}</p>
            )}
          </div>
        </>
      )}
      <footer className="model-picker-foot">{t('Applies to the next question. History is preserved.')}</footer>
    </Modal>
  );
}
