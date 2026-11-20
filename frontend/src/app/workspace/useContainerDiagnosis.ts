import { useEffect, useEffectEvent, useRef } from 'react';
import type { Container, DiagnosticTarget } from '../../shared/contracts/contracts';
import type { useInvestigation, useWorkspace } from '../../modules/investigations';
import { useLocale } from '../../shared/i18n/locale';

type ContainerTarget = Extract<DiagnosticTarget, { kind: 'container' }>;

interface ContainerDiagnosisContext {
  host: string;
  selected?: Container;
  draft: string;
  saved: ReturnType<typeof useWorkspace>;
  investigation: ReturnType<typeof useInvestigation>;
  blocked: boolean;
  openInvestigation: () => void;
  refreshHistory: () => Promise<void>;
  startDemo: (container: Container, query: string, target: ContainerTarget, startsNew: boolean) => void;
}

/** Route an explicit container diagnosis to its exact saved or Demo chat. */
export function useContainerDiagnosis({
  host,
  selected,
  draft,
  saved,
  investigation,
  blocked,
  openInvestigation,
  refreshHistory,
  startDemo,
}: ContainerDiagnosisContext) {
  const { t } = useLocale();
  const creating = useRef(false);
  const { lastTarget } = investigation;
  const occupied = Boolean(investigation.turns.length || saved.detail?.turn_count || draft);
  const separate = occupied && (lastTarget?.kind !== 'container' || lastTarget.id !== selected?.id);

  const submitInitial = useEffectEvent((id: string) => {
    const diagnosis = saved.takeDiagnosis(id);
    if (!diagnosis) return;
    openInvestigation();
    void investigation.run(diagnosis.query, true, diagnosis.target);
  });

  useEffect(() => {
    if (!saved.loading && saved.diagnosisChatId === saved.detail?.id && saved.diagnosisChatId)
      submitInitial(saved.diagnosisChatId);
  }, [saved.loading, saved.diagnosisChatId, saved.detail?.id]);

  /** Create and select a chat before its mounted owner submits the initial turn. */
  async function createChat(query: string, target: ContainerTarget) {
    creating.current = true;
    try {
      await saved.create(host, { query, target });
      await refreshHistory();
    } finally {
      creating.current = false;
    }
  }

  /** Resolve the clicked action without treating a facts selection as a diagnosis. */
  function diagnose(container: Container, inCurrentChat = false) {
    if (investigation.running || blocked || saved.loading || creating.current) return;
    const target = { kind: 'container', id: container.id, name: container.name } as const;
    const query = t('Investigate {name} ({id}). What happened, and what evidence supports it?', target);
    const startsNew = separate && !inCurrentChat;
    if (investigation.demoChats) startDemo(container, query, target, startsNew);
    else if (startsNew || !saved.detail) void createChat(query, target);
    else {
      openInvestigation();
      void investigation.run(query, true, target);
    }
  }

  return { diagnose, separate };
}
