# Evaluation

## Rewards

Every episode produces one reward per seat (see [How to Play](02-how-to-play.md#scoring)):

- **Scientist:** `max(0, 30 − turns used − penalty × wrong guesses)` if solved, else 0.
- **Rule-maker:** the second-highest scientist score, or 0 if a built-in rule had to be used.

## From rewards to ratings (proposal)

Game Arena fits a Bradley–Terry model over pairwise outcomes. Eleusis produces pairwise outcomes like this:

- **Scientist vs scientist:** scientists in the same episode faced the same rule and the same deal, so the higher reward wins and equal rewards tie. This works like duplicate bridge: luck of the deal cancels out.
- **Rule-maker vs rule-maker:** compare rule-maker rewards across episodes with the same scientist line-up.

Report scientist and rule-maker ratings separately, plus a combined rating. Rotate every model through every seat so seat position doesn't bias the result.

## Two penalty settings

The wrong-guess penalty decides whether bold or cautious play wins. Run every pairing at:

| Setting | Penalty | What it rewards |
| :---- | :---- | :---- |
| Low | 2 | Guessing early, when a wrong guess is cheap |
| High | 5 | Gathering enough evidence before committing |

A model that ranks well at both settings is inducing rules, not gambling. A model whose rank changes a lot between them shows how well it adapts to the stakes.

## Extra metrics

Kept in the replay and cheap to report: accept rate of plays, turns to solve, wrong guesses before solving, repeated wrong guesses, turn of the first guess (boldness), and tokens and cost per turn.

## Episode validity

An episode with a crashed or timed-out seat is **voided**: every seat gets `ERROR` and all rewards are null, so infrastructure problems never count as losses. A bad but well-formed answer is **scored**: a lost turn, or a wrong guess for code that doesn't compile. That is a genuine capability signal.
