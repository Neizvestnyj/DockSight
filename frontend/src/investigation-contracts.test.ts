import { describe, expect, it } from 'vitest';
import { actorWorkspaceSchema, investigationWorkspaceSchema, startTurnSchema } from './investigation-contracts';

describe('persisted workspace contracts', () => {
  it('rejects fractional, unsafe, boolean and unknown revisions', () => {
    for (const revision of [true, 1.5, -1, Number.MAX_SAFE_INTEGER + 1])
      expect(
        actorWorkspaceSchema.safeParse({ revision, last_investigation_id: null, host: null, model: null }).success,
      ).toBe(false);
    expect(
      investigationWorkspaceSchema.safeParse({
        revision: 0,
        draft: '',
        target: null,
        selected_container: null,
        view: 'diagnostics',
        token: 'secret',
      }).success,
    ).toBe(false);
  });

  it('forbids replacement text on clarification and requires parent revision', () => {
    const input = {
      kind: 'clarification',
      submission_id: crypto.randomUUID(),
      expected_revision: 0,
      clarification_of: crypto.randomUUID(),
      expected_parent_revision: 3,
      target: { kind: 'compose', name: 'shop' },
      model: null,
    };
    expect(startTurnSchema.safeParse(input).success).toBe(true);
    expect(startTurnSchema.safeParse({ ...input, query: 'replacement' }).success).toBe(false);
    expect(startTurnSchema.safeParse({ ...input, expected_parent_revision: undefined }).success).toBe(false);
  });
});
