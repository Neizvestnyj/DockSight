import sharedStyles from '../../shared/ui/Shared.module.css';
import { useEffect, useId, useState, type ReactNode } from 'react';
import { Languages } from 'lucide-react';
import { LocaleContext } from '../../shared/i18n/locale';
import { useLocale } from '../../shared/i18n/locale';
import { resolveLocale, translate, type LocalePreference } from '../../shared/i18n/messages';
import { Select } from '../../shared/ui/Select';
import styles from './LocaleProvider.module.css';

const storageKey = 'docksight.locale';

/** Treat unavailable or invalid preference storage as automatic language selection. */
function storedPreference(): LocalePreference {
  try {
    const value = localStorage.getItem(storageKey);
    return value === 'en' || value === 'ru' ? value : 'system';
  } catch {
    return 'system';
  }
}

/** Observe browser language changes and persist only the non-sensitive locale preference. */
export function LocaleProvider({ children }: { children: ReactNode }) {
  const [preference, setPreferenceValue] = useState(storedPreference);
  const [languages, setLanguages] = useState(() =>
    navigator.languages.length ? navigator.languages : [navigator.language],
  );
  const locale = resolveLocale(preference, languages);
  useEffect(() => {
    const changed = () => setLanguages(navigator.languages.length ? navigator.languages : [navigator.language]);
    window.addEventListener('languagechange', changed);
    return () => window.removeEventListener('languagechange', changed);
  }, []);
  useEffect(() => {
    document.documentElement.lang = locale;
    document.title = locale === 'ru' ? 'DockSight — Диагностика' : 'DockSight — Diagnostics';
  }, [locale]);

  /** Keep switching usable even when storage is disabled or full. */
  function setPreference(value: LocalePreference) {
    setPreferenceValue(value);
    try {
      localStorage.setItem(storageKey, value);
    } catch {
      /* The in-memory preference still applies to the active tab. */
    }
  }

  return (
    <LocaleContext value={{ locale, preference, setPreference, t: (key, values) => translate(locale, key, values) }}>
      {children}
    </LocaleContext>
  );
}

/** Expose automatic and explicit languages with stable language names on every viewport. */
export function LanguageSwitch() {
  const { preference, setPreference, t } = useLocale();
  const id = useId();
  return (
    <label className={`${styles['language-switch']}`} htmlFor={id}>
      <Languages size={16} aria-hidden="true" />
      <span className={`sr-only ${sharedStyles['sr-only']}`}>{t('Language')}</span>
      <Select<LocalePreference>
        id={id}
        label={t('Language')}
        value={preference}
        onChange={setPreference}
        options={[
          { value: 'system', label: t('System') },
          { value: 'en', label: 'English' },
          { value: 'ru', label: 'Русский' },
        ]}
      />
    </label>
  );
}
