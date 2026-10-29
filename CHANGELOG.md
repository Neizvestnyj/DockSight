# Changelog

## v0.3.0

- Diagnose Compose projects and Swarm stacks with participant status, bounded failure logs, and explicit coverage gaps.
- Resolve group names from chat, including unambiguous typos, and retain cards for collected failing participants.
- Separate confirmed failure causes from unresolved details and match explanations to the question's language.
- Improve group selection and evidence navigation with resource grouping, framed sources, and clearer observation IDs.
- Return to diagnosis from the logo without clearing active work, and show the question shortcut only when its input
  is outside the viewport.
- Consolidate setup and contributor guides, require ongoing release notes, and block direct local commits and pushes
  to `master`.

## v0.2.0

- Add a responsive React workspace with English/Russian localization and isolated demo scenarios.
- Browse container state, logs, metrics, and environment values; refresh inventory and show dependency availability.
- Stream diagnoses with progress, cancellation, evidence links, and sanitized per-turn model/tool traces.
- Separate suggested actions from permitted operations, with exact-target confirmation and lost-response recovery.

## v0.1.0

- Introduce authenticated REST reads and SSE diagnoses with evidence-linked typed cards.
- Support local, verified SSH, and mTLS Docker connections and Ollama, OpenAI, Anthropic, and compatible models.
- Bound read-only model tools, sanitize logs, and validate evidence references.
- Prepare expiring restart/stop actions with confirmation, target revalidation, and idempotent execution.
- Package a Python backend image, reproducible Compose failures, and an HTTP demo client.

Sessions and action records are held in memory and reset on restart.
