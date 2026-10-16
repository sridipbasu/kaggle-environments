"""Eleusis: inductive rule discovery, with an LLM rule-maker.

Seats: 0 = rule-maker, 1..N = scientists.

Phases:

* ``rule`` -- only the rule-maker is ACTIVE. Each step it submits
  ``{words, code}``. The code must compile under ``rules.compile_rule`` and
  pass ``rules.fairness``. A rejected rule is logged on the rule-maker's
  ``rule_attempts`` (with the reason) and it tries again. After
  ``rule_retries`` rejections a random library rule is used and the
  rule-maker's reward is pinned to 0.
* ``play`` -- every unfinished scientist is ACTIVE and takes one turn per
  step. Scientists sit at parallel, separate tables: the same secret rule
  and the same deal (one shuffle, copied to every table, so scientists
  differ only by their decisions -- the duplicate-bridge idea), and no
  visibility of other tables. A scientist finishes when it guesses
  correctly or runs out of turns.

Failure handling (Game Arena semantics):

* Crash / timeout (framework ERROR / TIMEOUT) voids the episode: every seat
  ERROR (a TIMEOUT seat keeps TIMEOUT), so core.py nulls all rewards.
* A bad but well-formed action is scored, not voided. Like word_art, the
  reward is a running score, so a flat +/-1 forfeit would throw away the
  game; instead a bad action costs what it would cost a human: an
  unplayable/unparseable action is a pass (turn used, no information), a
  guess whose code does not compile is a wrong guess, and a bad rule is a
  failed rule attempt. A schema-level INVALID ends the episode with every
  seat DONE and the scores reached so far.
"""

import json
import random
from os import path

from . import rules

dir_path = path.dirname(__file__)

RULE_MAKER = 0
_FRAMEWORK_FAILURE_STATUSES = ("ERROR", "TIMEOUT")


class _Hidden:
    """Authoritative hidden state, kept on ``env`` so it never reaches an
    observation (and so never the replay or an agent): the secret truth
    table and each table's draw pile."""

    def __init__(self, rng):
        self.rng = rng
        self.table = None
        self.piles = {}


def _unwrap(action):
    """Return the action dict, or None for a pass.

    Accepts a bare dict, a JSON string, or the core-harness envelope
    ``{"submission": ...}``. On the forfeit signal (``submission == -1``)
    core_harness keeps the last rejected attempt in ``actionString``; the
    harness writes that as JSON, so a guess whose code never compiled is
    still scored as a (wrong) guess rather than silently dropped.
    """
    if isinstance(action, dict) and "submission" in action:
        sub = action["submission"]
        action = action.get("actionString") if sub == -1 else sub
    if isinstance(action, str):
        try:
            action = json.loads(action)
        except ValueError:
            return None
    return action if isinstance(action, dict) else None


def _scientists(state):
    return range(1, len(state))


def _score(obs):
    if not obs.solved:
        return 0
    return max(0, obs.max_turns - obs.turns_used - obs.wrong_guess_penalty * len(obs.wrong_guesses))


def _rule_maker_reward(state):
    rule = state[RULE_MAKER].observation.secret_rule
    if not rule or rule["source"] != "rule_maker":
        return 0
    scores = sorted((state[i].observation.score for i in _scientists(state)), reverse=True)
    return scores[1]


# --- Phases ------------------------------------------------------------------


def _initialize(state, env):
    config = env.configuration
    seed = config.get("seed")
    env.eleusis = _Hidden(random.Random(seed))
    for i, s in enumerate(state):
        obs = s.observation
        obs.role = "rule_maker" if i == RULE_MAKER else "scientist"
        obs.phase = "rule"
        obs.max_turns = config.max_turns
        obs.wrong_guess_penalty = config.wrong_guess_penalty
        obs.rule_retries = config.rule_retries
        obs.accept_rate_min = config.accept_rate_min
        obs.accept_rate_max = config.accept_rate_max
        obs.num_scientists = len(state) - 1
        s.status = "ACTIVE" if i == RULE_MAKER else "INACTIVE"


def _check_rule(code, obs):
    """Return (table, None) if the rule is usable, else (None, reason)."""
    try:
        table = rules.truth_table(code)
    except rules.RuleError as e:
        return None, str(e)
    reason = rules.fairness(table, obs.accept_rate_min, obs.accept_rate_max)
    return (None, reason) if reason else (table, None)


def _rule_step(state, env):
    obs = state[RULE_MAKER].observation
    action = _unwrap(state[RULE_MAKER].action) or {}
    words = str(action.get("words") or "")
    code = action.get("code")
    table, error = _check_rule(code, obs) if code else (None, "no rule submitted")
    if table is not None:
        source = "rule_maker"
    else:
        obs.rule_attempts = list(obs.rule_attempts) + [{"words": words, "code": str(code or ""), "error": error}]
        if len(obs.rule_attempts) < obs.rule_retries:
            return
        _, words, code = env.eleusis.rng.choice(rules.LIBRARY)
        table, source = rules.truth_table(code), "library"
    obs.secret_rule = {"words": words, "code": code, "source": source, "accept_rate": rules.acceptance_rate(table)}
    env.eleusis.table = table
    _deal(state, env)


