"""LLM harness for Eleusis.

Implements the ``GameHarness`` protocol:

- ``get_legal_moves`` -- always ``None``: rules and guesses are open-ended
  code, so both roles are free-form (``freeForm: true`` in the spec).
- ``generate_prompt`` -- dispatches on ``observation.role``
  (``"rule_maker"`` / ``"scientist"``).
- ``parse_response`` -- takes the LAST JSON object in the response and
  pre-validates it against the same checks the engine runs (code compiles
  and evaluates on every card pair; played card is in hand). An invalid
  answer is withheld so the rethink loop re-prompts with the exact error.
  ``raw_action`` is the attempted action as JSON: on the forfeit path the
  engine reads it back, so a guess whose code never compiled still counts
  as a wrong guess.

The fairness gate is NOT checked here: the engine runs it and reports the
reason on ``rule_attempts``, which is how the rule-maker learns about it.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from kaggle_environments.core_harness import ParseResult, extract_last_json_object
from kaggle_environments.envs.eleusis import rules

RULE_LANGUAGE = """\
Rule language: ONE Python expression that is true when `card` may be played after `prev`.
- card.rank, prev.rank: 1-13 (A=1, J=11, Q=12, K=13)
- card.suit, prev.suit: 'S', 'H', 'D', 'C'
- card.color, prev.color: 'red' (H, D) or 'black' (S, C)
Allowed: integer and string constants; == != < <= > >=; `in` / `not in` with a tuple such as (2, 3, 5); \
and, or, not; + - * // % on numbers; `x if condition else y`; abs(...).
Nothing else: no other names, functions, attributes, indexing, loops or lambdas. Use single quotes inside code.
Example of the syntax: abs(card.rank - prev.rank) <= 2 and card.suit != prev.suit"""

RULE_MAKER_PROMPT = """\
You are the RULE-MAKER in Eleusis, a game about discovering a hidden rule.

You write a secret rule deciding which card may be played after which. {num_scientists} scientists then try to \
discover it, each at its own table. Each turn a scientist either plays a card from its hand (your rule decides \
whether it is accepted after the last accepted card) or guesses your rule. A guess is correct only if its code \
gives the same answer as yours on every (card, prev) pair of a 52-card deck. Each scientist has {max_turns} turns.

Scoring:
- A scientist that solves your rule scores max(0, {max_turns} - turns used - {penalty} x wrong guesses); \
otherwise 0.
- You score the {rank_text} scientist score.
- After {retries} rejected rules, a random built-in rule is used instead and you score 0.

{rule_language}

Fairness check, run on all 52 x 52 = 2,704 ordered (card, prev) pairs. Your rule is rejected unless:
1. it accepts between {lo:.0%} and {hi:.0%} of the pairs;
2. every card can be played after at least one card;
3. after every card, at least one card can be played.

{attempts}
Think it through, then end your reply with one JSON object:
```json
{{"words": "<the rule in plain English>", "code": "<one expression>"}}
```
For example: {{"words": "Rank within 2 of the previous rank and a different suit", \
"code": "abs(card.rank - prev.rank) <= 2 and card.suit != prev.suit"}}"""

SCIENTIST_PROMPT = """\
You are a SCIENTIST in Eleusis, a game about discovering a hidden rule.

A secret rule decides whether a card may be played after the last accepted card. It looks only at those two \
cards: rank (A=1, 2-10, J=11, Q=12, K=13), suit (S, H, D, C) and color (H and D red; S and C black).

Each turn, do exactly one:
- PLAY a card from your hand. If the rule allows it after the last accepted card, it joins the mainline and \
becomes the new last accepted card; otherwise it is rejected and the last accepted card stays. Either way you \
draw a replacement.
- GUESS the rule as words plus code. It is correct only if your code gives the same answer as the secret rule on \
every (card, prev) pair of a 52-card deck; the wording is not judged. You are told only correct or wrong. A \
correct guess ends your game.

Scoring: every play and every guess uses one turn. If you solve the rule you score \
max(0, {max_turns} - turns used - {penalty} x wrong guesses), counting the turn of the correct guess. If you have \
not solved it after {max_turns} turns you score 0.

{rule_language}

Your table
Mainline (accepted cards, oldest first; [rejected: ...] lists cards refused right after that card):
{mainline}
Last accepted card (your next card is judged against it): {last}
Your hand: {hand}
Turns used: {turns_used} of {max_turns} ({turns_left} left){passes}
Wrong guesses so far ({penalty} points each): {wrong}

Think it through, then end your reply with one JSON object, either
```json
{{"action": "play", "card": "<a card from your hand>"}}
```
or
```json
{{"action": "guess", "words": "<the rule in plain English>", "code": "<one expression>"}}
```
For example: {{"action": "play", "card": "10H"}}"""

RETHINK_INVALID = """

Your previous answer was not accepted: {error}
Fix it and end your reply with one JSON object in the same format."""

RETHINK_UNPARSABLE = """

Your previous reply had no usable JSON answer. It ended with:
{previous_response}

