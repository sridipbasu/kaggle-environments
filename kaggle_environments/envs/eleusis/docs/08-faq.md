# Frequently Asked Questions

**Why are guesses code and not plain English?**
Code can be checked exactly against the secret rule on every card pair. An English guess would need an LLM judge to translate it, and a judge can mistranslate a correct guess. The scientist writes the code itself, so there is no translation step to blame.

**Is it safe to evaluate code written by a model?**
The code is never run as written. It must be a single expression built only from an allow-list of syntax, its arithmetic is rewritten to work only on bounded integers, and it runs with no Python built-ins. Imports, attribute tricks like `card.__class__`, lambdas, comprehensions, `**` and string-multiplication bombs are all rejected. The tests include these cases.

**Can't the rule-maker just write an impossible rule?**
The fairness check rejects rules that accept fewer than 20% or more than 60% of pairs, that make some card unplayable, or that create a dead end. The rule-maker also scores only what the second-best scientist scores, so an unsolvable rule earns it 0.

**Why does every scientist get the same deal?**
So that scientists in the same episode differ only by their decisions, as in duplicate bridge. That makes scientist-vs-scientist comparisons fair and lowers the number of episodes a rating needs.

**Why only `card` and `prev`? Classic Eleusis rules can depend on the whole history.**
With two cards, a rule is fully described by its 2,704-entry truth table, so equivalence is exact and instant. Rules over the whole mainline are a natural v2. They would need simulation-based equivalence instead.

**Can a model memorise rules from the internet?**
The rule-maker is a model that invents a new rule each episode; the built-in rules are only a fallback. A scientist could still favour common rule shapes, which is one reason to rotate models between the rule-maker and scientist seats.

**What happens if a model returns nonsense?**
The harness re-prompts once with the exact error, e.g. "'KC' is not a card in your hand". If the second answer is also invalid, the turn is lost, or the guess counts as wrong. The episode keeps going.

**How long does a game take, and what does it cost?**
With a reasoning model: 20–60 LLM calls and 20–45 minutes; games run longer when scientists keep guessing wrong. Gemini 2.5 Flash cost about $0.2–0.3 per completed game, and thinking tokens are about 90% of the output.

**How is this different from earlier Eleusis LLM benchmarks?**
Earlier work is single-player against a fixed rule library, and uses a second LLM to turn the guess into code. Here, the rule-maker seat is itself a model, the scientists write their own code, and the game is head-to-head, so it can feed a Game Arena leaderboard.
