# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Dates record merges into `master`. Version links show the corresponding changes.

## [0.8.0]

### Added

- SQLite archive storage saves owned investigations, revisioned drafts and preferences, and paginated turn snapshots.
  Explicit deletion preserves submission receipts and action protection. Runtime wiring remains in memory until the
  recovery services are integrated.
- Packaged forward migrations, exclusive process ownership, and stopped-server status and byte-preserving backup
  support establish local state storage. Backups reject source-file and source-sidecar destinations.
  The backend image prepares `/var/lib/docksight` for a durable directory mount.
- Durable action claims, dispatch markers, outcomes, and audit retain idempotency and exact-target uncertainty guards
  across restart. Cancelled callers retain an owned execution handoff.
- Offline state commands inspect, back up, migrate, and explicitly reconcile blocked targets under the backend lock.
  Reconciliation requires a fresh Docker observation and operator acknowledgement, preserves the unknown outcome,
  and invalidates old preparations without resending Docker commands.

### Fixed

- Creating a saved investigation enforces both byte quotas before saving its initial workspace and model context.
  Rejected creation preserves existing archives and actor preferences.
- A dispatch-marker commit that settles after its action deadline cannot send a late Docker command.

### Changed

- Keep temporary agent plans and review artifacts out of version control.
- Architecture checks keep SQLAlchemy, Alembic, and file-locking libraries inside adapters.

## [0.7.0]

### Added

- `make update-deps` upgrades backend and frontend runtime and dev dependencies within declared version ranges.
- `DOCKSIGHT_API_TOKENS` defines named operators, each with its own bearer token. Diagnostic sessions and prepared
  actions belong to the operator whose token created them, and audit records name that operator.
  `DOCKSIGHT_API_TOKEN` keeps working as the `operator` identity.

### Changed

- Shorter README, contributor guide, and technical references, with shared Markdown style rules.
- Action-store regression coverage protects owner isolation, retention, concurrent claims, cancellation, and
  indeterminate target blocks.
- Backend failures carry transport-independent categories. The HTTP adapter translates them into the existing
  response statuses without changing public error codes, messages, or diagnostic stream events.
- Architecture checks enforce independent inbound and outbound adapters, with concrete wiring confined to bootstrap.

### Fixed

- Dependency updates keep pytest compatible with the unused-fixture check.
- Browser checks wait for selection menus to finish rendering before reading their option target, avoiding
  timing-dependent failures immediately after opening a menu.

### Security

- Frontend tooling uses minimatch `11.0.1` or newer within `11.x` to fix CVE-2026-118764.
- The compatible provider no longer falls back to `OPENAI_API_KEY` or `DOCKSIGHT_OPENAI_API_KEY`, so an OpenAI key is
  never sent to a third-party or local endpoint. Use `DOCKSIGHT_MODEL_API_KEY` or `DOCKSIGHT_COMPATIBLE_API_KEY`.

## [0.6.0] - 2026-11-01

### Added

- Apache-2.0 license for the public repository and third-party notices in frontend builds.
- Docker healthcheck status appears separately from process state in container facts, diagnostic cards, inventory,
  and Compose members. Running unhealthy containers receive bounded diagnostic logs even without restarts.
  Missing health observations remain unknown. Probe commands and output are not exposed.
- Local Docker/model regression scenarios cover clean shutdowns, OOM, unexplained exits, failing healthchecks, and
  dependency follow-ups. Checks flag selected contradictions in explanations and recommendations, including unsupported
  claims that failures are unrelated. Other claims still need review.

### Changed

- Consolidated setup guides for host scope, evidence limits, providers, and connection errors, with current English Demo
  screenshots and diagnostic diagrams. README now covers diagnosis and confirmed actions, with CI and license badges.
  Release links point to merged commits. Contributor rules omit a stale version.
- Selection menus share custom styling, keyboard navigation, typeahead, and explicit selected or disabled states.
  Optional diagnostic-scope guidance appears beside a help button, available by hover, focus, or tap.
- Container card headers show process state only, with healthchecks in separate facts. Stopped containers identify the
  last reported check. Exited states are neutral and nonzero exit codes are highlighted.
- General incident questions return a bounded host overview across projects and ungrouped containers, with observed
  state, log coverage, collection limits, and optional focused investigations. Named ambiguity still requires a target
  choice. Additional log reads retain their evidence, and unavailable actions preserve collected observations.
  Updated diagnostic diagrams and documentation. Live regressions use mixed hosts and production log limits.

### Fixed

- Docker log deadline regressions send valid multiplexed frames during slow delivery, avoiding platform-dependent
  scan-limit failures in the timeout scenario.
- Healthy Compose-group diagnoses offer model cards only when their required data was collected. Group-only evidence
  supports group cards without unsupported individual-container cards. Final generation and repair share this
  restriction. No-card replies preserve empty public card lists through provider schema conversion.
