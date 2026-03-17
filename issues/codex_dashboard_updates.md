# Codex Dashboard Updates

## Purpose

This note documents the code changes made in the dashboard/skill-selection slice of this session.

The goal of the slice was:

- make prompt-visible skill selection a first-class runtime input
- surface that selection in the live dashboard
- add a replay launcher to the `/live` dashboard
- persist the selected skills into session state and traces so the live dashboard can display the actual per-run selection

This document focuses on:

- what files changed
- what classes/functions/constants were added or changed
- where they were added
- why each change was made

It does not attempt to document unrelated worktree churn.

## High-Level Behavior Change

Before this work:

- prompt-visible skills were appended more or less inline in the agent factory
- the live dashboard showed a hardcoded skill list
- the live dashboard could observe sessions but not launch replay runs

After this work:

- prompt-visible skill selection is centralized in a skill catalog
- `enabled_skills` can be threaded through the factory chain
- root runs persist `enabled_skills` into session state
- SQLite tracing captures `enabled_skills`
- the live dashboard reads `enabled_skills` from traced session state
- the live dashboard has a replay launch panel that can choose prompt-visible skills and start an in-process replay run

## Files Changed

### 1. New Skill Catalog

File: [rlm_adk/skills/catalog.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/catalog.py)

Why:

- create one source of truth for prompt-visible skills
- stop hardcoding prompt block assembly in `create_reasoning_agent()`
- provide reusable helpers for both runtime prompt construction and dashboard display

Added symbols:

