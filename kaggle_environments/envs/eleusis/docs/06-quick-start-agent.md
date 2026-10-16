# Quick Start Agent

A simple agent that handles both seats. As rule-maker it submits "colors alternate". As scientist it plays five cards to gather evidence, then tries a short list of hypotheses until one is correct:

```python
HYPOTHESES = [
    ("Colors alternate", "card.color != prev.color"),
    ("Same suit as the previous card", "card.suit == prev.suit"),
    ("Higher rank than the previous card", "card.rank > prev.rank"),
]


def agent(obs, config):
    if obs.role == "rule_maker":
        return {"words": "Colors alternate", "code": "card.color != prev.color"}

    # Scientist: play a few cards to gather evidence, then try each hypothesis in turn.
    if obs.turns_used < 5:
        return {"action": "play", "card": obs.hand[0]}
    tried = {g["code"] for g in obs.wrong_guesses}
    for words, code in HYPOTHESES:
        if code not in tried:
            return {"action": "guess", "words": words, "code": code}
    return {"action": "play", "card": obs.hand[0]}
```

Run it against itself and a random scientist:

```python
from kaggle_environments import make

env = make("eleusis", configuration={"seed": 1})
env.run([agent, agent, "random"])
print(env.render(mode="ansi"))
```

Output:

```
Phase: done
Secret rule (rule_maker, accepts 50%): Colors alternate  [card.color != prev.color]
Scientist 1: SOLVED, turns 6/30, wrong guesses 0, score 24
  AC -> JH -> 10S [x 10C JS] -> 7D
Scientist 2: out of turns, turns 30/30, wrong guesses 0, score 0
  AC [x 10C 10S AS] -> 8D -> QC -> ...
```

The random scientist never guesses, so it scores 0. The rule-maker therefore scores 0 too: it gets the lower scientist score.

## Useful observation fields

| Field | Seat | Meaning |
| :---- | :---- | :---- |
| `role` | all | `"rule_maker"` or `"scientist"` |
| `phase` | all | `"rule"`, `"play"` or `"done"` |
| `hand` | scientist | Cards in hand, e.g. `["10H", "QD"]` |
| `mainline` | scientist | Accepted cards in order, each `{"card", "rejected"}` |
| `wrong_guesses` | scientist | Earlier wrong guesses, each `{"words", "code", "error"}` |
| `log` | scientist | One entry per turn: play, guess or pass, with the result |
| `turns_used`, `max_turns` | scientist | Turn budget |
| `rule_attempts` | rule-maker | Rejected rules, each with the reason |
| `secret_rule` | rule-maker | The rule in play once accepted. Never shown to scientists |

The full schema is in [`eleusis.json`](../eleusis.json).
