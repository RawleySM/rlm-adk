"""Plan Review Loop configuration — constants and environment variable defaults.

Stdlib-only. All env vars use PRL_ prefix to avoid collision with existing
CODEX_* vars from scripts/codex_transfer/.
"""

import os
from pathlib import Path

# -- Paths -----------------------------------------------------------------

SCRIPT_DIR: Path = Path(__file__).parent

PLANS_DIR: Path = Path(os.environ.get("PRL_PLANS_DIR", str(Path.home() / ".claude" / "plans")))

CODEX_BIN: Path = Path(
    os.environ.get("CODEX_BIN", str(Path.home() / ".npm-global" / "bin" / "codex"))
)

REPO_DIR: Path = Path(os.environ.get("PRL_REPO_DIR", "/home/rawley-stanhope/dev/rlm-adk"))

LOG_DIR: Path = Path(os.environ.get("PRL_LOG_DIR", str(SCRIPT_DIR / "logs")))

TEMPLATE_PATH: Path = SCRIPT_DIR / "review_prompt_template.md"

# -- Orchestration ----------------------------------------------------------

MAX_ITERATIONS: int = int(os.environ.get("PRL_MAX_ITERATIONS", "5"))

CLAUDE_BUDGET_PER_TURN: float = float(os.environ.get("PRL_CLAUDE_BUDGET_PER_TURN", "2.0"))

CLAUDE_BUDGET_TOTAL: float = float(os.environ.get("PRL_CLAUDE_BUDGET_TOTAL", "10.0"))

CODEX_MODEL: str = os.environ.get("PRL_CODEX_MODEL", "o3")

CODEX_TIMEOUT: int = int(os.environ.get("PRL_CODEX_TIMEOUT", "300"))

# -- Verdict Parsing --------------------------------------------------------

VERDICT_APPROVED: str = "APPROVED"
VERDICT_NEEDS_REVISION: str = "NEEDS_REVISION"
VERDICT_PATTERN: str = r"^VERDICT:\s*(APPROVED|NEEDS_REVISION)\s*$"
