# Frontend verification

## Scope

Verified locally on 2026-10-27 with Node.js 24 and installed Chrome. Browser tests use mock HTTP/SSE responses and
the labeled Demo transport. No live Docker mutation, remote host, or model-provider call was made.

The selected app style is Framed sheet, seed `196156103`, without redraws. Its face is the cold grey frame, self-hosted
IBM Plex fonts, and the container sight mark. Its signature is conclusion → evidence reference → observation → reviewed
server action. The screen asks: what happened to the container, what supports that conclusion, and what can happen next?

## Checks

| Check | Result |
| --- | --- |
| TypeScript, ESLint, Prettier | Passed |
| Production Vite build | Passed |
| Unit and component tests | 35 passed |
| Chrome browser tests | 48 scenarios passed across 1440, 768, and 390 px |
| Axe on workspace and action dialog | No violations in tested states |
| Design skill inspector | 0 FAIL, 0 WARN at all three widths |
| Existing pre-commit checks | Passed; backend suite: 111 passed, 11 opt-in tests skipped |

Browser coverage includes all widgets, source focus, 200 log lines, empty logs, unavailable metrics versus zero,
truncation, uncertain cause, failed and expired actions, indeterminate delivery, keyboard focus containment, Escape,
host changes, retained demo settings, manual retry, cancellation, HTTP-200 terminal errors, bearer authentication,
POST SSE, lost execution response recovery by GET, long identifiers, and hostile-looking text in logs and environment.
Unit checks also cover split UTF-8/CRLF SSE frames, heartbeats, early EOF, unsupported versions, session expiry,
late events after cancellation, running action reads, and retaining the execution key after checking prepared state.

Localization checks cover automatic browser-language resolution, explicit English/Russian selection, returning to
System, reload persistence, invalid/blocked storage, languagechange events, Russian plural forms, Cyrillic font loading,
and preserving operator questions, drafts, evidence, action IDs, and verbatim logs/env/API text. Local transport errors
are localized; identical text authored by the API stays verbatim. Russian workspace and confirmation dialogs were checked
at all three widths with no Axe violations or page overflow.

All six authored demo questions and explanations are localized. Fictional host labels, control descriptions, preserved
empty OOM/SIGKILL logs, and operator-entered English questions under Russian UI have browser regressions. Large-log
coverage uses a mocked API response rather than a demo switch that manufactures evidence. Empty logs use a compact
neutral message inside their card.

Inventory checks cover deferred refresh progress, visible acknowledgement, retained rows and drafts after failure,
and distinct receipt/observation times. Host selection checks cover keyboard activation, focus restoration, current-host
selection without state loss, a new session after changing hosts, long names, loading, errors, and empty discovery.
English and Russian host pickers and refresh feedback were reviewed at all three widths with no Axe violations.
Host discovery and successful retries keep the picker open through workspace remounts and restore focus on close.

## Final app critique

1. The operator's question and model explanation lead the reading order. Runtime values remain in separately labeled
   cards; evidence references open the matching observation with keyboard focus.
2. The sheet closes against both canvas edges. Removing the overlaid composer fixed card occlusion. Column content
   retains natural height rather than stretching short cards into empty panels.
3. Teal identifies selected evidence, amber expresses uncertainty/restarts, red signals exited/failed states, and green
   marks running/succeeded observations. The frame remains neutral. The mark and product name survive mobile collapse.
4. Demo stack counts and membership derive from the same inventory. The duplicated container state, exit code, OOM,
   and restart count originate from fixture snapshots. Inventory and evidence have separately named observation times.
5. Zero CPU is printed as 0.0%; missing metrics say Unavailable. Empty inventories, logs, references, and cards retain
   explanatory context. There are no invented trend lines or confidence percentages.
6. The stack strip uses the returned count ratio; logs keep timestamps and text. No legend or chart duplicates data.
7. Mobile folds host navigation into a modal, stacks contextual evidence, wraps long text, and keeps logs bounded.
   The composer is reachable through Ask DockSight and remains in document flow.

Visual assessment: 8/10. The layout prioritizes investigation and readable facts. Long answers and several widgets
require scrolling, especially on mobile; the source links and composer shortcut preserve direct access.
All six final inspector images were opened and reviewed. No inspector rules were waived. The linter's monospace
warning is limited to code/IDs and timestamped logs; its shadow warning is limited to floating dialogs.

## Review and limitations

Independent review reproduced two issues: demo controls diverged from retained transport state after a host change,
and mobile connection settings opened above an existing navigation modal with a duplicate title ID. Both were fixed
and covered by regressions. There are no deferred code-review findings.

Localization review found an English-only path for frontend-authored stream errors. Error provenance now distinguishes
local errors from server messages; unit and browser regressions verify both origins, including identical text.

Demo review found that scenario selection could bypass empty inventory and create container cards on an empty host.
Scenario selection and streamed demo answers now share the same empty-state boundary, with regression coverage.

Navigation review reproduced a picker closing during initial host discovery or a successful retry. Picker visibility
now belongs to the connection owner, with focus returning to the current breadcrumb after a host-scoped remount.

Frontend CI was not added: automatic approval review could not authorize the workflow-file change because its service
reported a usage limit. Existing CI configuration is unchanged. Local verification remains reproducible with the
commands in [frontend operation](frontend.md).

Screenshots: [desktop](screenshots/frontend-desktop.jpg), [tablet](screenshots/frontend-tablet.jpg),
[mobile](screenshots/frontend-mobile.jpg), and [indeterminate action](screenshots/frontend-action.png).
Russian UI: [desktop](screenshots/frontend-russian-desktop.png), [tablet](screenshots/frontend-russian-tablet.png),
[mobile](screenshots/frontend-russian-mobile.png), and [confirmation](screenshots/frontend-russian-action.png).
Demo clarification: [desktop](screenshots/frontend-demo-desktop.png), [tablet](screenshots/frontend-demo-tablet.png),
and [mobile](screenshots/frontend-demo-mobile.png).
Navigation: [host selection](screenshots/frontend-host-picker.png),
[mobile host selection](screenshots/frontend-host-picker-mobile.png),
and [refresh acknowledgement](screenshots/frontend-refresh.png).
