# Changelog

## v0.4.0

- Let the agent resolve informal group names against observed Compose/Swarm targets and request a choice when ambiguous;
  continue the original question with the selected scope while preserving the follow-up draft.
- Suppress identical model card proposals before preparing actions, keeping repeated output from duplicating controls.
- Present each container's diagnostic state, logs, and environment together with links to original observations;
  keep snapshots and action confirmations intact.
- Animate log, trace, and observation-data disclosure with short transitions that respect reduced motion.
- Make permitted operations easier to find with accented action controls, and select live end-to-end checks by
  integration risk while retaining focused browser checks for interface changes.
- Ground Ollama structured replies in schema descriptions and reject placeholder or reference-only cause explanations;
  make the single repair explicit about separate container cards and action constraints.
- Enforce 90% combined backend line and branch coverage in local hooks and CI, with missing-line output and optional
  HTML reports; cover Docker log bounds, secret redaction, connection cleanup, and mutation failure handling.
- Add an opt-in live end-to-end suite for isolated Docker Compose workloads and configurable local Ollama model matrices,
  with exact-resource card checks, English/Russian narrative checks, retained diagnostic artifacts, and scoped cleanup.
- Exercise free-form group questions, spaced/Cyrillic names, ambiguous alternatives, and explicit Compose selection through
  the real browser, API, Docker, and model; exclude an independently failing peer project from target evidence.
- Assign the intended semantic version during branch development and keep backend package metadata aligned.
- Add optional root Make commands with English help for setup, development servers, checks, tests, and frontend builds.

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
