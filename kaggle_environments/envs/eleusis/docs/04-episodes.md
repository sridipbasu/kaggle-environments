# Episodes

Completed LLM episodes, played on Vertex AI with `reasoning_effort: high`. Each replay is `env.toJSON()` with an `info` block shaped like a Kaggle episode replay (`Agents`, `TeamNames`, `EpisodeId`, `seed`).

| Episode | Penalty | Rule-maker | Scientist 1 | Scientist 2 | Secret rule (accept rate) | Rewards (RM / S1 / S2) | Replay |
| :---- | :---- | :---- | :---- | :---- | :---- | :---- | :---- |
| 001 | 2 | Flash | Flash: solved in 13 turns, 5 wrong | Flash: solved in 6 turns, 1 wrong | `card.color != prev.color and (card.rank % 2) != (prev.rank % 2)` (25%) | 7 / 7 / 22 | [json](episodes/eleusis-episode-001.json) |
| 002 | 2 | Flash | Flash-Lite: solved in 24 turns, 8 wrong | Flash: solved in 4 turns, 0 wrong | `card.color != prev.color and card.rank % 2 == prev.rank % 2` (25%) | 0 / 0 / 26 | [json](episodes/eleusis-episode-002.json) |

Flash = `gemini-2.5-flash`, Flash-Lite = `gemini-2.5-flash-lite`. Episode 002 is walked through turn by turn in [Example Game](03-example-game.md).

## What the episodes show so far

- **The harness is robust.** Every answer parsed on the first try in both episodes.
- **Exact-equivalence scoring works.** Correct guesses written as different code were accepted.
- **There is a clear model gap.** Given the same deal, Flash needed 4 turns and Flash-Lite 24.
- **Over-guessing is the main failure mode.** Models often guess before the evidence pins the rule down, and repeat hypotheses already marked wrong. A high penalty (5) separates this behaviour more sharply.

These are smoke tests, not ratings. Ratings need many episodes with models rotated through every seat (see [Evaluation](07-evaluation.md)).

## Loading a replay

```python
import json
from kaggle_environments import make

replay = json.load(open("eleusis-episode-002.json"))
env = make("eleusis", configuration=replay["configuration"], steps=replay["steps"], info=replay["info"])
print(env.render(mode="ansi"))
```
