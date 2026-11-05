import { useLocale } from './locale';
import { useState } from 'react';
import { ArrowRight, PlugZap } from 'lucide-react';
import { ApiClient } from './api';
import { Modal } from './ui';
import { isMessageKey, type MessageKey } from './messages';

/** Accept a browser API endpoint, never a Docker daemon URL or a compiled credential. */
export function Connection({ close, connect }: { close: () => void; connect: (client: ApiClient) => void }) {
  const { t } = useLocale();
  const [endpoint, setEndpoint] = useState('/api/v1');
  const [token, setToken] = useState('');
  const [error, setError] = useState<MessageKey | ''>('');
  const [busy, setBusy] = useState(false);
  return (
    <Modal title={t('Connect to DockSight')} close={close}>
      <p>{t('Use your DockSight backend and its configured Docker hosts.')}</p>
      <form
        onSubmit={async (event) => {
          event.preventDefault();
          if (busy) return;
          const base = endpoint.trim().replace(/\/$/, '');
          try {
            const url = new URL(base, window.location.origin);
            const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
            if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback))
              throw new Error('Use HTTPS, or HTTP on localhost.');
            if (url.username || url.password || url.search || url.hash || !url.pathname.endsWith('/api/v1'))
              throw new Error('The API base must end in /api/v1 and contain no credentials or query.');
            if (!token.trim()) throw new Error('Enter a bearer token.');
            setBusy(true);
            const secret = token.trim();
            const sameOrigin = url.origin === window.location.origin;
            const client = new ApiClient(sameOrigin ? url.pathname : base, sameOrigin ? '' : secret);
            try {
              if (sameOrigin) await client.login(secret);
              else await client.hosts(new AbortController().signal);
              setToken('');
              connect(client);
            } finally {
              setToken('');
              setBusy(false);
            }
          } catch (failure) {
            const message = failure instanceof Error ? failure.message : '';
            setError(isMessageKey(message) ? message : 'Check the API endpoint.');
          }
        }}
      >
        <label className="field">
          {t('API base URL')}
          <input
            required
            value={endpoint}
            onChange={(event) => setEndpoint(event.target.value)}
            aria-describedby="api-help"
          />
        </label>
        <p id="api-help" className="section-note">
          {t(
            'Same-origin API login restores your session after refresh. A separate-origin API uses transient bearer access and requires reconnecting.',
          )}
        </p>
        <label className="field">
          {t('Bearer token')}
          <input
            type="password"
            autoComplete="off"
            required
            value={token}
            onChange={(event) => setToken(event.target.value)}
            aria-describedby="token-help"
          />
        </label>
        <p id="token-help" className="section-note">
          {t('The token is cleared after login. Cookie and CSRF credentials are never stored in browser storage.')}
        </p>
        {error && (
          <p className="inline-error" role="alert">
            {t(error)}
          </p>
        )}
        <footer className="modal-actions">
          <button type="button" className="secondary" onClick={close}>
            {t('Cancel')}
          </button>
          <button type="submit" className="primary" disabled={busy}>
            <PlugZap size={15} />
            {t('Connect')}
            <ArrowRight size={15} />
          </button>
        </footer>
      </form>
    </Modal>
  );
}