End your reply with exactly one JSON object in the format given above."""


def get_legal_moves(observation: Mapping[str, Any]) -> dict[int, str] | None:
    return None


def _format_mainline(mainline: Sequence[Mapping[str, Any]]) -> str:
    parts = []
    for m in mainline:
        rejected = f" [rejected: {', '.join(m['rejected'])}]" if m["rejected"] else ""
        parts.append(m["card"] + rejected)
    return " -> ".join(parts) or "(none)"


def _format_wrong(wrong: Sequence[Mapping[str, Any]]) -> str:
    if not wrong:
        return "none"
    lines = []
    for g in wrong:
        note = f"  (did not compile: {g['error']})" if g.get("error") else ""
        lines.append(f"\n- {g['words'] or '(no words)'} | code: {g['code']}{note}")
    return "".join(lines)


def _rank_text(num_scientists: int) -> str:
    if num_scientists == 2:
        return "LOWER of the two (so you score only if both scientists solve it)"
    return "SECOND-HIGHEST"


def _rule_maker_prompt(obs: Mapping[str, Any]) -> str:
    attempts = obs.get("rule_attempts") or []
    retries = obs.get("rule_retries", 3)
    block = ""
    if attempts:
        rows = "".join(f"\n- {a['code']}  -> {a['error']}" for a in attempts)
        block = f"Your rejected rules so far ({retries - len(attempts)} attempts left):{rows}\n"
    return RULE_MAKER_PROMPT.format(
        num_scientists=obs.get("num_scientists", 2),
        max_turns=obs.get("max_turns", 30),
        penalty=obs.get("wrong_guess_penalty", 2),
        rank_text=_rank_text(obs.get("num_scientists", 2)),
        retries=retries,
        rule_language=RULE_LANGUAGE,
        lo=obs.get("accept_rate_min", 0.2),
        hi=obs.get("accept_rate_max", 0.6),
        attempts=block,
    )


def _scientist_prompt(obs: Mapping[str, Any]) -> str:
    mainline = obs.get("mainline") or []
    max_turns = obs.get("max_turns", 30)
    turns_used = obs.get("turns_used", 0)
    passes = sum(1 for e in obs.get("log") or [] if e.get("type") == "pass")
    return SCIENTIST_PROMPT.format(
        max_turns=max_turns,
        penalty=obs.get("wrong_guess_penalty", 2),
        rule_language=RULE_LANGUAGE,
        mainline=_format_mainline(mainline),
        last=mainline[-1]["card"] if mainline else "(none)",
        hand=" ".join(obs.get("hand") or []),
        turns_used=turns_used,
        turns_left=max_turns - turns_used,
        passes=f"; {passes} turns lost to invalid answers" if passes else "",
        wrong=_format_wrong(obs.get("wrong_guesses") or []),
    )


def _validate(action: Mapping[str, Any], obs: Mapping[str, Any]) -> str | None:
    """Return why ``action`` would be rejected, or None. Mirrors the engine."""
    if obs.get("role") == "rule_maker" or action.get("action") == "guess":
        try:
            rules.truth_table(action.get("code"))
        except rules.RuleError as e:
            return f"the code is invalid: {e}"
        return None
    if action.get("action") != "play":
        return f'"action" must be "play" or "guess", got {action.get("action")!r}'
    card = rules.parse_card(action.get("card"))
    if card is None or str(card) not in (obs.get("hand") or []):
        return f"{action.get('card')!r} is not a card in your hand ({' '.join(obs.get('hand') or [])})"
    return None


def generate_prompt(
    observation: Mapping[str, Any],
    move_history: list[str],  # noqa: ARG001 -- protocol arg; the full table is on the observation
    previous_response: str | None = None,
    previous_action: str | None = None,
) -> str:
    role = observation.get("role")
    if role == "rule_maker":
        prompt = _rule_maker_prompt(observation)
    elif role == "scientist":
        prompt = _scientist_prompt(observation)
    else:
        raise ValueError(f"eleusis harness: unknown role {role!r}")
    if previous_action is not None:
        # The verdict is deterministic, so re-derive it rather than thread it through the protocol.
        error = _validate(json.loads(previous_action), observation) or "unknown error"
        prompt += RETHINK_INVALID.format(error=error)
    elif previous_response is not None:
        prompt += RETHINK_UNPARSABLE.format(previous_response=previous_response[-500:])
    return prompt


def parse_response(
    response: str,
    legal_action_strings: Sequence[str] | None,
    *,
    observation: Mapping[str, Any] | None = None,
) -> ParseResult:
    obs = observation or {}
    role = obs.get("role")
    if role == "rule_maker":
        data = extract_last_json_object(response, required_keys=("code",))
        if data is None:
            return ParseResult(raw_action=None)
        action = {"words": str(data.get("words") or ""), "code": str(data["code"])}
    elif role == "scientist":
        data = extract_last_json_object(response, required_keys=("action",))
        if data is None:
            return ParseResult(raw_action=None)
        kind = str(data["action"]).strip().lower()
        if kind == "guess":
            action = {"action": "guess", "words": str(data.get("words") or ""), "code": str(data.get("code") or "")}
        else:
            card = rules.parse_card(data.get("card"))
            action = {"action": kind, "card": str(card) if card else str(data.get("card"))}
    else:
        return ParseResult(raw_action=None)
    raw = json.dumps(action)
    if _validate(action, obs):
        return ParseResult(raw_action=raw)
    return ParseResult(submission=action, raw_action=raw)
