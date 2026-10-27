import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ArrowRight, Check, RefreshCw } from 'lucide-react';
import { executeOnce } from './api';
import type { Action, Transport } from './contracts';
import { Modal, Status } from './ui';

interface Props {
  action: Action;
  client: Transport;
  demo: boolean;
  name?: string;
  close: () => void;
  update: (action: Action) => void;
  keys: Map<string, string>;
}

/** Keep confirmation, execution delivery, and authoritative Docker outcome separate. */
export function ActionReview({ action, client, demo, name, close, update, keys }: Props) {
  const [current, setCurrent] = useState(action);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [now, setNow] = useState(Date.now);
  const sent = useRef(false);
  const [submitted, setSubmitted] = useState(false);
  const [checkedPrepared, setCheckedPrepared] = useState(false);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const expired = current.state === 'prepared' && now >= Date.parse(current.expires_at);
  const state = expired ? 'expired' : current.state;

  /** Publish a server outcome without changing the card's historical observation. */
  function publish(result: Action) {
    setCurrent(result);
    update(result);
    if (result.state === 'prepared') {
      sent.current = false;
      setSubmitted(false);
      setCheckedPrepared(true);
    }
  }

  /** Confirm once; preserve the execution key even if delivery becomes ambiguous. */
  async function confirm() {
    if (busy || sent.current || state !== 'prepared') return;
    sent.current = true;
    setSubmitted(true);
    setBusy(true);
    setError('');
    const key = keys.get(current.id) ?? crypto.randomUUID();
    keys.set(current.id, key);
    try {
      publish(await executeOnce(client, current.id, key));
    } catch (failure) {
      setError(
        failure instanceof Error ? failure.message : 'Execution response unavailable. Check the existing action.',
      );
    } finally {
      setBusy(false);
    }
  }

  /** Query the retained action independently of the earlier HTTP response. */
  async function check() {
    setBusy(true);
    setError('');
    try {
      publish(await client.action(current.id));
    } catch {
      setError(
        'Cannot read this action. The Docker result remains unconfirmed. After a backend restart, inspect Docker before preparing another action.',
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      title={current.state === 'prepared' && !submitted ? `Review ${current.operation}` : 'Action outcome'}
      close={close}
    >
      {demo && <p className="demo-notice">Demo operation · no Docker mutation</p>}
      <div className="action-operation">
        <span>{current.operation === 'stop' ? 'Stop container' : 'Restart container'}</span>
        <Status state={state} />
      </div>
      <p>
        {current.operation === 'stop'
          ? 'The container will stop serving its workload.'
          : 'The container will be interrupted and started again.'}
      </p>
      <dl className="confirmation-facts">
        <div>
          <dt>Host</dt>
          <dd>{current.host}</dd>
        </div>
        <div>
          <dt>Container</dt>
          <dd>{name ?? 'Exact target below'}</dd>
        </div>
        <div>
          <dt>Exact container ID</dt>
          <dd>
            <code>{current.container_id}</code>
          </dd>
        </div>
        <div>
          <dt>Expires</dt>
          <dd>{new Date(current.expires_at).toISOString().replace('T', ' ').replace('.000Z', ' UTC')}</dd>
        </div>
        <div>
          <dt>Prepared action ID</dt>
          <dd>
            <code>{current.id}</code>
          </dd>
        </div>
      </dl>
      {current.state !== 'prepared' && (
        <p className="operation-message">
          {current.state === 'succeeded' && <Check size={16} />}
          {current.message}
        </p>
      )}
      {state === 'indeterminate' && (
        <p className="inline-warning">
          <AlertTriangle size={17} />
          The Docker result is not confirmed. Inspect Docker directly. This mutation cannot be repeated automatically;
          the target is fenced by the backend.
        </p>
      )}
      {state === 'succeeded' && (
        <p className="section-note">
          These cards remain historical observations. Run a new diagnosis to observe the current container state.
        </p>
      )}
      {state === 'expired' && (
        <p className="inline-warning">
          This action has expired. Run a new diagnosis to obtain a fresh server-prepared action.
        </p>
      )}
      {error && (
        <p role="alert" className="inline-error">
          {error}
        </p>
      )}
      <footer className="modal-actions">
        <button className="secondary" onClick={close}>
          {state === 'prepared' ? 'Cancel' : 'Close'}
        </button>
        {(submitted || keys.has(current.id) || current.state !== 'prepared') && (
          <button className="secondary" disabled={busy} onClick={() => void check()}>
            <RefreshCw size={14} />
            Check existing action
          </button>
        )}
        {state === 'prepared' && !submitted && (!keys.has(current.id) || checkedPrepared) && (
          <button className="primary" disabled={busy} onClick={() => void confirm()}>
            {keys.has(current.id) ? 'Retry confirmed' : 'Confirm'} {current.operation}
            <ArrowRight size={15} />
          </button>
        )}
        {busy && (
          <span role="status" className="muted">
            Checking delivery…
          </span>
        )}
      </footer>
    </Modal>
  );
}
