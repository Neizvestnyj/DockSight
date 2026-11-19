import controlStyles from '../../../shared/ui/Controls.module.css';
import { useLocale } from '../../../shared/i18n/locale';
import type { MessageKey } from '../../../shared/i18n/messages';
import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, ArrowRight, Check, RefreshCw } from 'lucide-react';
import { executeOnce } from '../model/executeOnce';
import type { Action } from '../../../shared/contracts/contracts';
import type { Transport } from '../../../shared/contracts/transport';
import { Modal, Status } from '../../../shared/ui/ui';
import styles from './ActionReview.module.css';
import modalStyles from '../../../shared/ui/Modal.module.css';

interface Props {
  action: Action;
  client: Transport;
  demo: boolean;
  name?: string;
  close: () => void;
  update: (action: Action) => void;
  keys: Map<string, string>;
}

/** Match every response to the action the operator originally selected. */
function matchesSelection(result: Action, selected: Action) {
  return (
    result.id === selected.id &&
    result.host === selected.host &&
    result.container_id === selected.container_id &&
    result.operation === selected.operation
  );
}

/** Keep confirmation, execution delivery, and authoritative Docker outcome separate. */
export function ActionReview({ action, client, demo, name, close, update, keys }: Props) {
  const { t } = useLocale();
  const [selected] = useState(() => ({ ...action }));
  const [current, setCurrent] = useState(action);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState<MessageKey | ''>('');
  const [now, setNow] = useState(Date.now);
  const sent = useRef(false);
  const [submitted, setSubmitted] = useState(false);
  const [checkedPrepared, setCheckedPrepared] = useState(false);
  const [available, setAvailable] = useState(false);
  const [readClient, setReadClient] = useState<Transport | null>(null);
  const owner = useRef<object | null>(null);
  useEffect(() => {
    let attached = true;
    const lifetime = {};
    owner.current = lifetime;
    void client
      .action(selected.id)
      .then((result) => {
        if (!attached) return;
        if (!matchesSelection(result, selected)) throw new Error('Action response is outside the selected scope.');
        setCurrent(result);
        update(result);
        setReadClient(client);
        setAvailable(true);
        setCheckedPrepared(result.state === 'prepared');
        setError('');
      })
      .catch(() => {
        if (attached) {
          setReadClient(client);
          setAvailable(false);
          setCheckedPrepared(false);
          setError('This saved action is unavailable. Run a new diagnosis for current evidence.');
        }
      })
      .finally(() => {
        if (attached) setBusy(false);
      });
    return () => {
      attached = false;
      if (owner.current === lifetime) owner.current = null;
    };
    // Reopening requires renewed authoritative state and a closed confirmation lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected.id, client]);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const checking = busy || readClient !== client;
  const trusted = available && readClient === client;
  const expired = current.state === 'prepared' && now >= Date.parse(current.expires_at);
  const state = !trusted ? (checking ? 'checking' : 'unavailable') : expired ? 'expired' : current.state;

  /** Publish a server outcome without changing the card's historical observation. */
  function publish(result: Action) {
    if (!matchesSelection(result, selected)) throw new Error('Action response is outside the selected scope.');
    setCurrent(result);
    update(result);
    setReadClient(client);
    setAvailable(true);
    setCheckedPrepared(result.state === 'prepared');
    if (result.state === 'prepared') {
      sent.current = false;
      setSubmitted(false);
    }
  }

  /** Confirm once; preserve the execution key even if delivery becomes ambiguous. */
  async function confirm() {
    if (checking || !trusted || !checkedPrepared || sent.current || state !== 'prepared') return;
    const lifetime = owner.current;
    sent.current = true;
    setSubmitted(true);
    setBusy(true);
    setError('');
    const key = keys.get(current.id) ?? crypto.randomUUID();
    keys.set(current.id, key);
    try {
      const result = await executeOnce(client, current.id, key);
      if (owner.current !== lifetime) return;
      publish(result);
    } catch {
      if (owner.current !== lifetime) return;
      setAvailable(false);
      setCheckedPrepared(false);
      setError(
        'Execution response unavailable. The Docker result is unconfirmed. Check this existing action before retrying.',
      );
    } finally {
      if (owner.current === lifetime) setBusy(false);
    }
  }

  /** Query the retained action independently of the earlier HTTP response. */
  async function check() {
    const lifetime = owner.current;
    setBusy(true);
    setAvailable(false);
    setCheckedPrepared(false);
    setError('');
    try {
      const result = await client.action(current.id);
      if (owner.current !== lifetime) return;
      publish(result);
    } catch {
      if (owner.current !== lifetime) return;
      setError(
        'Cannot read this action. The Docker result remains unconfirmed. After a backend restart, inspect Docker before preparing another action.',
      );
    } finally {
      if (owner.current === lifetime) setBusy(false);
    }
  }

  /** Explain the authoritative outcome and any unresolved delivery state. */
  function outcomeMessages() {
    return (
      <>
        {current.state !== 'prepared' && (
          <p className={styles['operation-message']}>
            {current.state === 'succeeded' && <Check size={16} />}
            {current.message}
          </p>
        )}
        {state === 'indeterminate' && (
          <p className={`inline-warning ${controlStyles['inline-warning']}`}>
            <AlertTriangle size={17} />
            {t(
              'The Docker result is not confirmed. Inspect Docker directly. This mutation cannot be repeated automatically; the target is fenced by the backend.',
            )}
          </p>
        )}
        {state === 'succeeded' && (
          <p className={`section-note ${controlStyles['section-note']}`}>
            {t(
              'These cards remain historical observations. Run a new diagnosis to observe the current container state.',
            )}
          </p>
        )}
        {state === 'expired' && (
          <p className={`inline-warning ${controlStyles['inline-warning']}`}>
            {t('This action has expired. Run a new diagnosis to obtain a fresh server-prepared action.')}
          </p>
        )}
        {error && (
          <p role="alert" className={`inline-error ${controlStyles['inline-error']}`}>
            {t(error)}
          </p>
        )}
      </>
    );
  }

  /** Offer only operations allowed by the current authoritative action state. */
  function actionControls() {
    return (
      <footer className={`${modalStyles['modal-actions']} modal-actions`}>
        <button className={`secondary ${controlStyles['secondary']}`} onClick={close}>
          {t(state === 'prepared' ? 'Cancel' : 'Close')}
        </button>
        {(submitted || keys.has(current.id) || current.state !== 'prepared') && (
          <button
            className={`secondary ${controlStyles['secondary']}`}
            disabled={checking}
            onClick={() => void check()}
          >
            <RefreshCw size={14} />
            {t('Check existing action')}
          </button>
        )}
        {trusted &&
          checkedPrepared &&
          state === 'prepared' &&
          !submitted &&
          (!keys.has(current.id) || checkedPrepared) && (
            <button
              className={`primary ${controlStyles['primary']}`}
              disabled={checking}
              onClick={() => void confirm()}
            >
              {keys.has(current.id) ? t(`Retry confirmed ${current.operation}`) : t(`Confirm ${current.operation}`)}
              <ArrowRight size={15} />
            </button>
          )}
        {checking && (
          <span role="status" className={`muted ${controlStyles['muted']}`}>
            {t('Checking delivery…')}
          </span>
        )}
      </footer>
    );
  }

  return (
    <Modal
      title={current.state === 'prepared' && !submitted ? t(`Review ${current.operation}`) : t('Action outcome')}
      close={close}
    >
      {demo && <p className={styles['demo-notice']}>{t('Demo operation · no Docker mutation')}</p>}
      <div className={styles['action-operation']}>
        <span>{t(current.operation === 'stop' ? 'Stop container' : 'Restart container')}</span>
        <Status state={state} action />
      </div>
      <p>
        {t(
          current.operation === 'stop'
            ? 'The container will stop serving its workload.'
            : 'The container will be interrupted and started again.',
        )}
      </p>
      <dl className={`${styles['confirmation-facts']} confirmation-facts`}>
        <div>
          <dt>{t('Host')}</dt>
          <dd>{current.host}</dd>
        </div>
        <div>
          <dt>{t('Container')}</dt>
          <dd>{name ?? t('Exact target below')}</dd>
        </div>
        <div>
          <dt>{t('Exact container ID')}</dt>
          <dd>
            <code>{current.container_id}</code>
          </dd>
        </div>
        <div>
          <dt>{t('Expires')}</dt>
          <dd>{new Date(current.expires_at).toISOString().replace('T', ' ').replace('.000Z', ' UTC')}</dd>
        </div>
        <div>
          <dt>{t('Prepared action ID')}</dt>
          <dd>
            <code>{current.id}</code>
          </dd>
        </div>
      </dl>
      {outcomeMessages()}
      {actionControls()}
    </Modal>
  );
}
