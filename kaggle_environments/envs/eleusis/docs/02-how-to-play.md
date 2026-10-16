# How to Play

## Overview

A game has 3 to 5 seats. **Seat 0 is the rule-maker.** Every other seat is a **scientist**.

1. **Rule phase.** The rule-maker writes a secret rule. The engine checks it for fairness; a rejected rule is sent back with the reason. After 3 rejections a built-in rule is used and the rule-maker scores 0.
2. **Play phase.** Each scientist sits at its own table with the **same deal** (one shuffle, copied to every table) and the same secret rule. Scientists cannot see each other's tables. All scientists take one turn per step.
3. A scientist is finished when it guesses the rule correctly or uses all 30 turns. The game ends when every scientist is finished.

## Cards

Two 52-card decks are shuffled together. Every card has three fields:

| Field | Values |
| :---- | :---- |
| `rank` | 1–13 (A = 1, J = 11, Q = 12, K = 13) |
| `suit` | `'S'` (spades), `'H'` (hearts), `'D'` (diamonds), `'C'` (clubs) |
| `color` | `'red'` (H, D) or `'black'` (S, C) |

Cards are written rank then suit: `AS`, `10H`, `QD`, `7C`.

## The table

- One starting card is turned face up. It starts the **mainline**, the row of accepted cards.
- Each scientist holds **12 cards**. After every play it draws one, so the hand stays at 12.
- A played card is judged against the **last accepted card** (`prev`):
  - **Accepted:** it joins the mainline and becomes the new `prev`.
  - **Rejected:** it goes on a **sideline** under the card it failed to follow, and `prev` stays the same.

## Actions

Each turn a scientist does exactly one of these. Every action uses one turn.

| Action | Format | Effect |
| :---- | :---- | :---- |
| **PLAY** | `{"action": "play", "card": "QD"}` | The card must be in the hand. The engine says accepted or rejected. |
| **GUESS** | `{"action": "guess", "words": "Colors alternate", "code": "card.color != prev.color"}` | Correct ends the scientist's game. Wrong costs a penalty. The engine says only correct or wrong. It never shows a counterexample. |

The rule-maker submits once per rule attempt:

```json
{"words": "Colors alternate", "code": "card.color != prev.color"}
```

`words` is for humans and the replay. Only `code` is judged.

## Rule language

A rule is **one Python expression** that is true when `card` may be played after `prev`.

| Allowed | Example |
| :---- | :---- |
| Card fields | `card.rank`, `prev.suit`, `card.color` |
| Integer and string constants | `7`, `'H'`, `'red'` |
| Comparisons | `==  !=  <  <=  >  >=` |
| Membership in a tuple | `card.rank in (2, 3, 5, 7)` |
| Logic | `and`, `or`, `not` |
| Arithmetic on numbers | `+  -  *  //  %` |
| Conditional | `x if condition else y` |
| Absolute value | `abs(card.rank - prev.rank)` |

Nothing else is allowed: no other names, function calls, attributes, indexing, loops or lambdas.

Example: `card.rank % 2 == 1 if prev.color == 'red' else card.rank % 2 == 0` means "after a red card play an odd rank, after a black card an even rank".

**Safety.** Model output is never executed as written. The expression is parsed, every syntax node is checked against an allow-list, and arithmetic is rewritten so it only works on integers up to 10⁶. That blocks memory bombs like `'S' * 1000 * 1000 * 1000`. Expressions are limited to 500 characters and 200 syntax nodes, and run with no Python built-ins. A rule that raises an error on any card pair is rejected.

## Fairness check (rule-maker)

The engine evaluates the rule on all 52 × 52 = 2,704 ordered `(card, prev)` pairs of one deck. The rule is accepted only if:

1. it accepts **between 20% and 60%** of the pairs;
2. **every card is playable** after at least one card;
3. **there are no dead ends**: after every card, at least one card is playable.

Each rejected attempt is shown to the rule-maker with its reason, e.g. `accepts 100% of (card, prev) pairs; must be between 20% and 60%`.

## When is a guess correct?

A guess is correct if and only if its code gives the same answer as the secret rule on **all 2,704 pairs**. Wording and code style don't matter:

| Secret rule | Guess | Verdict |
| :---- | :---- | :---- |
| `card.color != prev.color` | `not (card.color == prev.color)` | Correct |
| `card.color != prev.color and card.rank % 2 == prev.rank % 2` | `card.color != prev.color and abs(card.rank - prev.rank) % 2 == 0` | Correct |
| `card.color != prev.color` | `card.suit != prev.suit` | Wrong (fails on, e.g., 2♥ after 3♦) |

## Scoring

| Seat | Score |
| :---- | :---- |
| Scientist, solved | `max(0, 30 − turns used − penalty × wrong guesses)`, counting the turn of the correct guess |
| Scientist, not solved in 30 turns | 0 |
| Rule-maker | The **second-highest** scientist score. With 2 scientists that is the lower score, so the rule-maker scores only if every scientist solves the rule. |
| Rule-maker, built-in rule used | 0 |

The wrong-guess penalty is 2 by default. Run it at 2 and at 5 to separate bold models from cautious ones (see [Evaluation](07-evaluation.md)).

## Bad answers and failures

| What happens | Result |
| :---- | :---- |
| Answer can't be parsed, or the card isn't in the hand | The harness re-prompts once with the exact error. If it fails again, the turn is lost. |
| Guess code doesn't compile | Re-prompted once. If it fails again, it counts as a wrong guess. |
| Rule-maker answer invalid | Re-prompted once. If it fails again, it counts as a rejected rule. |
| A model crashes or times out | The episode is voided: every seat gets `ERROR` and no result is recorded. |

## Configuration

| Key | Default | Meaning |
| :---- | :---- | :---- |
| `max_turns` | 30 | Turns per scientist |
| `hand_size` | 12 | Cards in hand |
| `num_decks` | 2 | Decks in the shoe |
| `wrong_guess_penalty` | 2 | Points per wrong guess |
| `rule_retries` | 3 | Rule attempts before the built-in fallback |
| `accept_rate_min` / `accept_rate_max` | 0.2 / 0.6 | Fairness band |
| `seed` | null | Shuffle seed |
