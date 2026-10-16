import pytest

from kaggle_environments import make
from kaggle_environments.envs.eleusis import rules
from kaggle_environments.envs.eleusis.agents import perfect_agent, random_agent
from kaggle_environments.errors import DeadlineExceeded

RULE = {"words": "Colors alternate", "code": "card.color != prev.color"}


def _make(**config):
    return make("eleusis", configuration={"seed": 3, **config})


def _rule_then(scientist):
    """Agent: submits RULE as rule-maker, delegates to `scientist` otherwise."""

    def agent(obs, config):
        return RULE if obs.role == "rule_maker" else scientist(obs, config)

    return agent


def _solver(obs, config):
    return {"action": "guess", "words": "color changes", "code": "not (card.color == prev.color)"}


# --- rules ---------------------------------------------------------------------


@pytest.mark.parametrize("level,words,code", rules.LIBRARY)
def test_library_rules_pass_fairness(level, words, code):
    assert rules.fairness(rules.truth_table(code)) is None


@pytest.mark.parametrize(
    "src",
    [
        "__import__('os').system('echo hi')",
        "card.__class__",
        "(lambda: 1)()",
        "[c for c in (1, 2)]",
        "card.rank ** 2 > 3",
        "card.suit * 1000 * 1000 * 1000 == 'S'",
        "(1, 2) * 100000000 == ()",
        "card.rank % 0 == 1",
        "open('x')",
        "x",
        "abs",
        "card.rank.real",
        "f'{card}'",
        "card.rank == 99999999",
        " or ".join(["card.rank == 1"] * 100),
        "",
    ],
)
def test_malicious_or_broken_rules_rejected(src):
    with pytest.raises(rules.RuleError):
        rules.truth_table(src)


def test_equivalence_is_semantic():
    assert rules.truth_table("card.color != prev.color") == rules.truth_table(
        "(card.suit in ('H', 'D')) != (prev.suit in 'HD')"
    )
    assert rules.truth_table("card.color != prev.color") != rules.truth_table("card.suit != prev.suit")


@pytest.mark.parametrize(
    "code,fragment",
    [("card.rank > 0", "accepts 100%"), ("prev.color == 'red'", "dead end"), ("card.rank != 1 and prev.rank < 8", "")],
)
def test_fairness_reasons(code, fragment):
    reason = rules.fairness(rules.truth_table(code))
    assert reason is not None and fragment in reason


def test_parse_card():
    assert [str(rules.parse_card(s)) for s in ("10h", "qd", "T♠", " ks ")] == ["10H", "QD", "10S", "KS"]
    assert rules.parse_card("14S") is None and rules.parse_card("ZZ") is None and rules.parse_card(None) is None


# --- full games ------------------------------------------------------------------


@pytest.mark.parametrize("num_agents", [3, 4, 5])
def test_random_game_completes(num_agents):
    env = _make()
    env.run([random_agent] * num_agents)
    assert [s.status for s in env.state] == ["DONE"] * num_agents
    assert all(s.observation.turns_used == 30 for s in env.state[1:])


def test_perfect_scientists_solve_library_rules():
    for seed in range(10):
        env = _make(seed=seed)
        env.run([perfect_agent] * 3)
        assert all(s.observation.solved for s in env.state[1:]), env.render(mode="ansi")
        assert env.state[0].reward == min(s.reward for s in env.state[1:]) > 0


def test_identical_deal_at_every_table():
    env = _make()
    env.run([random_agent] * 4)
    dealt = env.steps[1]
    assert len({(s.observation.mainline[0]["card"], tuple(s.observation.hand)) for s in dealt[1:]}) == 1


def test_scoring_and_second_best_rule_maker_reward():
    wrong = {"action": "guess", "words": "same suit", "code": "card.suit == prev.suit"}

    def wrong_then_solve(obs, config):
        return wrong if obs.turns_used == 0 else _solver(obs, config)

    env = _make(wrong_guess_penalty=5)
    env.run([_rule_then(_solver), _rule_then(_solver), _rule_then(wrong_then_solve), _rule_then(random_agent)])
    rewards = [s.reward for s in env.state]
    # solver: 30 - 1 turn; wrong-then-solve: 30 - 2 turns - 5; random never solves.
    assert rewards == [23, 29, 23, 0]


