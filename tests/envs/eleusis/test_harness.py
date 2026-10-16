import json
from unittest.mock import patch

from kaggle_environments import core_harness, make
from kaggle_environments.core_harness import create_agent_fn
from kaggle_environments.envs.eleusis.harness import generate_prompt, get_legal_moves, parse_response


class _EleusisHarness:
    """Test-local GameHarness adapter; mirrors the prod wrapper shape."""

    def get_legal_moves(self, observation):
        return get_legal_moves(observation)

    def make_prompt(self, observation, move_history, previous_response=None, previous_action=None):
        return generate_prompt(observation, move_history, previous_response, previous_action)

    def parse_response(self, response, legal_action_strings, *, observation=None):
        return parse_response(response, legal_action_strings, observation=observation)


class _Delta:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content, finish_reason=None):
        self.delta = _Delta(content)
        self.finish_reason = finish_reason


class _Chunk:
    def __init__(self, choices, usage=None):
        self.choices = choices
        self.usage = usage


class _Usage:
    prompt_tokens = 1
    completion_tokens = 1
    total_tokens = 2
    completion_tokens_details = None


def _fake_completion(content):
    return [_Chunk([_Choice(content)]), _Chunk([_Choice("", finish_reason="stop")]), _Chunk([], usage=_Usage())]


_ENV = {"MODEL_NAME": "test-model", "MODEL_PROXY_KEY": "key", "MODEL_PROXY_URL": "dummy_url"}

RULE_MAKER = {
    "role": "rule_maker",
    "phase": "rule",
    "max_turns": 30,
    "wrong_guess_penalty": 2,
    "rule_retries": 3,
    "accept_rate_min": 0.2,
    "accept_rate_max": 0.6,
    "num_scientists": 2,
    "rule_attempts": [],
}

SCIENTIST = {
    "role": "scientist",
    "phase": "play",
    "max_turns": 30,
    "wrong_guess_penalty": 2,
    "hand": ["10H", "QD", "2S"],
    "mainline": [{"card": "5H", "rejected": ["7H"]}, {"card": "9S", "rejected": []}],
    "wrong_guesses": [{"words": "same suit", "code": "card.suit == prev.suit", "error": None}],
    "log": [{"type": "play"}, {"type": "pass"}],
    "turns_used": 4,
}


def _parse(response, obs):
    return parse_response(response, None, observation=obs)


# --- parse_response ----------------------------------------------------------


def test_get_legal_moves_is_free_form():
    assert get_legal_moves(SCIENTIST) is None


def test_rule_maker_valid_rule():
    r = _parse('I pick colors.\n```json\n{"words": "alternate", "code": "card.color != prev.color"}\n```', RULE_MAKER)
    assert r.submission == {"words": "alternate", "code": "card.color != prev.color"}


def test_rule_maker_invalid_code_withheld_with_raw_action():
    r = _parse('{"words": "x", "code": "card.rank ** 2 > 4"}', RULE_MAKER)
    assert r.submission is None and json.loads(r.raw_action)["code"] == "card.rank ** 2 > 4"


def test_no_json_is_unparsable():
    assert _parse("I would play the ten of hearts.", SCIENTIST).raw_action is None
    assert _parse("no rule", RULE_MAKER).raw_action is None


def test_last_json_wins():
    r = _parse('{"action": "play", "card": "QD"} hmm, no: {"action": "play", "card": "2s"}', SCIENTIST)
    assert r.submission == {"action": "play", "card": "2S"}


def test_play_normalizes_card():
    assert _parse('{"action": "PLAY", "card": "10h"}', SCIENTIST).submission == {"action": "play", "card": "10H"}


def test_play_card_not_in_hand_withheld():
    r = _parse('{"action": "play", "card": "KC"}', SCIENTIST)
    assert r.submission is None and r.raw_action is not None


def test_illegal_json_does_not_ghost_substitute_from_prose():
    r = _parse('I could play 10H or QD, but {"action": "play", "card": "AS"}', SCIENTIST)
    assert r.submission is None


