# Directory Structure

```
.github/
  workflows/
    docs.yml (60 lines)
    publish.yml (32 lines)
    README.md (96 lines)
    style.yml (34 lines)
    test.yml (37 lines)
docs/
  api/
    rlm.md (460 lines)
  src/
    app/
      api/
        page.tsx (282 lines)
      backends/
        page.tsx (123 lines)
      environments/
        docker/
          page.tsx (92 lines)
        local/
          page.tsx (73 lines)
        modal/
          page.tsx (115 lines)
        page.tsx (165 lines)
      trajectories/
        page.tsx (125 lines)
      globals.css (75 lines)
      layout.tsx (29 lines)
      page.tsx (289 lines)
    components/
      Button.tsx (48 lines)
      CodeBlock.tsx (102 lines)
      Sidebar.tsx (118 lines)
      Table.tsx (33 lines)
      Tabs.tsx (43 lines)
    lib/
      utils.ts (6 lines)
  .gitignore (34 lines)
  getting-started.md (342 lines)
  next.config.js (9 lines)
  package.json (31 lines)
  postcss.config.js (6 lines)
  tailwind.config.ts (17 lines)
  tsconfig.json (20 lines)
examples/
  daytona_repl_example.py (112 lines)
  docker_repl_example.py (69 lines)
  e2b_repl_example.py (28 lines)
  lm_in_prime_repl.py (76 lines)
  lm_in_repl.py (70 lines)
  modal_repl_example.py (99 lines)
  prime_repl_example.py (30 lines)
  quickstart.py (27 lines)
prompts/
  rebuild_rlm_codebase_with_adk.md (235 lines)
rlm/
  clients/
    __init__.py (63 lines)
    anthropic.py (112 lines)
    azure_openai.py (142 lines)
    base_lm.py (33 lines)
    gemini.py (162 lines)
    litellm.py (105 lines)
    openai.py (129 lines)
    portkey.py (94 lines)
  core/
    __init__.py (0 lines)
    comms_utils.py (264 lines)
    lm_handler.py (225 lines)
    rlm.py (399 lines)
    types.py (265 lines)
  environments/
    __init__.py (42 lines)
    base_env.py (182 lines)
    constants.py (32 lines)
    daytona_repl.py (637 lines)
    docker_repl.py (347 lines)
    e2b_repl.py (506 lines)
    local_repl.py (404 lines)
    modal_repl.py (512 lines)
    prime_repl.py (598 lines)
  logger/
    __init__.py (4 lines)
    rlm_logger.py (63 lines)
    verbose.py (393 lines)
  utils/
    __init__.py (0 lines)
    parsing.py (169 lines)
    prompts.py (156 lines)
    rlm_utils.py (12 lines)
  __init__.py (3 lines)
tests/
  clients/
    portkey.py (24 lines)
    test_gemini.py (189 lines)
  repl/
    test_local_repl.py (23 lines)
  __init__.py (0 lines)
  mock_lm.py (27 lines)
  README.md (1 lines)
  test_imports.py (503 lines)
  test_local_repl_persistent.py (220 lines)
  test_local_repl.py (245 lines)
  test_multi_turn_integration.py (395 lines)
  test_parsing.py (366 lines)
  test_types.py (185 lines)
visualizer/
  public/
    file.svg (1 lines)
    globe.svg (1 lines)
    next.svg (1 lines)
    vercel.svg (1 lines)
    window.svg (1 lines)
  src/
    app/
      globals.css (254 lines)
      layout.tsx (45 lines)
      page.tsx (5 lines)
    components/
      ui/
        accordion.tsx (66 lines)
        badge.tsx (46 lines)
        button.tsx (62 lines)
        card.tsx (92 lines)
        collapsible.tsx (33 lines)
        dropdown-menu.tsx (257 lines)
        resizable.tsx (56 lines)
        scroll-area.tsx (58 lines)
        separator.tsx (28 lines)
        tabs.tsx (66 lines)
        tooltip.tsx (61 lines)
      AsciiGlobe.tsx (113 lines)
      CodeBlock.tsx (185 lines)
      CodeWithLineNumbers.tsx (40 lines)
      Dashboard.tsx (311 lines)
      ExecutionPanel.tsx (189 lines)
      FileUploader.tsx (114 lines)
      IterationTimeline.tsx (186 lines)
      LogViewer.tsx (196 lines)
      StatsCard.tsx (58 lines)
      SyntaxHighlight.tsx (183 lines)
      ThemeProvider.tsx (10 lines)
      ThemeToggle.tsx (150 lines)
      TrajectoryPanel.tsx (211 lines)
    lib/
      parse-logs.ts (180 lines)
      types.ts (71 lines)
      utils.ts (6 lines)
  .gitignore (41 lines)
  components.json (22 lines)
  eslint.config.mjs (18 lines)
  next.config.ts (7 lines)
  package.json (41 lines)
  postcss.config.mjs (7 lines)
  README.md (38 lines)
  tsconfig.json (34 lines)
.gitattributes (1 lines)
.gitignore (215 lines)
.pre-commit-config.yaml (25 lines)
.python-version (1 lines)
AGENTS.md (319 lines)
CONTRIBUTING.md (26 lines)
LICENSE (21 lines)
Makefile (58 lines)
MANIFEST.IN (8 lines)
pyproject.toml (83 lines)
README.md (159 lines)
```