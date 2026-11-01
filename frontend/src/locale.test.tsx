import { chooseOption } from '../test-utils/select';
import '@testing-library/jest-dom/vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { LocaleProvider, LanguageSwitch } from './LocaleProvider';
import { useLocale } from './locale';
import { resolveLocale, translate } from './messages';
import App from './App';

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.restoreAllMocks();
  document.documentElement.lang = 'en';
});

/** Expose the active language without involving any transport or server data. */
function Probe() {
  const { locale, t } = useLocale();
  return (
    <>
      <LanguageSwitch />
      <p>
        {locale}: {t('Container investigation')}
      </p>
    </>
  );
}

describe('language preference', () => {
  it('matches system language regions, uses the first supported preference, and falls back to English', () => {
    expect(resolveLocale('system', ['ru-RU', 'en-US'])).toBe('ru');
    expect(resolveLocale('system', ['EN-gb', 'ru'])).toBe('en');
    expect(resolveLocale('system', ['de-DE', 'ru'])).toBe('ru');
    expect(resolveLocale('system', ['fr-FR'])).toBe('en');
    expect(resolveLocale('system', [])).toBe('en');
    expect(resolveLocale('en', ['ru-RU'])).toBe('en');
  });

  it('defaults to Russian, persists a manual override, and supports returning to system language', async () => {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['ru-RU']);
    const view = render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByText('ru: Диагностика контейнера')).toBeInTheDocument();
    expect(document.documentElement.lang).toBe('ru');
    chooseOption(screen.getByRole('combobox', { name: 'Язык' }), 'en');
    expect(localStorage.getItem('docksight.locale')).toBe('en');
    view.unmount();
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByText('en: Container investigation')).toBeInTheDocument();
    chooseOption(screen.getByRole('combobox', { name: 'Language' }), 'system');
    await waitFor(() => expect(document.documentElement.lang).toBe('ru'));
  });

  it('follows languagechange only in automatic mode', () => {
    const languages = vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['en-US']);
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    languages.mockReturnValue(['ru-RU']);
    fireEvent(window, new Event('languagechange'));
    expect(screen.getByText('ru: Диагностика контейнера')).toBeInTheDocument();
    chooseOption(screen.getByRole('combobox', { name: 'Язык' }), 'en');
    fireEvent(window, new Event('languagechange'));
    expect(screen.getByText('en: Container investigation')).toBeInTheDocument();
  });

  it('ignores invalid stored values and keeps following system language', () => {
    localStorage.setItem('docksight.locale', 'invalid');
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['ru-RU']);
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    expect(screen.getByRole('combobox', { name: 'Язык' })).toHaveTextContent('Системный');
    expect(screen.getByText('ru: Диагностика контейнера')).toBeInTheDocument();
  });

  it('keeps switching usable when browser storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('Blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Blocked');
    });
    render(
      <LocaleProvider>
        <Probe />
      </LocaleProvider>,
    );
    chooseOption(screen.getByRole('combobox', { name: 'Language' }), 'ru');
    expect(screen.getByText('ru: Диагностика контейнера')).toBeInTheDocument();
  });

  it('uses Russian plurals for returned lines', () => {
    expect(translate('ru', '{count} lines returned', { count: 1 })).toBe('Получена 1 строка');
    expect(translate('ru', '{count} lines returned', { count: 2 })).toBe('Получены 2 строки');
    expect(translate('ru', '{count} lines returned', { count: 5 })).toBe('Получено 5 строк');
    expect(translate('ru', '{count} lines returned', { count: 21 })).toBe('Получена 21 строка');
    expect(translate('ru', '{count} lines returned', { count: 22 })).toBe('Получены 22 строки');
    expect(translate('ru', '{count} lines returned', { count: 25 })).toBe('Получено 25 строк');
    expect(translate('en', '{count} lines returned', { count: 1 })).toBe('1 line returned');
  });

  it('localizes demo copy without replacing evidence or the current action', async () => {
    render(<App />);
    const log = 'ValueError: invalid application configuration';
    chooseOption(screen.getByRole('combobox', { name: 'Language' }), 'ru');
    expect(screen.getByRole('heading', { name: 'Диагностика контейнера' })).toBeInTheDocument();
    expect(screen.getByText(log, { exact: true })).toBeInTheDocument();
    expect(screen.getByText('production', { exact: true })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Почему payments-api постоянно перезапускается?' })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: 'Проверить остановку' }));
    expect(screen.getByRole('dialog')).toHaveTextContent('1'.repeat(64));
    expect(screen.getByRole('button', { name: 'Подтвердить остановку' })).toBeInTheDocument();
  });

  it('localizes the OOM example and identifies the simulated host without fabricating log lines', async () => {
    render(<App />);
    chooseOption(screen.getByRole('combobox', { name: 'Language' }), 'ru');
    chooseOption(screen.getByLabelText('Демо-сценарий'), 'oom');
    expect(screen.getByRole('heading', { name: 'Почему report-worker завершился с кодом 137?' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Объяснение модели' })).toHaveTextContent(
      'Docker сообщает, что report-worker был завершён из-за нехватки памяти (OOM)',
    );
    expect(screen.getByRole('combobox', { name: 'Настроенный хост' })).toHaveTextContent('Демо-хост / EU');
    expect(screen.getByRole('group', { name: 'Логи контейнера' })).toHaveTextContent('Получено 0 строк');
    expect(screen.queryByRole('checkbox', { name: '200 строк логов' })).not.toBeInTheDocument();
    expect(
      await screen.findByText('Пример данных вымышленного хоста. Подключите API для диагностики своего Docker.'),
    ).toBeInTheDocument();
  });
});
