"""Built-in Eleusis agents. Every agent handles both roles; the seat decides which."""

import random

from .rules import LIBRARY, is_legal, parse_card, truth_table

_LIBRARY_TABLES = [(words, code, truth_table(code)) for _, words, code in LIBRARY]


def _library_rule():
    _, words, code = random.choice(LIBRARY)
    return {"words": words, "code": code}


def _evidence(mainline):
    """(card, prev, accepted) triples implied by a mainline with sidelines."""
    out = []
    for k, entry in enumerate(mainline):
        prev = parse_card(entry["card"])
        out.extend((parse_card(r), prev, False) for r in entry["rejected"])
        if k + 1 < len(mainline):
            out.append((parse_card(mainline[k + 1]["card"]), prev, True))
    return out


def random_agent(observation, configuration):
    """Rule-maker: a random library rule. Scientist: plays a random card, never guesses."""
    if observation.role == "rule_maker":
        return _library_rule()
    return {"action": "play", "card": random.choice(observation.hand)}


def perfect_agent(observation, configuration):
    """Rule-maker: a random library rule. Scientist: assumes the secret rule is
    a library rule, keeps the ones consistent with the evidence, guesses once
    a single candidate is left, and otherwise plays the hand card that splits
    the candidates most evenly."""
    if observation.role == "rule_maker":
        return _library_rule()
    evidence = _evidence(observation.mainline)
    wrong = {g["code"] for g in observation.wrong_guesses}
    candidates = {}
    for words, code, table in _LIBRARY_TABLES:
        if code not in wrong and all(is_legal(table, c, p) == ok for c, p, ok in evidence):
            candidates.setdefault(table, (words, code))
    if not candidates:
        return {"action": "play", "card": random.choice(observation.hand)}
    if len(candidates) > 1:
        prev = parse_card(observation.mainline[-1]["card"])

        def split(name):
            yes = sum(is_legal(t, parse_card(name), prev) for t in candidates)
            return min(yes, len(candidates) - yes)

        best = max(observation.hand, key=split)
        if split(best) > 0:
            return {"action": "play", "card": best}
    words, code = next(iter(candidates.values()))
    return {"action": "guess", "words": words, "code": code}


agents = {"random": random_agent, "perfect": perfect_agent}
