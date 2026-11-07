"""check with refinement rounds: a fake provider whose first cases miss (task 16)."""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest
from fixture_repos import FixtureRepository, build_fixture_repository

from didibreak import cli, llm
from didibreak.cli import EXIT_FINDINGS, EXIT_OK, main
from didibreak.config import Config

FUNCTION = "app/utils/phone.py::normalize_phone"
NO_DIFFERENCE = ["'555 12 34 56'"]  # same result in both versions
REGRESSION = ["'995 555 12 34 56'"]  # documented unexpected finding


def case(args: list[str], rationale: str = "r") -> dict[str, Any]:
    return {"args": args, "kwargs": [], "rationale": rationale}


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FixtureRepository:
    fixture = build_fixture_repository("phone_regression", tmp_path / "repo")
    monkeypatch.chdir(fixture.repository.path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return fixture


def install(
    monkeypatch: pytest.MonkeyPatch,
    first: list[str],
    later: list[list[str]],
    completion_tokens: int = 100,
) -> list[str]:
    """Fake provider: ``first`` for the first request, ``later[i]`` for refinements."""
    prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        prompt = json.loads(request.content)["messages"][-1]["content"]
        prompts.append(prompt)
        refinements = sum("Cases already tried" in p for p in prompts)
        args = first if refinements == 0 else later[min(refinements, len(later)) - 1]
        content = json.dumps({"cases": [case(args)]})
        body = {
            "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 500, "completion_tokens": completion_tokens},
        }
        return httpx.Response(200, json=body)

    def create(config: Config, environment: Mapping[str, str]) -> object:
        return llm.create_client(config, environment, httpx.MockTransport(handler))

    monkeypatch.setattr(cli, "create_client", create)
    return prompts


def test_refinement_finds_the_regression_the_first_cases_missed(
    repo: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompts = install(monkeypatch, NO_DIFFERENCE, [REGRESSION])

    assert main(["check"]) == EXIT_FINDINGS

    assert len(prompts) == 2
    assert "Cases already tried" not in prompts[0]
    refinement = prompts[1]
    assert (
        "- normalize_phone('555 12 34 56') -> old: '+995555123456'; "
        "new: '+995555123456'" in refinement
    )
    err = capsys.readouterr().err
    assert f"{FUNCTION}('995 555 12 34 56')" in err
    assert "before '+995555123456' → after '+995995555123456'" in err
    assert "Refinement: 1 function(s) got 1 more cases" in err
    assert "2 cases · 1 behavior changes" in err


def test_without_refinement_the_regression_is_missed(
    repo: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompts = install(monkeypatch, NO_DIFFERENCE, [REGRESSION])

    assert main(["check", "--refine-rounds", "0"]) == EXIT_OK

    assert len(prompts) == 1
    assert "1 cases · 0 behavior changes" in capsys.readouterr().err


def test_default_is_exactly_one_refinement_round(
    repo: FixtureRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    misses = [["'1'"], ["'2'"], ["'3'"]]
    prompts = install(monkeypatch, NO_DIFFERENCE, misses)

    main(["check"])

    assert len(prompts) == 2


def test_rounds_stop_at_the_configured_maximum(
    repo: FixtureRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    misses = [["'1'"], ["'2'"], ["'3'"], ["'4'"]]
    prompts = install(monkeypatch, NO_DIFFERENCE, misses)

    main(["check", "--refine-rounds", "3"])

    assert len(prompts) == 4  # first request + 3 refinements
    assert "- normalize_phone('2') ->" in prompts[3]  # all earlier cases listed


def test_estimate_counts_the_refinement_rounds(
    repo: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    install(monkeypatch, NO_DIFFERENCE, [REGRESSION])

    main(["check", "--refine-rounds", "3"])

    err = capsys.readouterr().err
    assert "Estimated: up to 4 LLM calls (1 + up to 3 refinement)" in err


def test_cost_limit_covers_refinement(
    repo: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The first reply costs $0.0013 (500 input, 2,500 output tokens); the
    # refinement estimate then follows those output tokens and does not fit.
    prompts = install(monkeypatch, NO_DIFFERENCE, [REGRESSION], 2500)
    limit = "0.0015"

    assert main(["check", "--max-cost", limit]) == EXIT_OK

    assert len(prompts) == 1
    err = capsys.readouterr().err
    assert f"refinement skipped: {FUNCTION} (cost limit)" in err


def test_refinement_cases_are_cached_by_round(
    repo: FixtureRepository, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts = install(monkeypatch, NO_DIFFERENCE, [REGRESSION])
    assert main(["check"]) == EXIT_FINDINGS
    prompts.clear()

    assert main(["check"]) == EXIT_FINDINGS

    assert prompts == []  # both rounds came from the cache
    cache = repo.repository.path / ".didibreak" / "cache" / "cases"
    assert len(list(cache.glob("*.json"))) == 2
