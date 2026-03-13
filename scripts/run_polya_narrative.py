#!/usr/bin/env python3
"""Trial run: Polya narrative loop for the unemployment assistant story.

---
name: polya-narrative-trial
description: >
  Runs the Polya Understand-Plan-Implement-Reflect loop to iteratively
  develop a rich product narrative for an AI unemployment assistant.
config:
  model: ${RLM_ADK_MODEL:-gemini-3.1-pro-preview}
  max_cycles: ${POLYA_MAX_CYCLES:-2}
  thinking_budget: 2048
instruction_router:
  depth_0: Narrative Coordinator - orchestrates Polya loop via skill import
  depth_1: Narrative Worker - executes individual phase tasks
  depth_2+: (empty - no additional routing)
---

Usage:
    .venv/bin/python scripts/run_polya_narrative.py

Environment:
    RLM_ADK_MODEL          Model identifier (default: gemini-3.1-pro-preview)
    POLYA_MAX_CYCLES        Max Polya cycles (default: 2)
    RLM_ADK_DEBUG           Enable debug logging (1/true/yes)
    RLM_ADK_SQLITE_TRACING  Enable sqlite tracing (1/true/yes)
"""

import asyncio
import logging
import os
import sys

# Ensure rlm_adk is importable from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Load API keys from rlm_adk/.env (where adk run expects them)
_pkg_env = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "rlm_adk", ".env",
)
load_dotenv(dotenv_path=_pkg_env, override=False)

from google.adk.artifacts import FileArtifactService
from google.adk.runners import Runner
from google.genai import types

from rlm_adk.agent import _default_session_service, create_rlm_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Instruction Router
# ---------------------------------------------------------------------------

def polya_narrative_router(depth: int, fanout_idx: int) -> str:
    """Route skill instructions by depth for the Polya narrative loop.

    Args:
        depth: Current recursion depth (0 = root reasoning agent).
        fanout_idx: Index within a batched dispatch.

    Returns:
        Skill instruction text injected into the dynamic instruction template.
    """
    if depth == 0:
        return (
            "You are the Narrative Coordinator for a Polya problem-solving loop.\n\n"
            "YOUR MISSION: Use the polya-narrative source-expandable REPL skill to\n"
            "iteratively develop a rich, compelling product narrative through cycles\n"
            "of Understand -> Plan -> Implement -> Reflect.\n\n"
            "INSTRUCTIONS:\n"
            "1. Import the skill: from rlm_repl_skills.polya_narrative import run_polya_narrative\n"
            "2. Call run_polya_narrative(story) where 'story' is the full seed\n"
            "   narrative from your prompt.\n"
            "3. The function dispatches child agents for each Polya phase and\n"
            "   returns a PolyaNarrativeResult with the refined narrative.\n"
            "4. After receiving the result, present the final refined narrative\n"
            "   and the reflection verdict using set_model_response.\n\n"
            "IMPORTANT: Pass the ENTIRE seed narrative text as the 'story' argument.\n"
            "The skill handles all four phases and cycle repetition internally."
        )
    elif depth == 1:
        return (
            "You are a Narrative Worker executing one phase of a Polya\n"
            "problem-solving cycle for developing a product narrative.\n\n"
            "Focus deeply on your assigned task. Write rich, specific, grounded\n"
            "content. Do not be generic or produce placeholder text. Engage with\n"
            "the emotional, technical, and human dimensions of the narrative.\n"
            "Your output will be composed with other workers' outputs to build\n"
            "a complete, compelling product vision."
        )
    return ""


# ---------------------------------------------------------------------------
# Seed Story
# ---------------------------------------------------------------------------