- Host model projections limit repeated member detail. Final generation omits unvalidated prose drafts across scopes
  and recaps bounded latest lifecycle facts. Causal guidance separates clean shutdowns and unknown stop reasons from
  old errors. Model explanations still require review. Schema guidance places unresolved causes in unknowns.
  Repeated reads reuse current-turn evidence references. Redundant tool batches end exploration.
  Follow-ups label earlier questions and summaries as historical context and collect fresh facts.
  Ollama context-window exhaustion is distinguished from the response token limit, with localized guidance.
- Docker log tails retain transport timeouts and abort at a fixed deadline. Stalled or slowly delivered responses release
  worker capacity and cannot return partial logs as a successful read or prevent backend shutdown.

## [0.5.0] - 2026-10-31

### Fixed

- The Docker diagnosis/restart regression uses precollected container and log evidence and reports stream failures
  directly instead of failing with a missing-answer lookup.
- Provider/model selection initializes on Python 3.12 and 3.13 by deferring type-only settings annotations.
  Backend CI uses Node.js 24 actions and a fixed Ubuntu image. A compatibility failure leaves the other version running.
- Language selection fits its option labels without clipping.
- Dialogs close on an outside click while preserving drafts and prepared actions. Clicks inside and text selection
  remain within the dialog without dismissing it.
- Model generation distinguishes missing or inaccessible models from unsupported requests, with guidance
  to check the model name and API-key access. Provider response bodies remain private.
- Bounded Docker logs and diagnostic byte budgets retain the latest output. Viewers show the retained UTC date range and
  order. Oversized scans return an error.
- Final and repair schemas restrict evidence references to the current turn.
  A noisy SQL-log follow-up covers exact-container evidence, card content, and response language.
- Explicit container references preserve container scope when a Compose project has the same name,
  allowing dependency follow-ups to continue the existing conversation with fresh observations. Server tool scope keeps
  earlier group context from adding unrelated container cards to the new answer. Exact-target status and bounded logs are
  collected before model exploration. The server fills missing cards from those facts and retains status when logs fail.
- Untyped container/project name collisions ask which resource to investigate. The choice retains the question and
  conversation. Container reads use a freshly validated full Docker ID.
- Diagnostics and New investigation open an empty conversation, clear the draft, and focus the question input.
- Bare incident questions ask which observed Compose project or Swarm stack to diagnose when several are available,
  before collecting unrelated container logs. Named-group questions retain automatic scope resolution.
- Choosing a clarification scope continues the original question in one history entry. The selected group stays visible
  while the diagnosis runs. Unrelated answers and the next question's draft are preserved.
- Log-only answers keep the container name captured by Docker in panel headings and observation sources, even when the
  model omits the status card or its snapshot evidence.

### Added

- Header provider/model selection with searchable catalogs, server-managed credentials, and temporary per-tab choices.
  Catalogs refresh on demand with bounded caching and retain previous choices on failure. Switching preserves the
  investigation and prepared actions. Requests without a selection use the configured default model.
- A graceful-shutdown live scenario checks tail retention and detects unsupported attribution of process stops to SQL
  request errors. The causal check currently exposes a remaining local-model limitation.
- Gemini provider with a default Google endpoint, environment-based API keys, metadata checks, and preserved tool-call
  signatures for multi-step diagnostics. The status panel recognizes Gemini. Configuration uses 3.5 Flash-Lite because
  Google restricts 2.5 Flash-Lite generation for new users.
- An opt-in two-turn live regression checks group-to-dependency follow-ups in the same session against isolated Docker
  workloads and local models, including a container/project name collision and original evidence retention.
- An unscoped live scenario checks clarification before model calls and the selected project's complete failure cards.
  Language assertions distinguish verbatim Docker log text from model-authored explanations.

## [0.4.0] - 2026-10-30

### Added

- Opt-in end-to-end diagnostics using isolated Docker Compose workloads and configurable local Ollama models, including
  real browser flows, exact-resource evidence checks, and retained diagnostic artifacts.
- Optional root Make commands with English help for setup, development servers, checks, tests, and frontend builds.

### Changed

- Informal group names resolve against observed Compose/Swarm targets. Ambiguous requests offer a choice and continue
  the original question with the selected scope, preserving the follow-up draft.
- Each container's state, logs, and environment appear together with links to original observations. Action controls are
  more prominent. Log, trace, and observation disclosures animate while respecting reduced motion.
- Backend hooks and CI enforce 90% combined line and branch coverage, with missing-line output and optional HTML reports.
  Live Docker/model checks are selected by integration risk and remain opt-in.
- Numeric release versions stay aligned across backend metadata and the lockfile. Release notes use dated categories
  and summarize related outcomes across commits.

### Fixed

- Identical model card proposals no longer produce duplicate cards or prepare duplicate action controls.
- Ollama structured responses use schema descriptions. Validation rejects placeholder or reference-only causes.
  Repair instructions preserve separate container cards and action constraints.