- `PromptSkillRegistration` at [catalog.py#L24](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/catalog.py#L24)
  - new dataclass
  - stores a `Skill` plus the callable that builds its prompt instruction block
- `PROMPT_SKILL_REGISTRY` at [catalog.py#L40](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/catalog.py#L40)
  - new registry mapping skill name to prompt registration
- `DEFAULT_ENABLED_SKILL_NAMES` at [catalog.py#L55](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/catalog.py#L55)
  - default ordered tuple of prompt-visible skills
- `normalize_enabled_skill_names(...)` at [catalog.py#L58](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/catalog.py#L58)
  - validates user-supplied names
  - preserves catalog order
  - raises on unknown skills
- `build_enabled_skill_instruction_blocks(...)` at [catalog.py#L71](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/catalog.py#L71)
  - returns the prompt blocks for the selected skills
- `selected_skill_summaries(...)` at [catalog.py#L82](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/catalog.py#L82)
  - returns `(name, description)` tuples for UI display

### 2. Skill Exports

File: [rlm_adk/skills/__init__.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/__init__.py)

Why:

- make the new catalog helpers importable from `rlm_adk.skills`
- export the `polya-understand` skill object alongside the existing ones

Added exports:

- `DEFAULT_ENABLED_SKILL_NAMES`
- `PROMPT_SKILL_REGISTRY`
- `POLYA_UNDERSTAND_SKILL`
- `build_enabled_skill_instruction_blocks`
- `normalize_enabled_skill_names`
- `selected_skill_summaries`

### 3. New Session State Key

File: [rlm_adk/state.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py)

Why:

- persist the selected prompt-visible skills into session state
- make the selection available to tracing and dashboard loaders

Added constant:

- `ENABLED_SKILLS = "enabled_skills"` at [state.py#L34](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py#L34)

### 4. Agent Factory Changes

File: [rlm_adk/agent.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py)

Why:

- thread `enabled_skills` through the runtime factory chain
- centralize prompt block assembly through the new catalog

Changed functions:

- `create_reasoning_agent(...)` at [agent.py#L193](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L193)
  - new parameter: `enabled_skills` at [agent.py#L203](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L203)
  - changed prompt assembly at [agent.py#L249](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L249)
  - old behavior:
    - append skill blocks inline and explicitly
  - new behavior:
    - iterate over `build_enabled_skill_instruction_blocks(enabled_skills)`
  - why:
    - the parent prompt is now driven by a validated catalog rather than ad hoc imports

- `create_rlm_orchestrator(...)` at [agent.py#L279](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L279)
  - new parameter: `enabled_skills` at [agent.py#L291](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L291)
  - normalizes the selection at [agent.py#L294](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L294)
  - passes normalized skills to the reasoning agent at [agent.py#L301](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L301)
  - persists them onto the orchestrator model at [agent.py#L325](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L325)
  - why:
    - keep prompt construction and orchestrator state aligned

- `create_rlm_app(...)` at [agent.py#L459](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L459)
  - new parameter: `enabled_skills` at [agent.py#L473](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L473)
  - forwards it at [agent.py#L510](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L510)
  - why:
    - let programmatic app creation specify prompt-visible skills

- `create_rlm_runner(...)` at [agent.py#L522](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L522)
  - new parameter: `enabled_skills` at [agent.py#L538](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L538)
  - forwards it at [agent.py#L604](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py#L604)
  - why:
    - let dashboard-launched runs pass selected skills into the runtime

### 5. Orchestrator Changes

File: [rlm_adk/orchestrator.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py)

Why:

- persist the chosen skill selection into root-run session state
- register the `polya-understand` skill module as an expandable REPL skill

Changed model fields:

- `enabled_skills: tuple[str, ...] = ()` added at [orchestrator.py#L219](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L219)
  - why:
    - store the normalized skill selection on the orchestrator instance

Changed runtime behavior:

- side-effect import of `rlm_adk.skills.polya_understand` added at [orchestrator.py#L282](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L282)
  - why:
    - register the skill for source expansion in the REPL path

- initial state persistence of `enabled_skills` added at [orchestrator.py#L329](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py#L329)
  - behavior:
    - only root runs (`depth == 0`) persist `enabled_skills`
  - why:
    - child runs inherit behavior through prompt/routing, but the root session should carry the canonical prompt-visible selection

### 6. Replay Launch Service

File: [rlm_adk/dashboard/run_service.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/run_service.py)

Why:

- create a programmatic replay launcher usable from the NiceGUI live dashboard
- validate replay payloads
- create a persisted session before the run starts
- seed `enabled_skills` into initial session state

Added class:

- `ReplayLaunchHandle` at [run_service.py#L18](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/run_service.py#L18)
  - fields:
    - `runner`
    - `user_id`
    - `session_id`
    - `queries`
  - added method:
    - `run()` at [run_service.py#L27](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/run_service.py#L27)
    - why:
      - execute the replay queries against the created runner/session

Added functions:

- `_load_replay_file(...)` at [run_service.py#L41](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/run_service.py#L41)
  - validates:
    - file exists
    - payload is a dict
    - `state` is a dict
    - `queries` is a non-empty list of non-empty strings
  - why:
    - fail fast before trying to create a runner/session

- `prepare_replay_launch(...)` at [run_service.py#L68](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/run_service.py#L68)
  - resolves and normalizes skills
  - injects `enabled_skills` into `initial_state` at [run_service.py#L78](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/run_service.py#L78)
  - creates a runner at [run_service.py#L80](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/run_service.py#L80)
  - creates a persisted session at [run_service.py#L84](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/run_service.py#L84)
  - why:
    - decouple replay-launch preparation from the UI/controller layer

### 7. Live Dashboard State

File: [rlm_adk/dashboard/live_models.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_models.py)

Why:

- give the live dashboard controller/UI enough state to render and track replay launches

Changed class:

- `LiveDashboardState` at [live_models.py#L318](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_models.py#L318)

Added fields:

- `replay_path` at [live_models.py#L324](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_models.py#L324)
- `selected_skills` at [live_models.py#L325](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_models.py#L325)
- `launch_in_progress` at [live_models.py#L326](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_models.py#L326)
- `launch_error` at [live_models.py#L327](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_models.py#L327)
- `launched_session_id` at [live_models.py#L328](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_models.py#L328)

### 8. Live Dashboard Controller

File: [rlm_adk/dashboard/live_controller.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_controller.py)

Why:

- manage launch-form state and background replay execution from the `/live` page

Changed class:

- `LiveDashboardController` at [live_controller.py#L36](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_controller.py#L36)

Added controller state initialization:

- default selected skills seeded from `DEFAULT_ENABLED_SKILL_NAMES` at [live_controller.py#L42](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_controller.py#L42)
- `_launch_task` added at [live_controller.py#L43](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_controller.py#L43)

Added methods:

- `set_replay_path(...)` at [live_controller.py#L56](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_controller.py#L56)
  - why:
    - update UI state and clear prior launch errors

- `set_selected_skills(...)` at [live_controller.py#L60](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_controller.py#L60)
  - why:
    - normalize and store skill selection coming from the UI

- `launch_replay(...)` at [live_controller.py#L64](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_controller.py#L64)
  - responsibilities:
    - guard against duplicate launch
    - call `prepare_replay_launch(...)`
    - surface launch errors
    - mark launch state
    - insert/select the new session
    - start background execution
  - why:
    - own replay-launch orchestration in the controller layer

- `_run_launch(...)` at [live_controller.py#L86](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_controller.py#L86)
  - why:
    - run the prepared replay in the background and capture late failures

### 9. Live Dashboard UI

File: [rlm_adk/dashboard/live_app.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py)

Why:

- expose replay launch controls on the `/live` page
- display the real prompt-visible skill selection instead of a generic "registered skills" label

Changed existing UI:

- subtitle changed to `"Live view plus replay launch controls"` at [live_app.py#L149](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py#L149)
- `_launch_panel(...)` inserted into the header area at [live_app.py#L189](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py#L189)
- session metadata label changed from `"Registered Skills"` to `"Skills in Prompt"` at [live_app.py#L203](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py#L203)
- polling logic now refreshes while launch is in progress or when a launch error exists at [live_app.py#L262](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py#L262)

Added function:

- `_launch_panel(...)` at [live_app.py#L289](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py#L289)
  - renders:
    - replay JSON path input at [live_app.py#L308](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py#L308)
    - prompt-visible skills multiselect at [live_app.py#L314](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py#L314)
    - launch button at [live_app.py#L322](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py#L322)
    - selected-skill chips at [live_app.py#L329](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py#L329)
    - launched-session label at [live_app.py#L342](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py#L342)
    - launch-error label at [live_app.py#L346](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py#L346)
  - why:
    - provide a complete launch surface without leaving the live dashboard

### 10. Live Loader

File: [rlm_adk/dashboard/live_loader.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_loader.py)

Why:

- replace hardcoded skill metadata with per-run skill selection from traced state

Changed behavior:

- `session_summary(...)` now reads `enabled_skills` from session state events at [live_loader.py#L206](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_loader.py#L206)
- it uses `_registered_skills(enabled_skills)` at [live_loader.py#L221](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_loader.py#L221)

Added function:

- `_latest_session_value(...)` at [live_loader.py#L383](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_loader.py#L383)
  - why:
    - read typed session-state values from SQLite traces instead of flattening everything to text

Changed function:

- `_latest_session_text(...)` at [live_loader.py#L377](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_loader.py#L377)
  - now delegates to `_latest_session_value(...)`
  - why:
    - avoid duplicating the state-row parsing logic

- `_registered_skills(...)` at [live_loader.py#L399](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_loader.py#L399)
  - old behavior:
    - return a hardcoded list of two skills
  - new behavior:
    - map the traced selection through `selected_skill_summaries(...)`
    - fall back to defaults on invalid traced data
  - why:
    - display the actual run selection

### 11. SQLite Tracing

File: [rlm_adk/plugins/sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py)

Why:

- make `enabled_skills` visible to the live dashboard via `session_state_events`

Changed logic:

- `_categorize_key(...)` now treats `enabled_skills` as `request_meta` at [sqlite_tracing.py#L99](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L99)
- `_CURATED_EXACT` now includes `enabled_skills` at [sqlite_tracing.py#L123](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py#L123)

Why it matters:

- without these two changes, the loader could not later recover the per-run skill selection from traces

## Tests Added / Updated

### Runtime / Skill Selection

File: [tests_rlm_adk/test_phase2_child_factory.py](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_phase2_child_factory.py)

Added tests:

- `test_parent_reasoning_agent_can_limit_prompt_visible_skills` at [test_phase2_child_factory.py#L68](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_phase2_child_factory.py#L68)
  - verifies prompt filtering when only `polya-narrative` is enabled

- `test_create_rlm_orchestrator_persists_enabled_skills` at [test_phase2_child_factory.py#L78](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_phase2_child_factory.py#L78)
  - verifies normalized skills are stored on the orchestrator

### Live Loader

File: [tests_rlm_adk/test_live_dashboard_loader.py](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_live_dashboard_loader.py)

Changed/added coverage:

- the existing session-summary test now expects `polya-understand` to appear in the default skill list at [test_live_dashboard_loader.py#L456](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_live_dashboard_loader.py#L456)
- `test_live_loader_session_summary_prefers_enabled_skills_from_state` added at [test_live_dashboard_loader.py#L464](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_live_dashboard_loader.py#L464)
  - inserts a traced `enabled_skills` value into `session_state_events`
  - verifies the loader returns only that selected skill

### Replay Launch Service

File: [tests_rlm_adk/test_dashboard_run_service.py](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_dashboard_run_service.py)

Added tests:

- `test_prepare_replay_launch_persists_enabled_skills` at [test_dashboard_run_service.py#L10](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_dashboard_run_service.py#L10)
  - verifies session creation includes `enabled_skills`

- `test_prepare_replay_launch_rejects_invalid_payload` at [test_dashboard_run_service.py#L41](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_dashboard_run_service.py#L41)
  - verifies invalid replay payloads fail fast

## What Was Added vs What Was Only Changed

New files added:

- [rlm_adk/skills/catalog.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/catalog.py)
- [rlm_adk/dashboard/run_service.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/run_service.py)
- [tests_rlm_adk/test_dashboard_run_service.py](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_dashboard_run_service.py)

Existing files changed:

- [rlm_adk/skills/__init__.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/skills/__init__.py)
- [rlm_adk/state.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/state.py)
- [rlm_adk/agent.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/agent.py)
- [rlm_adk/orchestrator.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/orchestrator.py)
- [rlm_adk/dashboard/live_models.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_models.py)
- [rlm_adk/dashboard/live_controller.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_controller.py)
- [rlm_adk/dashboard/live_app.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_app.py)
- [rlm_adk/dashboard/live_loader.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/dashboard/live_loader.py)
- [rlm_adk/plugins/sqlite_tracing.py](/home/rawley-stanhope/dev/rlm-adk/rlm_adk/plugins/sqlite_tracing.py)
- [tests_rlm_adk/test_phase2_child_factory.py](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_phase2_child_factory.py)
- [tests_rlm_adk/test_live_dashboard_loader.py](/home/rawley-stanhope/dev/rlm-adk/tests_rlm_adk/test_live_dashboard_loader.py)

## Important Caveats

- `enabled_skills` currently controls prompt visibility, not hard runtime enforcement.
- the dashboard replay path is in-process via `create_rlm_runner(...)`, not the documented ADK CLI replay path
- the live loader treats empty values as missing, so an intentionally empty `enabled_skills` list would currently fall back rather than display an empty selection
