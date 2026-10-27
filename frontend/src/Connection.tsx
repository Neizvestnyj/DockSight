import { useState } from 'react';
import { ArrowRight, PlugZap } from 'lucide-react';
import { ApiClient } from './api';
import { Modal } from './ui';

/** Accept a browser API endpoint, never a Docker daemon URL or a compiled credential. */
export function Connection({ close, connect }: { close: () => void; connect: (client: ApiClient) => void }) {
  const [endpoint, setEndpoint] = useState('/api/v1');
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  return (
    <Modal title="Connect to DockSight" close={close}>
      <p>Use your DockSight backend and its configured Docker hosts.</p>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          const base = endpoint.trim().replace(/\/$/, '');
          try {
            const url = new URL(base, window.location.origin);
            const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
            if (url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback))
              throw new Error('Use HTTPS, or HTTP on localhost.');
            if (url.username || url.password || url.search || url.hash || !url.pathname.endsWith('/api/v1'))
              throw new Error('The API base must end in /api/v1 and contain no credentials or query.');
            if (!token.trim()) throw new Error('Enter a bearer token.');
            connect(new ApiClient(base, token.trim()));
          } catch (failure) {
            setError(failure instanceof Error ? failure.message : 'Check the API endpoint.');
          }
        }}
      >
        <label className="field">
          API base URL
          <input
            required
            value={endpoint}
            onChange={(event) => setEndpoint(event.target.value)}
            aria-describedby="api-help"
          />
        </label>
        <p id="api-help" className="section-note">
          The local Vite proxy forwards /api to 127.0.0.1:8000. A remote API must allow this browser origin through
          CORS.
        </p>
        <label className="field">
          Bearer token
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
          Kept only in this tab's memory. Refreshing disconnects the API and returns to demo.
        </p>
        {error && (
          <p className="inline-error" role="alert">
            {error}
          </p>
        )}
        <footer className="modal-actions">
          <button type="button" className="secondary" onClick={close}>
            Cancel
          </button>
          <button type="submit" className="primary">
            <PlugZap size={15} />
            Connect
            <ArrowRight size={15} />
          </button>
        </footer>
      </form>
    </Modal>
  );
}
