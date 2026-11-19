import { createContext, useContext } from 'react';
import { translate, type Locale, type LocalePreference, type Translator } from './messages';

export interface LocaleContextValue {
  locale: Locale;
  preference: LocalePreference;
  setPreference: (preference: LocalePreference) => void;
  t: Translator;
}

export const LocaleContext = createContext<LocaleContextValue>({
  locale: 'en',
  preference: 'system',
  setPreference: () => undefined,
  t: (key, values) => translate('en', key, values),
});

/** Read the interface language without coupling runtime transports to presentation. */
export function useLocale(): LocaleContextValue {
  return useContext(LocaleContext);
}