SEED_STORY = """\
## The Unemployment Assistant: A Story of Transition

Rawley Stanhope sat at his kitchen table, staring at his laptop screen. Three weeks \
since the layoff. The severance package email sat unopened in his inbox next to \
seventeen tabs of government benefit websites, each more confusing than the last.

"Apply for unemployment benefits within 14 days." He'd missed that window once \
already because the state portal crashed during peak hours. COBRA healthcare \
continuation -- $1,847 per month for the family plan. Food assistance -- five \
different programs with overlapping eligibility requirements and different \
application portals. Each one a separate bureaucratic maze designed in the 1990s \
and barely updated since.

But Rawley wasn't just any recently displaced developer. He'd spent the last \
decade building systems that made complex processes simple. And now, sitting at \
that kitchen table with his coffee going cold, he had an idea.

What if there was an AI assistant -- not the kind that writes your emails or \
generates code, but the kind that actually *cares* about what you're going \
through? One that understands that losing your job isn't just a financial event \
-- it's an identity crisis. One that knows that the hardest part isn't the \
paperwork; it's the morning when you wake up and don't know who you are anymore.

The assistant would be called something simple. Something that says "I'm here \
to help" without the corporate polish. Something like... the Unemployment Assistant.

It would automate the nightmare:
- Filing for unemployment benefits across all 50 states (each with different \
  rules, different portals, different deadlines)
- Navigating COBRA and ACA marketplace options for temporary healthcare
- Applying for SNAP (food stamps), WIC, and local food bank programs
- Finding and applying to rental assistance and utility assistance programs
- Connecting users with free mental health resources and career counseling
- Managing the weekly certification requirements that keep benefits flowing
- Tracking appeal deadlines and filing appeals when claims are denied
- Finding local community resources: churches, nonprofits, mutual aid networks

But more than that -- and this is what makes it different -- it would also be \
a companion for the transition. Because Rawley learned something in those dark \
weeks at his kitchen table: your job was never supposed to be your identity. \
The layoff didn't take away who he was. It revealed that he'd been building his \
life on the wrong foundation.

The real foundation was always there: his family eating dinner together on a \
Tuesday because nobody had a late meeting. His neighbor who brought over soup \
without being asked. The church small group that showed up, literally showed up, \
at his door. The morning walks with his dog that he'd been too busy to take for \
years.

The Unemployment Assistant wouldn't just automate benefits applications. It would \
gently, consistently, encouragingly help people discover what Rawley discovered: \
that the transition from "I am what I do" to "I am who I love and who loves me" \
is the most important journey of a lifetime. And it often starts with a layoff.

---

The vision is to build an AI-powered product that:
1. Eliminates the bureaucratic friction of applying for government benefits
2. Provides personalized, state-specific guidance through every step
3. Offers emotional support and reframing during career transitions
4. Connects displaced professionals with community, relationships, and faith
5. Operates on a freemium model -- core benefits automation is free, premium \
   features (career coaching integration, financial planning) are subscription-based
6. Partners with churches, nonprofits, and community organizations to extend reach
"""


# ---------------------------------------------------------------------------
# Trial Runner
# ---------------------------------------------------------------------------

async def main():
    """Run the Polya narrative trial."""
    # Configure logging
    log_level = logging.DEBUG if os.getenv("RLM_ADK_DEBUG") else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    model = os.getenv("RLM_ADK_MODEL", "gemini-3.1-pro-preview")
    max_cycles = int(os.getenv("POLYA_MAX_CYCLES", "2"))

    print(f"[trial] Model: {model}")
    print(f"[trial] Max cycles: {max_cycles}")
    print(f"[trial] Seed story length: {len(SEED_STORY)} chars")

    # Build the app with instruction router
    rlm_app = create_rlm_app(
        model=model,
        root_prompt=SEED_STORY,
        instruction_router=polya_narrative_router,
        thinking_budget=2048,
    )

    # Build runner with services
    from pathlib import Path
    pkg_dir = Path(__file__).resolve().parents[1] / "rlm_adk"
    adk_dir = pkg_dir / ".adk"
    adk_dir.mkdir(parents=True, exist_ok=True)

    runner = Runner(
        app=rlm_app,
        session_service=_default_session_service(),
        artifact_service=FileArtifactService(root_dir=str(adk_dir / "artifacts")),
    )

    session = await runner.session_service.create_session(
        app_name="rlm_adk",
        user_id="polya_trial",
    )

    print(f"[trial] Session: {session.id}")
    print("=" * 70)
    print("[trial] Starting Polya narrative loop...")
    print("=" * 70)

    # The orchestrator yields root_prompt as initial user content.
    # We send a minimal user message to start the runner.
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(
            text=(
                "Develop this seed story into a rich, compelling product narrative "
                "using the Polya problem-solving loop. Import and call the "
                "run_polya_narrative skill with the full story provided in your "
                "system context."
            )
        )],
    )

    final_text = ""
    event_count = 0

    async for event in runner.run_async(
        user_id="polya_trial",
        session_id=session.id,
        new_message=content,
    ):
        event_count += 1

        # Print content events
        if event.content and event.content.parts:
            for part in event.content.parts:
                text = getattr(part, "text", None)
                if text:
                    final_text = text
                    preview = text[:300].replace("\n", " ")
                    print(f"\n[event #{event_count}] {event.author}: {preview}...")

        # Print state delta keys (not values, for brevity)
        if event.actions and event.actions.state_delta:
            keys = list(event.actions.state_delta.keys())
            print(f"[state #{event_count}] {keys}")

    print("\n" + "=" * 70)
    print("[trial] RUN COMPLETE")
    print(f"[trial] Total events: {event_count}")
    if final_text:
        print(f"[trial] Final answer length: {len(final_text)} chars")
        print("[trial] Final answer preview:")
        print("-" * 70)
        print(final_text[:2000])
        if len(final_text) > 2000:
            print(f"\n... ({len(final_text) - 2000} more chars)")
        print("-" * 70)


if __name__ == "__main__":
    asyncio.run(main())
