"""Run a full Eleusis game with LLM agents (1 rule-maker + 2 scientists) for local integration testing.

Usage:
    GEMINI_API_KEY=... uv run python -m kaggle_environments.envs.eleusis.test_llm_game --model gemini-2.5-flash

The replay goes to visualizer/default/replays/test-replay.json.
"""

from kaggle_environments.local_harness_runner import run_llm_game

if __name__ == "__main__":
    env = run_llm_game("eleusis", caller_file=__file__, num_agents=3)
    if env is not None:
        print(env.render(mode="ansi"))