def _deal(state, env):
    config = env.configuration
    shoe = [str(c) for c in rules.DECK] * config.num_decks
    env.eleusis.rng.shuffle(shoe)
    start, hand, pile = shoe[0], shoe[1 : 1 + config.hand_size], shoe[1 + config.hand_size :]
    for i, s in enumerate(state):
        s.observation.phase = "play"
        if i == RULE_MAKER:
            s.status = "INACTIVE"
            continue
        s.observation.mainline = [{"card": start, "rejected": []}]
        s.observation.hand = list(hand)
        env.eleusis.piles[i] = list(pile)
        s.status = "ACTIVE"


def _play_turn(obs, action, table, pile):
    """Apply one scientist turn to its observation. Returns the log entry."""
    turn = obs.turns_used + 1
    kind = action.get("action") if action else None
    if kind == "play":
        card = rules.parse_card(action.get("card"))
        name = str(card) if card else None
        if name not in obs.hand:
            return {"turn": turn, "type": "pass", "reason": f"{action.get('card')!r} is not a card in your hand"}
        prev = obs.mainline[-1]["card"]
        accepted = rules.is_legal(table, card, rules.parse_card(prev))
        hand = list(obs.hand)
        hand.remove(name)
        if pile:
            hand.append(pile.pop(0))
        obs.hand = hand
        mainline = [dict(m, rejected=list(m["rejected"])) for m in obs.mainline]
        if accepted:
            mainline.append({"card": name, "rejected": []})
        else:
            mainline[-1]["rejected"].append(name)
        obs.mainline = mainline
        return {"turn": turn, "type": "play", "card": name, "prev": prev, "accepted": accepted}
    if kind == "guess":
        words, code = str(action.get("words") or ""), str(action.get("code") or "")
        try:
            correct, error = rules.truth_table(code) == table, None
        except rules.RuleError as e:
            correct, error = False, str(e)
        if correct:
            obs.solved = True
        else:
            obs.wrong_guesses = list(obs.wrong_guesses) + [{"words": words, "code": code, "error": error}]
        return {"turn": turn, "type": "guess", "words": words, "code": code, "correct": correct, "error": error}
    return {"turn": turn, "type": "pass", "reason": "no valid action"}


def _play_step(state, env):
    hidden = env.eleusis
    for i in _scientists(state):
        s = state[i]
        if s.status != "ACTIVE":
            continue
        obs = s.observation
        entry = _play_turn(obs, _unwrap(s.action), hidden.table, hidden.piles[i])
        obs.turns_used += 1
        obs.log = list(obs.log) + [entry]
        if obs.solved or obs.turns_used >= obs.max_turns:
            obs.score = _score(obs)
            s.reward = obs.score
            s.status = "INACTIVE"
    if all(state[i].status != "ACTIVE" for i in _scientists(state)):
        _finish(state)


def _finish(state):
    state[RULE_MAKER].reward = _rule_maker_reward(state)
    for s in state:
        s.observation.phase = "done"
        s.status = "DONE"
        s.reward = s.reward or 0


def _abort_on_agent_failure(state):
    """Void on crash/timeout; end scored on INVALID. True if the episode ended."""
    if any(s.status in _FRAMEWORK_FAILURE_STATUSES for s in state):
        for s in state:
            if s.status != "TIMEOUT":
                s.status = "ERROR"
        return True
    if any(s.status == "INVALID" for s in state):
        _finish(state)
        return True
    return False


def interpreter(state, env):
    if state[0].observation.phase == "":
        _initialize(state, env)
        return state
    if env.done:
        return state
    if _abort_on_agent_failure(state):
        return state
    if not hasattr(env, "eleusis"):
        # Hidden state lives on the Environment instance; it does not survive
        # env.clone() or a JSON round-trip. Fail loudly rather than guess.
        raise RuntimeError("eleusis: hidden state missing; run an episode in a single Environment instance.")
    if state[RULE_MAKER].observation.phase == "rule":
        _rule_step(state, env)
    else:
        _play_step(state, env)
    return state


def renderer(state, env):
    rm = state[RULE_MAKER].observation
    lines = [f"Phase: {rm.phase}"]
    if rm.secret_rule:
        r = rm.secret_rule
        lines.append(f"Secret rule ({r['source']}, accepts {r['accept_rate']:.0%}): {r['words']}  [{r['code']}]")
    for a in rm.rule_attempts:
        lines.append(f"  rejected rule: {a['code']} -- {a['error']}")
    for i in _scientists(state):
        obs = state[i].observation
        line = " -> ".join(
            m["card"] + (f" [x {' '.join(m['rejected'])}]" if m["rejected"] else "") for m in obs.mainline
        )
        status = "SOLVED" if obs.solved else ("out of turns" if obs.turns_used >= obs.max_turns else "playing")
        lines.append(
            f"Scientist {i}: {status}, turns {obs.turns_used}/{obs.max_turns}, "
            f"wrong guesses {len(obs.wrong_guesses)}, score {obs.score}"
        )
        if line:
            lines.append(f"  {line}")
    return "\n".join(lines) + "\n"


with open(path.join(dir_path, "eleusis.json")) as f:
    specification = json.load(f)


def html_renderer():
    jspath = path.join(dir_path, "visualizer", "default", "dist", "index.html")
    if path.exists(jspath):
        with open(jspath, encoding="utf-8") as f:
            return f.read()
    return ""


from .agents import agents  # noqa: E402, F401
