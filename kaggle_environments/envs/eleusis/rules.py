"""Eleusis rule language, fairness gate, equivalence check, and rule library.

A rule is ONE Python expression over two cards, ``card`` (the card being
played) and ``prev`` (the card it would follow). Each card exposes
``.rank`` (1-13; A=1, J=11, Q=12, K=13), ``.suit`` ("S", "H", "D", "C") and
``.color`` ("red" / "black").

Model output is never ``exec``'d as written. ``compile_rule`` parses the
expression, rejects any node outside a small whitelist, and rewrites every
arithmetic operator into a call to a guarded helper that only accepts ints
and caps their magnitude -- without that, ``card.suit * 1000 * 1000 * 1000``
would allocate a gigabyte string. Evaluation runs with ``__builtins__``
emptied.

Because v1 rules only look at ``(card, prev)``, a rule is fully described by
its truth table over the 52 x 52 = 2,704 ordered pairs of a single deck.
Two rules are equivalent iff their truth tables are equal: exact and
instant, no LLM judge.
"""

import ast
import itertools
import operator
from dataclasses import dataclass

SUITS = "SHDC"
RANKS = range(1, 14)
_RANK_NAMES = {1: "A", 11: "J", 12: "Q", 13: "K"}
_RANK_FROM_NAME = {"A": 1, "J": 11, "Q": 12, "K": 13, "T": 10}
_SUIT_SYMBOLS = {"♠": "S", "♥": "H", "♦": "D", "♣": "C"}


@dataclass(frozen=True)
class Card:
    rank: int
    suit: str

    @property
    def color(self) -> str:
        return "red" if self.suit in "HD" else "black"

    def __str__(self) -> str:
        return _RANK_NAMES.get(self.rank, str(self.rank)) + self.suit


DECK = [Card(r, s) for s in SUITS for r in RANKS]
_INDEX = {c: i for i, c in enumerate(DECK)}
NUM_PAIRS = len(DECK) * len(DECK)


def parse_card(text) -> Card | None:
    """Parse '10H', 'qd', 'TS', 'A♠' -> Card. Returns None if unparseable."""
    if not isinstance(text, str):
        return None
    s = text.strip().upper()
    for sym, letter in _SUIT_SYMBOLS.items():
        s = s.replace(sym, letter)
    if len(s) < 2 or s[-1] not in SUITS:
        return None
    rank_txt = s[:-1]
    rank = _RANK_FROM_NAME.get(rank_txt) or (int(rank_txt) if rank_txt.isdigit() else None)
    if rank not in RANKS:
        return None
    return Card(rank, s[-1])


def pair_index(card: Card, prev: Card) -> int:
    return _INDEX[card] * len(DECK) + _INDEX[prev]


# --- Compilation -------------------------------------------------------------


class RuleError(ValueError):
    """The expression is not a valid rule (syntax, forbidden construct, or runtime error)."""


MAX_SOURCE_CHARS = 500
MAX_NODES = 200
MAX_INT = 10**6
MAX_STR_CONST = 16

_ALLOWED_NODES = (
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare, ast.IfExp, ast.Name, ast.Load,
    ast.Constant, ast.Attribute, ast.Call, ast.Tuple, ast.List,
    ast.And, ast.Or, ast.Not, ast.USub,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Add, ast.Sub, ast.Mult, ast.Mod, ast.FloorDiv,
)  # fmt: skip
_FIELDS = {"rank", "suit", "color"}
_CARD_NAMES = {"card", "prev"}
_ARITH = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
          ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}  # fmt: skip
_ARITH_BY_NAME = {op.__name__: fn for op, fn in _ARITH.items()}


def _int_operand(x):
    # bool is an int subclass; (card.rank > 7) + 1 is legitimate.
    if not isinstance(x, int):
        raise TypeError(f"arithmetic needs numbers, got {type(x).__name__} {x!r}")
    return x


def _arith(op_name, a, b):
    result = _ARITH_BY_NAME[op_name](_int_operand(a), _int_operand(b))
    if abs(result) > MAX_INT:
        raise OverflowError(f"intermediate value {result} exceeds {MAX_INT}")
    return result


def _neg(x):
    return -_int_operand(x)


class _GuardArithmetic(ast.NodeTransformer):
    """Rewrite `a <op> b` -> `_arith("<op>", a, b)` and `-a` -> `_neg(a)`."""

    def visit_BinOp(self, node):
        self.generic_visit(node)
        name = type(node.op).__name__
        return ast.Call(ast.Name("_arith", ast.Load()), [ast.Constant(name), node.left, node.right], [])

    def visit_UnaryOp(self, node):
        self.generic_visit(node)
        if isinstance(node.op, ast.USub):
            return ast.Call(ast.Name("_neg", ast.Load()), [node.operand], [])
        return node


def _check_tree(tree):
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise RuleError(f"expression too large ({len(nodes)} syntax nodes, limit {MAX_NODES})")
    call_funcs = {id(n.func) for n in nodes if isinstance(n, ast.Call)}
    for n in nodes:
        if not isinstance(n, _ALLOWED_NODES):
            raise RuleError(f"forbidden syntax: {type(n).__name__}")
        if isinstance(n, ast.Name):
            if n.id == "abs":
                if id(n) not in call_funcs:
                    raise RuleError("abs may only be called, e.g. abs(card.rank - prev.rank)")
            elif n.id not in _CARD_NAMES:
                raise RuleError(f"unknown name: {n.id} (only card, prev and abs are allowed)")
        elif isinstance(n, ast.Attribute):
            if not (isinstance(n.value, ast.Name) and n.value.id in _CARD_NAMES) or n.attr not in _FIELDS:
                raise RuleError(f"forbidden attribute: .{n.attr} (use card/prev .rank, .suit or .color)")
        elif isinstance(n, ast.Call):
            if not (isinstance(n.func, ast.Name) and n.func.id == "abs") or len(n.args) != 1 or n.keywords:
                raise RuleError("the only allowed call is abs(<one argument>)")
        elif isinstance(n, ast.Constant):
            v = n.value
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                if abs(v) > MAX_INT:
                    raise RuleError(f"constant {v} too large")
            elif isinstance(v, str):
                if len(v) > MAX_STR_CONST:
                    raise RuleError(f"string constant too long: {v!r}")
            else:
                raise RuleError(f"forbidden constant type: {type(v).__name__}")


