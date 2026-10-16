# Getting Started: Test Locally

## Install

Eleusis lives on a branch, not in a release yet:

```bash
git clone -b eleusis https://github.com/sridipbasu/kaggle-environments.git
cd kaggle-environments
uv sync            # or: pip install -e .
```

## Run a game

Pass agent functions, file paths, or built-in agent names. There are 3 to 5 seats, and seat 0 is the rule-maker:

```python
from kaggle_environments import make

env = make("eleusis", configuration={"seed": 7, "wrong_guess_penalty": 2}, debug=True)
env.run(["perfect", "perfect", "random"])   # rule-maker, scientist 1, scientist 2

for i, s in enumerate(env.steps[-1]):
    print(f"Seat {i} ({s.observation.role}): reward={s.reward}, status={s.status}")

print(env.render(mode="ansi"))
```

Built-in agents, which handle both roles:

| Name | Rule-maker | Scientist |
| :---- | :---- | :---- |
| `"random"` | Random built-in rule | Plays a random card, never guesses |
| `"perfect"` | Random built-in rule | Keeps the built-in rules that fit the evidence, plays the most informative card, guesses when one is left. Solves built-in rules in about 5 turns; a sanity ceiling, not a benchmark |

## Render a replay

The text render (`mode="ansi"`) works out of the box. The HTML replay viewer needs to be built once, because build output is not committed:

```bash
pnpm install
cd kaggle_environments/envs/eleusis/visualizer/default
pnpm build              # writes dist/index.html
```

Then, in a notebook or script:

```python
env.render(mode="ipython", width=1200, height=800)          # inside a notebook
open("game.html", "w").write(env.render(mode="html"))       # standalone file for any browser
```

To browse a saved replay with live reload instead:

```bash
pnpm dev-with-replay    # serves replays/test-replay.json
```

## Save a replay

```python
import json
with open("replay.json", "w") as f:
    json.dump(env.toJSON(), f)
```

## Play with real LLMs

The LLM harness is [`harness.py`](../harness.py), and both roles go through `kaggle_environments.core_harness`. The runner script puts the same model in every seat:

```bash
GEMINI_API_KEY=... uv run python -m kaggle_environments.envs.eleusis.test_llm_game --model gemini-2.5-flash
```

The replay is saved to `visualizer/default/replays/test-replay.json`.

Expect 20–60 LLM calls and 20–45 minutes per game with a reasoning model (more when scientists keep guessing wrong); Gemini 2.5 Flash cost about $0.2–0.3 per completed game. Keep the machine awake: a crashed or timed-out seat voids the episode.

## Run the tests

```bash
uv run pytest tests/envs/eleusis -q
```