def test_guess_valid_and_invalid():
    ok = _parse('{"action": "guess", "words": "w", "code": "card.rank > prev.rank"}', SCIENTIST)
    assert ok.submission["code"] == "card.rank > prev.rank"
    bad = _parse('{"action": "guess", "words": "w", "code": "import os"}', SCIENTIST)
    assert bad.submission is None and json.loads(bad.raw_action)["action"] == "guess"


# --- prompts -------------------------------------------------------------------


def test_rule_maker_prompt():
    p = generate_prompt(RULE_MAKER, [])
    assert "RULE-MAKER" in p and "20%" in p and "60%" in p and "LOWER of the two" in p and '"code"' in p
    obs = dict(RULE_MAKER, num_scientists=3, rule_attempts=[{"code": "card.rank > 0", "error": "accepts 100%"}])
    p = generate_prompt(obs, [])
    assert "SECOND-HIGHEST" in p and "card.rank > 0  -> accepts 100%" in p and "2 attempts left" in p


def test_scientist_prompt_renders_table():
    p = generate_prompt(SCIENTIST, [])
    assert "5H [rejected: 7H] -> 9S" in p
    assert "Last accepted card (your next card is judged against it): 9S" in p
    assert "Your hand: 10H QD 2S" in p
    assert "Turns used: 4 of 30 (26 left); 1 turns lost" in p
    assert "same suit | code: card.suit == prev.suit" in p
    assert "secret" in p.lower() and "card.color" in p


def test_rethink_suffixes():
    invalid = generate_prompt(SCIENTIST, [], "...", json.dumps({"action": "play", "card": "KC"}))
    assert "'KC' is not a card in your hand" in invalid
    bad_code = generate_prompt(RULE_MAKER, [], "...", json.dumps({"words": "", "code": "card.rank ** 2"}))
    assert "Pow" in bad_code
    unparsable = generate_prompt(SCIENTIST, [], "x" * 600 + "THE END", None)
    assert "THE END" in unparsable and "x" * 501 not in unparsable


# --- end to end through the env -------------------------------------------------


def test_full_game_with_mocked_llm():
    """Rule-maker: one unfair rule, then a fair one. Scientists: one unparsable
    reply, one bad card, a play, then the correct guess."""
    calls = {"rule": 0}

    def llm(*args, **kwargs):
        prompt = kwargs["messages"][-1]["content"]
        if "RULE-MAKER" in prompt:
            calls["rule"] += 1
            code = "card.rank > 0" if calls["rule"] == 1 else "card.color != prev.color"
            return _fake_completion(json.dumps({"words": "colors alternate", "code": code}))
        if "Turns used: 0 of" in prompt and "previous reply had no usable JSON" not in prompt:
            return _fake_completion("let me think... no answer")
        if "Turns used: 0 of" in prompt:
            return _fake_completion('{"action": "play", "card": "ZZ"}')  # second failure -> forfeit -> pass
        if "Turns used: 1 of" in prompt:
            hand = prompt.split("Your hand: ")[1].split("\n")[0].split()
            return _fake_completion(json.dumps({"action": "play", "card": hand[0]}))
        return _fake_completion('{"action": "guess", "words": "alternate", "code": "card.color != prev.color"}')

    env = make("eleusis", configuration={"seed": 1})
    agents = [create_agent_fn(_EleusisHarness()) for _ in range(3)]
    with patch.dict("os.environ", _ENV), patch.object(core_harness.litellm, "completion", side_effect=llm):
        env.run(agents)
    assert [s.status for s in env.state] == ["DONE"] * 3, env.render(mode="ansi")
    rm = env.state[0].observation
    assert len(rm.rule_attempts) == 1 and rm.secret_rule["source"] == "rule_maker"
    for s in env.state[1:]:
        assert [e["type"] for e in s.observation.log] == ["pass", "play", "guess"]
        assert s.reward == 27
    assert env.state[0].reward == 27
