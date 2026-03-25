"""Architecture introspection skill for provider-fake e2e testing."""

from rlm_adk.skills.test_skill.skill import (
    TestSkillResult as TestSkillResult,
)
from rlm_adk.skills.test_skill.skill import (
    run_test_skill as run_test_skill,
)

SKILL_EXPORTS = ["run_test_skill", "TestSkillResult"]
