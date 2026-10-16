# Eleusis

Inductive-reasoning card game for LLMs. One model invents a secret rule; the others run experiments to discover it.

## Seats and flow

| Seat | Role | Each step |
|---|---|---|
| 0 | Rule-maker | `{"words": ..., "code": ...}` until a rule passes the fairness gate |
| 1..N (N = 2-4) | Scientist | `{"action": "play", "card": "QD"}` or `{"action": "guess", "words": ..., "code": ...}` |

1. **Rule phase.** The rule-maker's code must compile (see *Rule language*) and pass the fairness gate over all
   2,704 `(card, prev)` pairs of one deck: accept rate in `[accept_rate_min, accept_rate_max]`, every card playable
   after some card, no dead ends. A rejected rule is logged with its reason on `rule_attempts`. After
   `rule_retries` rejections a random library rule (`rules.LIBRARY`) is used and the rule-maker scores 0.
2. **Play phase.** Scientists sit at separate tables with the same rule and the **same deal** (one shuffle copied to
   every table), and see only their own table. Each step every unfinished scientist takes one turn:
   - **play**: the card is judged against the last accepted card; accepted -> mainline, rejected -> sideline under
     that card. A replacement is drawn.
   - **guess**: correct iff the code's truth table equals the secret rule's on all 2,704 pairs. Wording is not judged.
     Only correct / wrong is revealed.

A scientist finishes on a correct guess or after `max_turns` turns.

## Scoring

- Scientist: `max(0, max_turns - turns_used - wrong_guess_penalty * wrong_guesses)` if solved, else 0. A guess
  uses a turn.
- Rule-maker: the second-highest scientist score (with 2 scientists, the lower one). 0 if a library rule was used.

## Rule language

One Python expression over `card` and `prev`, each with `.rank` (1-13), `.suit` (`'S' 'H' 'D' 'C'`), `.color`
(`'red'` / `'black'`). Allowed: int/str constants, comparisons, `in` / `not in` with tuples, `and or not`,
`+ - * // %` on ints, `x if c else y`, `abs()`.

Safety (`rules.compile_rule`): AST whitelist; attributes only `card/prev.rank|suit|color`; arithmetic rewritten to
a guarded helper (ints only, |value| <= 10^6, so string/tuple repetition bombs fail); <= 200 syntax nodes,
<= 500 chars; `__builtins__` emptied. A rule that raises on any pair is rejected.

## Failure handling (Game Arena)

| Event | Outcome |
|---|---|
| Agent crash / timeout | Episode voided: all seats `ERROR` (timed-out seat keeps `TIMEOUT`), rewards `None` |
| Scientist plays a card not in hand, or unparseable answer | Pass: turn used, no information |
| Guess whose code doesn't compile | Wrong guess |
| Rule-maker answer invalid | Failed rule attempt |
| Schema-level `INVALID` | Episode ends, all `DONE`, scores so far kept |

The harness pre-validates code and cards and re-prompts once with the exact error before the engine sees the action.

## Configuration

`max_turns=30`, `hand_size=12`, `num_decks=2`, `wrong_guess_penalty=2` (run 2 and 5), `rule_retries=3`,
`accept_rate_min=0.2`, `accept_rate_max=0.6`, `seed=null`.

## Agents

- `random`: library rule / random card, never guesses.
- `perfect`: library rule / filters library rules by the evidence, plays the most informative card, guesses when one
  candidate is left. Solves library rules in ~5 turns; a sanity ceiling, not a benchmark.

## Running

```bash
uv run pytest tests/envs/eleusis -q

# Live LLM game (1 rule-maker + 2 scientists, same model in every seat)
GEMINI_API_KEY=... uv run python -m kaggle_environments.envs.eleusis.test_llm_game --model gemini-2.5-flash

# Visualizer (replay at visualizer/default/replays/test-replay.json)
cd kaggle_environments/envs/eleusis/visualizer/default && pnpm dev-with-replay
```
