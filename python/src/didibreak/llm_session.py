"""One check run's use of the LLM: caches, price, budget, client and rounds.

The session plans every LLM request before the first one is sent, so the
cost estimate and the confirmation cover the refinement rounds too (task
16). One budget and one client serve all rounds. No output is printed here;
the CLI shows the plan and asks the user.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from didibreak.cache import CaseCache
from didibreak.cases import (
    PROMPT_FILE,
    REFINEMENT_PROMPT_FILE,
    CaseRun,
    PromptTemplate,
    load_template,
)
from didibreak.config import Config
from didibreak.functions import ChangedFunction
from didibreak.harness import Case
from didibreak.llm import client_settings, resolve_provider
from didibreak.llm.common import ClientSettings, TokenUsage
from didibreak.llm.pricing import LOCAL, prices_from_config, required_price
from didibreak.pipeline import (
    Budget,
    Estimate,
    Generation,
    estimate_generation,
    estimate_refinement,
    generate_cases,
)

ClientFactory = Callable[[Config, Mapping[str, str]], Any]


@dataclass(frozen=True)
class Plan:
    """The LLM requests a run may make, before any is sent.

    Attributes:
        initial: Requests for first cases (cache misses).
        refinement: Most refinement requests (cache misses, every round).
        estimate: Combined estimate of both.
    """

    initial: int
    refinement: int
    estimate: Estimate

    @property
    def calls(self) -> int:
        """Most requests the run can make."""
        return self.initial + self.refinement


@dataclass
class LLMSession:
    """LLM state of one run; use as a context manager to close the client."""

    config: Config
    environment: Mapping[str, str]
    settings: ClientSettings
    template: PromptTemplate
    refinement_template: PromptTemplate
    caches: tuple[CaseCache | None, CaseCache | None]
    factory: ClientFactory
    budget: Budget
    local: bool = False
    _client: Any = field(default=None, repr=False)

    @classmethod
    def open(
        cls, config: Config, environment: Mapping[str, str], factory: ClientFactory
    ) -> "LLMSession":
        """Resolve settings, templates and caches; no request is sent.

        Raises:
            ConfigError: Missing provider, model or API key.
        """
        settings = client_settings(config, environment)
        provider = resolve_provider(config, environment)
        template = load_template(PROMPT_FILE)
        refinement = load_template(REFINEMENT_PROMPT_FILE)
        caches: tuple[CaseCache | None, CaseCache | None] = (None, None)
        if not config.no_cache:
            folder = Path(config.output_dir)
            caches = (
                CaseCache(folder, provider, settings.model, template.version),
                CaseCache(folder, provider, settings.model, refinement.version),
            )
        budget = Budget(None, config.max_cost, config.cases)
        return cls(
            config, environment, settings, template, refinement, caches, factory, budget
        )

    def __enter__(self) -> "LLMSession":
        """Return the session itself."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the client if one was created."""
        if self._client is not None:
            self._client.close()

    def _cache(self, round_number: int) -> CaseCache | None:
        return self.caches[0] if round_number == 0 else self.caches[1]

    def _cached(
        self, function: ChangedFunction, round_number: int
    ) -> tuple[Case, ...] | None:
        cache = self._cache(round_number)
        if cache is None:
            return None
        return cache.load(function, self.config.cases, round_number)

    def plan(self, functions: Sequence[ChangedFunction]) -> Plan:
        """Count and estimate the requests the run may make.

        Refinement requests are counted for every function and round whose
        cases are not cached, as if no round found a difference.

        Raises:
            ConfigError: A request is needed and the model has no price and
                is not local (owner decision 2026-11-07).
        """
        count = self.config.cases
        initial = [f for f in functions if self._cached(f, 0) is None]
        rounds = [
            (function, round_number)
            for function in functions
            for round_number in range(1, self.config.refine_rounds + 1)
            if self._cached(function, round_number) is None
        ]
        price = None
        if initial or rounds:
            overrides = prices_from_config(self.config.prices)
            price = required_price(
                self.settings.model, self.settings.base_url, overrides
            )
            self.local = price.source == LOCAL
            self.budget = Budget(price, self.config.max_cost, count)
        first = estimate_generation(initial, count, self.template, price)
        more = estimate_refinement(rounds, count, self.refinement_template, price)
        cost = None if price is None else (first.cost_usd or 0) + (more.cost_usd or 0)
        estimate = Estimate(first.calls + more.calls, first.usage + more.usage, cost)
        return Plan(len(initial), len(rounds), estimate)

    def cases(
        self,
        functions: Sequence[ChangedFunction],
        round_number: int = 0,
        previous: Mapping[str, Sequence[CaseRun]] | None = None,
    ) -> Generation:
        """Cached or newly generated cases for one round.

        Args:
            functions: Functions to get cases for.
            round_number: 0 for first cases, 1 and up for refinement.
            previous: For refinement, the cases already run per report name.

        Returns:
            The round's cases (cached ones included), skips, usage and cost.
        """
        cached = {
            f.report_name: found
            for f in functions
            if (found := self._cached(f, round_number))
        }
        missing = [f for f in functions if f.report_name not in cached]
        generation = Generation({}, (), 0, TokenUsage(), 0.0)
        if missing:
            if self._client is None:
                self._client = self.factory(self.config, self.environment)
            template = self.template if round_number == 0 else self.refinement_template
            generation = generate_cases(
                self._client,
                missing,
                self.config.cases,
                template,
                budget=self.budget,
                previous=previous if round_number else None,
            )
            self._store(missing, generation, round_number)
        return replace(generation, cases={**cached, **generation.cases})

    def _store(
        self,
        functions: Sequence[ChangedFunction],
        generation: Generation,
        round_number: int,
    ) -> None:
        cache = self._cache(round_number)
        for function in functions if cache else ():
            found = generation.cases.get(function.report_name)
            if cache and found:
                cache.store(function, self.config.cases, found, round_number)