def compile_rule(src):
    """Compile a rule expression into ``fn(card, prev) -> bool``. Raises RuleError."""
    if not isinstance(src, str) or not src.strip():
        raise RuleError("rule code is empty")
    src = src.strip()
    if len(src) > MAX_SOURCE_CHARS:
        raise RuleError(f"rule code too long ({len(src)} chars, limit {MAX_SOURCE_CHARS})")
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as e:
        raise RuleError(f"syntax error: {e.msg}") from None
    _check_tree(tree)
    tree = ast.fix_missing_locations(_GuardArithmetic().visit(tree))
    code = compile(tree, "<rule>", "eval")
    env = {"__builtins__": {}, "abs": abs, "_arith": _arith, "_neg": _neg}
    return lambda card, prev: bool(eval(code, env, {"card": card, "prev": prev}))  # noqa: S307


def truth_table(src) -> tuple[bool, ...]:
    """Evaluate a rule on every (card, prev) pair. Raises RuleError on any failure.

    Index ``pair_index(card, prev)`` holds whether ``card`` may follow ``prev``.
    A rule that raises on ANY pair is rejected outright, so the engine never
    hits a runtime error mid-game.
    """
    fn = compile_rule(src)
    table = []
    for card, prev in itertools.product(DECK, DECK):
        try:
            table.append(fn(card, prev))
        except Exception as e:  # noqa: BLE001 -- any runtime error means the rule is invalid
            raise RuleError(f"error when card={card}, prev={prev}: {type(e).__name__}: {e}") from None
    return tuple(table)


def acceptance_rate(table) -> float:
    return sum(table) / len(table)


def fairness(table, lo=0.20, hi=0.60) -> str | None:
    """Return why a rule is unfair, or None if it passes the gate.

    1. Accepts between ``lo`` and ``hi`` of all (card, prev) pairs.
    2. Every card is playable after SOME card (no card is useless).
    3. After every card SOME card is playable (no dead end).
    """
    rate = acceptance_rate(table)
    if not lo <= rate <= hi:
        return f"accepts {rate:.0%} of (card, prev) pairs; must be between {lo:.0%} and {hi:.0%}"
    n = len(DECK)
    for ci, card in enumerate(DECK):
        if not any(table[ci * n + pi] for pi in range(n)):
            return f"{card} can never be played, whatever the previous card is"
    for pi, prev in enumerate(DECK):
        if not any(table[ci * n + pi] for ci in range(n)):
            return f"after {prev} no card can be played (dead end)"
    return None


def is_legal(table, card: Card, prev: Card) -> bool:
    return table[pair_index(card, prev)]


# --- Rule library ------------------------------------------------------------
# Fallback when the rule-maker fails the fairness gate, and the rule pool for
# scripted agents. Every entry passes `fairness` (enforced by tests).

LIBRARY = [
    ("easy", "Colors alternate", "card.color != prev.color"),
    ("easy", "Same color as the previous card", "card.color == prev.color"),
    ("easy", "Odd and even ranks alternate", "card.rank % 2 != prev.rank % 2"),
    ("easy", "Match the previous card's suit or rank", "card.suit == prev.suit or card.rank == prev.rank"),
    ("medium", "After a red card play an odd rank, after a black card an even rank",
     "card.rank % 2 == 1 if prev.color == 'red' else card.rank % 2 == 0"),
    ("medium", "Low (A-7) and high (8-K) alternate", "(card.rank >= 8) != (prev.rank >= 8)"),
    ("medium", "Suits cycle spades -> hearts -> diamonds -> clubs -> spades",
     "(card.suit, prev.suit) in (('H', 'S'), ('D', 'H'), ('C', 'D'), ('S', 'C'))"),
    ("medium", "Face cards (J, Q, K) and number cards alternate", "(card.rank >= 11) != (prev.rank >= 11)"),
    ("medium", "Rank within 3 of the previous rank", "abs(card.rank - prev.rank) <= 3"),
    ("hard", "The two ranks sum to 14 or more", "card.rank + prev.rank >= 14"),
    ("hard", "After spades/hearts same or higher rank, after diamonds/clubs same or lower",
     "card.rank >= prev.rank if prev.suit in ('S', 'H') else card.rank <= prev.rank"),
    ("hard", "Change color and stay within 4 ranks", "card.color != prev.color and abs(card.rank - prev.rank) <= 4"),
    ("hard", "After a black card play a prime rank, after a red card a non-prime rank",
     "card.rank in (2, 3, 5, 7, 11, 13) if prev.color == 'black' else card.rank not in (2, 3, 5, 7, 11, 13)"),
    ("hard", "After an odd rank change suit, after an even rank keep the suit",
     "card.suit != prev.suit if prev.rank % 2 == 1 else card.suit == prev.suit"),
]  # fmt: skip