def test_play_moves_card_to_mainline_or_sideline():
    def play_first(obs, config):
        return {"action": "play", "card": obs.hand[0]}

    env = _make(max_turns=5)
    env.run([_rule_then(play_first)] * 3)
    obs = env.state[1].observation
    for entry in obs.log:
        assert entry["type"] == "play"
        prev, card = rules.parse_card(entry["prev"]), rules.parse_card(entry["card"])
        assert entry["accepted"] == (card.color != prev.color)
    assert len(obs.hand) == 12
    assert sum(1 + len(m["rejected"]) for m in obs.mainline) == 1 + 5


def test_bad_actions_are_scored_not_voided():
    def bad(obs, config):
        return [
            {"action": "play", "card": "ZZ"},
            {"action": "dance"},
            {"submission": -1, "actionString": '{"action": "guess", "words": "", "code": "import os"}'},
            {"submission": -1, "actionString": None},
        ][obs.turns_used % 4]

    env = _make(max_turns=4)
    env.run([_rule_then(_solver), _rule_then(_solver), _rule_then(bad)])
    assert [s.status for s in env.state] == ["DONE"] * 3
    log = env.state[2].observation.log
    assert [e["type"] for e in log] == ["pass", "pass", "guess", "pass"]
    assert log[2]["error"] and len(env.state[2].observation.wrong_guesses) == 1
    assert [s.reward for s in env.state] == [0, 3, 0]  # 4 turns - 1


def test_unfair_rule_retries_then_falls_back_to_library():
    def unfair(obs, config):
        if obs.role == "rule_maker":
            return {"words": "anything", "code": "card.rank > 0"}
        return _solver(obs, config)

    env = _make()
    env.run([unfair, perfect_agent, perfect_agent])
    rm = env.state[0].observation
    assert len(rm.rule_attempts) == 3 and "accepts 100%" in rm.rule_attempts[0]["error"]
    assert rm.secret_rule["source"] == "library"
    assert env.state[0].reward == 0 and all(s.reward > 0 for s in env.state[1:])


def test_rule_accepted_after_a_rejection():
    def second_try(obs, config):
        if obs.role == "rule_maker":
            return RULE if obs.rule_attempts else {"words": "?", "code": "card.rank ** 2"}
        return _solver(obs, config)

    env = _make()
    env.run([second_try] * 3)
    rm = env.state[0].observation
    assert len(rm.rule_attempts) == 1 and "Pow" in rm.rule_attempts[0]["error"]
    assert rm.secret_rule["source"] == "rule_maker" and env.state[0].reward == 29


def test_secret_rule_never_on_scientist_observations():
    env = _make()
    env.run([_rule_then(_solver)] * 3)
    for step in env.steps:
        for s in step[1:]:
            assert s.observation.get("secret_rule") is None


@pytest.mark.parametrize("seat", range(3))
def test_agent_crash_voids_the_episode(seat):
    def crash(obs, config):
        raise RuntimeError("provider exploded")

    agents = [_rule_then(_solver)] * 3
    agents[seat] = crash
    env = _make()
    env.run(agents)
    assert [s.status for s in env.state] == ["ERROR"] * 3
    assert [s.reward for s in env.state] == [None] * 3


@pytest.mark.parametrize("seat", range(3))
def test_timeout_voids_the_episode(seat):
    def slow(obs, config):
        return DeadlineExceeded()

    agents = [_rule_then(_solver)] * 3
    agents[seat] = slow
    env = _make()
    env.run(agents)
    statuses = [s.status for s in env.state]
    assert statuses[seat] == "TIMEOUT" and set(statuses) <= {"TIMEOUT", "ERROR"}
    assert [s.reward for s in env.state] == [None] * 3


def test_renderer():
    env = _make()
    env.run([perfect_agent] * 3)
    out = env.render(mode="ansi")
    assert "Secret rule" in out and "Scientist 2" in out


def test_every_step_has_an_action_field():
    """local_harness_runner prints `agent_state.action` for every step; a null
    action default drops the key on step 0 and crashes the run before the
    replay is saved."""
    env = _make()
    env.run([perfect_agent] * 3)
    assert all("action" in s for step in env.steps for s in step)
