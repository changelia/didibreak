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
from didibreak.compare import Finding
from didibreak.config import Config
from didibreak.functions import ChangedFunction
from didibreak.harness import Case
from didibreak.intent import (
    LABEL_PROMPT_FILE,
    LABELS_SCHEMA,
    LABELS_SCHEMA_NAME,
    MAX_LABELLED_FINDINGS,
    apply_labels,
    build_label_messages,
    mark_unclear,
    to_label,
)
from didibreak.llm import client_settings, resolve_provider
from didibreak.llm.common import (
    ClientSettings,
    LLMInvalidResponseError,
    LLMRequestError,
    LLMUnavailableError,
    TokenUsage,
)
from didibreak.llm.pricing import LOCAL, cost_usd, prices_from_config, run_price
from didibreak.pipeline import (
    CHARS_PER_TOKEN,
    Budget,
    Estimate,
    Generation,
    estimate_call,
    estimate_generation,
    estimate_refinement,
    generate_cases,
)

# Labelling estimate: one line per finding and its label and reason.
FINDING_LINE_CHARS = 250
OUTPUT_TOKENS_PER_LABEL = 120
LABELLING_FAILED = "intent labelling failed: "

ClientFactory = Callable[[Config, Mapping[str, str]], Any]


@dataclass(frozen=True)
class Plan:
    """The LLM requests a run may make, before any is sent.

    Attributes:
        initial: Requests for first cases (cache misses).
        refinement: Most refinement requests (cache misses, every round).
        labelling: 1 when findings will be labelled against an intent.
        estimate: Combined estimate of all of them.
    """

    initial: int
    refinement: int
    labelling: int
    estimate: Estimate

    @property
    def calls(self) -> int:
        """Most requests the run can make."""
        return self.initial + self.refinement + self.labelling


@dataclass
class LLMSession:
    """LLM state of one run; use as a context manager to close the client."""

    config: Config
    environment: Mapping[str, str]
    settings: ClientSettings
    template: PromptTemplate
    refinement_template: PromptTemplate
    label_template: PromptTemplate
    caches: tuple[CaseCache | None, CaseCache | None]
    factory: ClientFactory
    budget: Budget
    local: bool = False
    unpriced: bool = False
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
        labels = load_template(LABEL_PROMPT_FILE)
        caches: tuple[CaseCache | None, CaseCache | None] = (None, None)
        if not config.no_cache:
            folder = Path(config.output_dir)
            caches = (
                CaseCache(folder, provider, settings.model, template.version),
                CaseCache(folder, provider, settings.model, refinement.version),
            )
        budget = Budget(None, config.max_cost, config.cases, config.max_tokens)
        return cls(
            config,
            environment,
            settings,
            template,
            refinement,
            labels,
            caches,
            factory,
            budget,
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

    def plan(
        self, functions: Sequence[ChangedFunction], intent: str | None = None
    ) -> Plan:
        """Count and estimate the requests the run may make.

        Refinement requests are counted for every function and round whose
        cases are not cached, as if no round found a difference. With an
        intent, one labelling request is added (labels are never cached).

        When a request is needed, sets ``local`` (cost 0) or ``unpriced``
        (no known price: cost unknown, only max_tokens applies; task 34).
        """
        count = self.config.cases
        initial = [f for f in functions if self._cached(f, 0) is None]
        rounds = [
            (function, round_number)
            for function in functions
            for round_number in range(1, self.config.refine_rounds + 1)
            if self._cached(function, round_number) is None
        ]
        labelling = 1 if intent and functions else 0
        price = None
        if initial or rounds or labelling:
            overrides = prices_from_config(self.config.prices)
            price = run_price(self.settings.model, self.settings.base_url, overrides)
            self.local = price is not None and price.source == LOCAL
            self.unpriced = price is None
            self.budget = Budget(
                price, self.config.max_cost, count, self.config.max_tokens
            )
        first = estimate_generation(initial, count, self.template, price)
        more = estimate_refinement(rounds, count, self.refinement_template, price)
        usage = first.usage + more.usage
        if labelling:
            usage += self._labelling_estimate(intent or "", len(functions))
        cost = None if price is None else cost_usd(usage, price)
        estimate = Estimate(first.calls + more.calls + labelling, usage, cost)
        return Plan(len(initial), len(rounds), labelling, estimate)

    def _labelling_estimate(self, intent: str, functions: int) -> TokenUsage:
        rounds = 1 + self.config.refine_rounds
        findings = min(functions * self.config.cases * rounds, MAX_LABELLED_FINDINGS)
        messages = build_label_messages(intent, (), self.label_template)
        call = estimate_call(messages, findings, OUTPUT_TOKENS_PER_LABEL)
        extra = findings * FINDING_LINE_CHARS // CHARS_PER_TOKEN
        return replace(call, input_tokens=call.input_tokens + extra)

    def label(
        self, findings: Sequence[Finding], intent: str | None, no_intent: str
    ) -> tuple[Finding, ...]:
        """Label findings against the intent with one request (task 17).

        Args:
            findings: All findings of the run.
            intent: The intent text, or None.
            no_intent: Reason used when there is no intent.

        Returns:
            The same findings, labelled; on any labelling problem they are
            unclear with the reason. A rejected key or an unknown model
            still raises (exit 2).
        """
        if intent is None:
            return mark_unclear(findings, no_intent)
        sent = to_label(findings)
        if not sent:
            return tuple(findings)
        messages = build_label_messages(intent, sent, self.label_template)
        refusal = self.budget.refusal(messages)
        if refusal is not None:
            return mark_unclear(findings, LABELLING_FAILED + refusal)
        if self._client is None:
            self._client = self.factory(self.config, self.environment)
        try:
            reply = self._client.complete_json(
                messages, LABELS_SCHEMA, LABELS_SCHEMA_NAME
            )
        except LLMInvalidResponseError as error:
            self.budget.add(error.usage)
            return mark_unclear(findings, LABELLING_FAILED + "invalid llm response")
        except LLMUnavailableError:
            return mark_unclear(findings, LABELLING_FAILED + "llm unavailable")
        except LLMRequestError as error:
            reason = f"{LABELLING_FAILED}request rejected: {error.provider_message}"
            return mark_unclear(findings, reason)
        self.budget.add(reply.usage)
        return apply_labels(findings, reply.data)

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