## [0.3.0] - 2026-10-29

### Added

- Compose-project and Swarm-stack diagnostics with participant states, service replica counts, and explicit coverage gaps.
  Failure logs cover up to four local problem containers. Remote Swarm-node logs and group-wide mutations are unsupported.
- Optional group selection and resource-grouped evidence sources with observation times and direct links from cards.

### Changed

- Setup, configuration, examples, and contributor documentation are consolidated around refreshed English demo screenshots.
- Local hooks reject commits and direct pushes to `master`. Contribution rules require ongoing release notes.

### Fixed

- Free-form questions resolve known group names and unambiguous typos before model exploration. Collected problem
  containers retain factual cards even when the model omits them.
- Evidence IDs cannot be used as Docker resource IDs. Explanations distinguish immediate failures from unresolved causes
  and follow the question's language.
- Returning through the logo preserves the active diagnosis. The question shortcut appears only when its input is offscreen.

## [0.2.0] - 2026-10-28

### Added

- Responsive React workspace with Docker inventory, evidence-linked investigations, and confirmed actions.
- Visibly separate demo scenarios for trying investigations and confirmed actions without Docker or a model.
- Read-only container overview for state, metrics, logs, and allowlisted environment values, with automatic inventory
  refresh that preserves earlier diagnostic observations.
- Authenticated streaming diagnoses with tool progress, cancellation, connection-error recovery, and linked evidence cards.
- Independent API, Docker, provider, and model availability indicators, including checks that do not generate model answers.
- Temporary per-turn traces with durations, available token usage, sanitized model responses, tool calls,
  and validation errors.

### Changed

- Suggested actions are distinct from other permitted operations. Confirmation identifies the exact prepared target, and
  lost execution responses are recovered by reading the action without automatically repeating a Docker mutation.

### Fixed

- Mixed-container model proposals resolve to the correct resources. Inventory refresh, host navigation, and composer
  layouts preserve usable controls across desktop and mobile views.

### Security

- API credentials remain in browser memory. Logs, environment values, and API/model text render as text.

## [0.1.0] - 2026-10-27

### Added

- Authenticated REST API and SSE diagnostics with typed UI cards and evidence references, plus public health and API docs.
- Docker inventory, state, logs, metrics, allowlisted environment values, and stack summaries over local, verified SSH,
  or mTLS connections.
- Configurable Ollama, OpenAI, Anthropic, and OpenAI-compatible model adapters.
- Host-scoped diagnostic sessions with bounded tool work, concurrency limits, and turn deadlines. Session and action state
  is held in memory, resets on restart, and requires a single backend worker.
- Expiring restart/stop proposals with explicit confirmation, target revalidation, idempotency, and execution audit events.
- Non-root Python 3.14 backend image, reproducible Compose failures, and an HTTP demo client.
- Hexagonal backend boundaries, strict quality checks, API/architecture guides, and editable Draw.io diagrams.

### Security

- Models receive read-only tools. Tool arguments, resource scope, and evidence references are validated. Inspect fields
  and environment values are allowlisted, and logs are sanitized before model requests or application logging.
- Prepared actions are bound to the caller and exact target. Unknown mutation outcomes block conflicting actions.
  Runtime mutations are never retried automatically.

[0.8.0]: https://github.com/Neizvestnyj/DockSight/compare/feature/security-fixes...feature/persistent-investigations
[0.7.0]: https://github.com/Neizvestnyj/DockSight/compare/3c69d1ac9d2316bf84582ec230c5290779967cf7...feature/security-fixes
[0.6.0]: https://github.com/Neizvestnyj/DockSight/compare/093f3c7e0a90251cfe73aba503576bd2280cca12...3c69d1ac9d2316bf84582ec230c5290779967cf7
[0.5.0]: https://github.com/Neizvestnyj/DockSight/compare/83c8fa477bfc63aa4c0d4f21f33bf676c0649e41...093f3c7e0a90251cfe73aba503576bd2280cca12
[0.4.0]: https://github.com/Neizvestnyj/DockSight/compare/5ac9a9ed6db7ec57b6ae3848365fb24adfc25b32...83c8fa477bfc63aa4c0d4f21f33bf676c0649e41
[0.3.0]: https://github.com/Neizvestnyj/DockSight/compare/bced0aeab5c9287e4dd4916e9b6631b5a017cdf9...5ac9a9ed6db7ec57b6ae3848365fb24adfc25b32
[0.2.0]: https://github.com/Neizvestnyj/DockSight/compare/bc073208b7a7f7ec33f227ffa70c3fb895fd3680...bced0aeab5c9287e4dd4916e9b6631b5a017cdf9
[0.1.0]: https://github.com/Neizvestnyj/DockSight/commit/bc073208b7a7f7ec33f227ffa70c3fb895fd3680
