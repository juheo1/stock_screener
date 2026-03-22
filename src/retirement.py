"""
src.retirement
==============
Retirement planning engine combining two modes:

1. **Deterministic Planning** – ports the 401k-aware saving_plan logic to answer
   "what annual return rate do I need to retire comfortably?"  Considers taxable
   accounts, Traditional 401k (pre-tax), Roth 401k (tax-free), employer match,
   IRS contribution limits, and post-retirement inflation-growing withdrawals.

2. **Monte Carlo Simulation** – three scenario (conservative / expected / optimistic)
   log-normal annual-return model, year-by-year P10/P50/P90 projections.

Public API
----------
calculate_retirement_planning(params)  -> PlanningResult | None
run_retirement_projection(params)      -> dict[str, ScenarioResult]
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pre-computed random cache (for "Fast" mode)
# ---------------------------------------------------------------------------

_RANDOM_CACHE: dict[tuple[int, int], np.ndarray] = {}
_RANDOM_CACHE_LOCK = threading.Lock()


def _get_cached_randoms(n_simulations: int, horizon: int) -> np.ndarray:
    """Return cached standard-normal samples of shape (n_simulations, horizon).

    Generated once with seed=0 and reused for every "Fast" mode call.
    Thread-safe via a module-level lock.
    """
    key = (n_simulations, horizon)
    with _RANDOM_CACHE_LOCK:
        if key not in _RANDOM_CACHE:
            rng = np.random.default_rng(0)
            _RANDOM_CACHE[key] = rng.standard_normal(size=(n_simulations, horizon))
            logger.debug("Cached %dx%d random normals", n_simulations, horizon)
        return _RANDOM_CACHE[key]


# ---------------------------------------------------------------------------
# Input / Output data classes  (Monte Carlo)
# ---------------------------------------------------------------------------

@dataclass
class ScenarioAssumptions:
    """Return and volatility assumptions for one MC scenario."""
    expected_return: float
    volatility: float
    label: str = ""


@dataclass
class YearProjection:
    """Portfolio value at the end of a single projected year."""
    age: int
    year_offset: int
    p10: float
    p50: float
    p90: float
    mean: float


@dataclass
class ScenarioResult:
    """Full Monte Carlo projection for one scenario."""
    label: str
    projections: list[YearProjection]
    final_p10: float
    final_p50: float
    final_p90: float
    readiness_score: float | None = None


# ---------------------------------------------------------------------------
# Planning engine data classes
# ---------------------------------------------------------------------------

@dataclass
class Account401kParams:
    """401k account parameters for the deterministic planning engine."""
    traditional_balance: float = 0.0
    roth_balance: float = 0.0
    monthly_traditional_contribution: float = 0.0
    monthly_roth_contribution: float = 0.0
    employer_match_rate: float = 0.0
    employer_match_cap: float = 0.06        # fraction of salary matched
    annual_salary: float = 0.0
    annual_employee_limit: float = 23_500.0  # 2025 IRS limit


@dataclass
class TaxRateParams:
    """Tax rate assumptions for after-tax portfolio conversion."""
    ordinary_income_rate: float = 0.22   # for Traditional 401k withdrawals
    capital_gains_rate: float = 0.15     # for taxable account gains
    cost_basis_ratio: float = 0.50       # fraction of taxable FV that is basis


@dataclass
class PlanningResult:
    """Output of the deterministic planning calculation.

    Dollar values are nominal at retirement date.
    ``required_nest_egg`` is in after-tax spendable dollars.
    """
    monthly_spending_at_retirement: float   # nominal monthly spend at retirement
    required_nest_egg: float                # PV of inflation-growing annuity (after-tax)
    required_return_rate: float             # binary-search result (annual nominal)
    fv_taxable: float                       # taxable account FV at required_return_rate
    fv_trad_401k: float                     # Traditional 401k FV (gross, pre-tax)
    fv_roth_401k: float                     # Roth 401k FV (tax-free)
    fv_roth_ira: float                      # Roth IRA FV (tax-free)
    after_tax_total: float                  # after-tax equivalent of all accounts
    eff_monthly_trad: float                 # effective employee Traditional contribution/mo
    eff_monthly_roth: float                 # effective employee Roth 401k contribution/mo
    eff_monthly_match: float                # effective employer match contribution/mo
    eff_monthly_roth_ira: float             # effective Roth IRA contribution/mo (after IRS limit)


# ---------------------------------------------------------------------------
# Input parameters (unified for both engines)
# ---------------------------------------------------------------------------

@dataclass
class RetirementParams:
    """Input parameters for both the planning and Monte Carlo engines.

    Existing fields (Monte Carlo)
    -----------------------------
    current_value : float
        Taxable account balance in USD.  For MC, combined with 401k balances.
    current_age : int
    retirement_age : int
    annual_contribution : float
        Yearly taxable-account contribution for the MC engine (derived as
        ``monthly_taxable_contribution * 12`` when using the planning engine).
    contribution_growth_rate : float
        Annual growth rate of taxable contributions (e.g. 0.03 for 3%).
    target_retirement_value : float | None
        Optional MC readiness target.  Auto-set to ``required_nest_egg`` when
        planning mode is active and no explicit target is provided.
    inflation_rate : float
    n_simulations : int
    seed : int | None

    Planning engine fields (all optional, have defaults)
    ----------------------------------------------------
    monthly_spending : float
        Current monthly spending in today's dollars.  Set to 0 to skip
        planning mode and use MC-only.
    life_expectancy : int
    monthly_taxable_contribution : float
        Monthly savings into the taxable account.
    trad_401k_balance : float
    roth_401k_balance : float
    monthly_trad_401k : float
    monthly_roth_401k : float
    employer_match_rate : float
    employer_match_cap : float
    annual_salary : float
    irs_limit_401k : float
    ordinary_income_rate : float
    capital_gains_rate : float
    cost_basis_ratio : float
    post_retirement_return : float
        Expected annual portfolio return *after* retirement (used for nest egg
        calculation, distinct from pre-retirement MC scenario returns).
    """
    # --- Monte Carlo required fields ---
    current_value: float
    current_age: int
    retirement_age: int

    # --- Monte Carlo optional fields ---
    annual_contribution: float = 0.0
    contribution_growth_rate: float = 0.03
    target_retirement_value: float | None = None
    inflation_rate: float = 0.03
    scenarios: dict[str, ScenarioAssumptions] | None = None
    n_simulations: int = 1000
    seed: int | None = 42

    # --- Planning engine: personal ---
    monthly_spending: float = 0.0
    life_expectancy: int = 90

    # --- Planning engine: taxable account ---
    monthly_taxable_contribution: float = 0.0

    # --- Planning engine: 401k balances ---
    trad_401k_balance: float = 0.0
    roth_401k_balance: float = 0.0

    # --- Planning engine: 401k contributions ---
    monthly_trad_401k: float = 0.0
    monthly_roth_401k: float = 0.0
    employer_match_rate: float = 0.0
    employer_match_cap: float = 0.06
    annual_salary: float = 0.0
    irs_limit_401k: float = 23_500.0

    # --- Planning engine: Roth IRA ---
    roth_ira_balance: float = 0.0
    monthly_roth_ira: float = 0.0
    irs_limit_roth_ira: float = 7_000.0

    # --- Planning engine: tax rates ---
    ordinary_income_rate: float = 0.22
    capital_gains_rate: float = 0.15
    cost_basis_ratio: float = 0.50

    # --- Planning engine: post-retirement ---
    post_retirement_return: float = 0.05

    # --- Simulation mode ---
    use_cached_randoms: bool = True  # True = fast (reproducible), False = true random


# ---------------------------------------------------------------------------
# Default Monte Carlo scenario assumptions
# ---------------------------------------------------------------------------

DEFAULT_SCENARIOS: dict[str, ScenarioAssumptions] = {
    "conservative": ScenarioAssumptions(
        expected_return=0.05, volatility=0.10, label="Conservative (5% / 10% vol)"
    ),
    "expected": ScenarioAssumptions(
        expected_return=0.08, volatility=0.15, label="Expected (8% / 15% vol)"
    ),
    "optimistic": ScenarioAssumptions(
        expected_return=0.11, volatility=0.20, label="Optimistic (11% / 20% vol)"
    ),
}


# ---------------------------------------------------------------------------
# Planning engine: pure helper functions
# (ported from finance/saving_plan/saving_test.ipynb)
# ---------------------------------------------------------------------------

def _calc_required_savings(
    initial_monthly_withdrawal: float,
    retirement_age: int,
    life_expectancy: int,
    annual_return_rate: float,
    annual_inflation_rate: float,
) -> float:
    """PV of an inflation-growing monthly annuity over retirement years.

    Withdrawals start at ``initial_monthly_withdrawal`` and increase by
    ``annual_inflation_rate`` each year.  Computes the nest egg required
    at retirement to sustain this schedule until ``life_expectancy``.
    """
    years = life_expectancy - retirement_age
    monthly_rate = (1.0 + annual_return_rate) ** (1.0 / 12) - 1.0
    total_pv = 0.0
    for year in range(years):
        monthly_w = initial_monthly_withdrawal * (1.0 + annual_inflation_rate) ** year
        if monthly_rate > 0:
            pv_year = monthly_w * (1.0 - (1.0 + monthly_rate) ** -12) / monthly_rate
        else:
            pv_year = monthly_w * 12
        # Discount entire year's block back to retirement date (month 0)
        discount = (1.0 + monthly_rate) ** (-(year * 12))
        total_pv += pv_year * discount
    return total_pv


def _calc_effective_401k(
    account: Account401kParams,
) -> tuple[float, float, float]:
    """Apply IRS annual employee limit; return (trad, roth, match) per month."""
    annual_ee = (
        account.monthly_traditional_contribution + account.monthly_roth_contribution
    ) * 12
    if annual_ee > account.annual_employee_limit and annual_ee > 0:
        scale = account.annual_employee_limit / annual_ee
        eff_trad = account.monthly_traditional_contribution * scale
        eff_roth = account.monthly_roth_contribution * scale
    else:
        eff_trad = account.monthly_traditional_contribution
        eff_roth = account.monthly_roth_contribution

    monthly_salary = account.annual_salary / 12.0
    max_matchable = account.employer_match_cap * monthly_salary
    ee_for_match = min(eff_trad + eff_roth, max_matchable)
    match_monthly = ee_for_match * account.employer_match_rate
    return eff_trad, eff_roth, match_monthly


def _fv_growing_contributions(
    annual_return_rate: float,
    current_balance: float,
    initial_monthly_contribution: float,
    annual_contribution_increase_rate: float,
    years: int,
) -> float:
    """FV with annually-growing monthly contributions (taxable account model).

    Each year the monthly contribution grows by ``annual_contribution_increase_rate``.
    Uses an explicit year-loop to avoid singularities in the closed-form formula.
    """
    monthly_rate = (1.0 + annual_return_rate) ** (1.0 / 12) - 1.0
    months = 12 * years
    fv_lump = current_balance * (1.0 + monthly_rate) ** months

    fv_contributions = 0.0
    for y in range(years):
        mc = initial_monthly_contribution * (1.0 + annual_contribution_increase_rate) ** y
        if monthly_rate > 0:
            # PV of 12 end-of-month payments at this year's rate
            pv_block = mc * (1.0 - (1.0 + monthly_rate) ** -12) / monthly_rate
        else:
            pv_block = mc * 12
        # Compound this block's PV to end of projection
        years_remaining = years - y
        fv_contributions += pv_block * (1.0 + monthly_rate) ** (12 * years_remaining)

    return fv_lump + fv_contributions


def _fv_fixed_contributions(
    annual_return_rate: float,
    current_balance: float,
    monthly_contribution: float,
    years: int,
) -> float:
    """FV with fixed monthly contributions (401k model — no annual increase)."""
    months = 12 * years
    monthly_rate = (1.0 + annual_return_rate) ** (1.0 / 12) - 1.0
    fv_lump = current_balance * (1.0 + monthly_rate) ** months
    if monthly_rate > 0:
        fv_contrib = monthly_contribution * ((1.0 + monthly_rate) ** months - 1.0) / monthly_rate
    else:
        fv_contrib = monthly_contribution * months
    return fv_lump + fv_contrib


def _after_tax_equivalent(
    fv_taxable: float,
    fv_traditional: float,
    fv_roth: float,
    taxes: TaxRateParams,
) -> float:
    """Convert gross future values to spendable after-tax dollars.

    - Roth 401k: 100% tax-free.
    - Traditional 401k: withdrawals taxed at ordinary income rate.
    - Taxable account: only gains above cost basis are taxed at capital gains rate.
    """
    at_roth = fv_roth
    at_trad = fv_traditional * (1.0 - taxes.ordinary_income_rate)
    gains = fv_taxable * (1.0 - taxes.cost_basis_ratio)
    at_taxable = fv_taxable - gains * taxes.capital_gains_rate
    return at_taxable + at_trad + at_roth


def _find_required_return_rate(
    required_portfolio_value: float,
    current_taxable_balance: float,
    initial_monthly_taxable: float,
    annual_contribution_increase_rate: float,
    account: Account401kParams,
    years: int,
    taxes: TaxRateParams,
    roth_ira_balance: float = 0.0,
    eff_monthly_roth_ira: float = 0.0,
) -> float:
    """Binary search for the annual nominal return rate that meets the goal.

    Returns the minimum rate needed so the after-tax total portfolio equals
    ``required_portfolio_value`` at retirement.  Capped at 30%.
    Roth IRA FV is added to the total (tax-free, separate IRS limit applied before calling).
    """
    eff_trad, eff_roth, eff_match = _calc_effective_401k(account)
    low, high = 1e-6, 0.30

    for _ in range(100):
        mid = (low + high) / 2.0
        fv_tax = _fv_growing_contributions(
            mid, current_taxable_balance,
            initial_monthly_taxable, annual_contribution_increase_rate, years,
        )
        fv_trad = _fv_fixed_contributions(
            mid, account.traditional_balance, eff_trad + eff_match, years,
        )
        fv_roth = _fv_fixed_contributions(
            mid, account.roth_balance, eff_roth, years,
        )
        fv_roth_ira = _fv_fixed_contributions(
            mid, roth_ira_balance, eff_monthly_roth_ira, years,
        )
        # Roth IRA is tax-free — add directly to after-tax total
        total_at = _after_tax_equivalent(fv_tax, fv_trad, fv_roth, taxes) + fv_roth_ira
        if total_at >= required_portfolio_value:
            high = mid
        else:
            low = mid

    if abs(high - 0.30) < 1e-4:
        logger.warning(
            "Required return rate hit the 30%% cap — goal may be unachievable "
            "with the given contribution parameters."
        )
    return high


# ---------------------------------------------------------------------------
# Planning engine: public orchestrator
# ---------------------------------------------------------------------------

def calculate_retirement_planning(params: RetirementParams) -> PlanningResult | None:
    """Run the deterministic planning engine.

    Returns ``None`` when ``params.monthly_spending <= 0`` (planning skipped).

    Steps
    -----
    1. Inflate today's monthly spending to the retirement date.
    2. Compute the required nest egg (after-tax PV of inflation-growing annuity).
    3. Binary-search for the required annual return rate across all account types.
    4. Compute the FV breakdown at that return rate for display.
    """
    if params.monthly_spending <= 0:
        return None

    years = params.retirement_age - params.current_age
    if years <= 0:
        return None

    # Step 1: nominal monthly spending at retirement
    monthly_at_retirement = params.monthly_spending * (
        (1.0 + params.inflation_rate) ** years
    )

    # Step 2: required nest egg
    nest_egg = _calc_required_savings(
        initial_monthly_withdrawal=monthly_at_retirement,
        retirement_age=params.retirement_age,
        life_expectancy=params.life_expectancy,
        annual_return_rate=params.post_retirement_return,
        annual_inflation_rate=params.inflation_rate,
    )

    # Step 3: build sub-objects from flat params
    account = Account401kParams(
        traditional_balance=params.trad_401k_balance,
        roth_balance=params.roth_401k_balance,
        monthly_traditional_contribution=params.monthly_trad_401k,
        monthly_roth_contribution=params.monthly_roth_401k,
        employer_match_rate=params.employer_match_rate,
        employer_match_cap=params.employer_match_cap,
        annual_salary=params.annual_salary,
        annual_employee_limit=params.irs_limit_401k,
    )
    taxes = TaxRateParams(
        ordinary_income_rate=params.ordinary_income_rate,
        capital_gains_rate=params.capital_gains_rate,
        cost_basis_ratio=params.cost_basis_ratio,
    )

    # Effective Roth IRA contribution (capped at IRS annual limit)
    eff_roth_ira = min(params.monthly_roth_ira, params.irs_limit_roth_ira / 12)

    # Step 4: required return rate (includes Roth IRA in total after-tax)
    req_rate = _find_required_return_rate(
        required_portfolio_value=nest_egg,
        current_taxable_balance=params.current_value,
        initial_monthly_taxable=params.monthly_taxable_contribution,
        annual_contribution_increase_rate=params.contribution_growth_rate,
        account=account,
        years=years,
        taxes=taxes,
        roth_ira_balance=params.roth_ira_balance,
        eff_monthly_roth_ira=eff_roth_ira,
    )

    # Step 5: FV breakdown at the required rate
    eff_trad, eff_roth, eff_match = _calc_effective_401k(account)
    fv_tax = _fv_growing_contributions(
        req_rate, params.current_value,
        params.monthly_taxable_contribution,
        params.contribution_growth_rate, years,
    )
    fv_trad = _fv_fixed_contributions(
        req_rate, account.traditional_balance, eff_trad + eff_match, years,
    )
    fv_roth_val = _fv_fixed_contributions(
        req_rate, account.roth_balance, eff_roth, years,
    )
    fv_roth_ira = _fv_fixed_contributions(
        req_rate, params.roth_ira_balance, eff_roth_ira, years,
    )
    after_tax_total = _after_tax_equivalent(fv_tax, fv_trad, fv_roth_val, taxes) + fv_roth_ira

    return PlanningResult(
        monthly_spending_at_retirement=monthly_at_retirement,
        required_nest_egg=nest_egg,
        required_return_rate=req_rate,
        fv_taxable=fv_tax,
        fv_trad_401k=fv_trad,
        fv_roth_401k=fv_roth_val,
        fv_roth_ira=fv_roth_ira,
        after_tax_total=after_tax_total,
        eff_monthly_trad=eff_trad,
        eff_monthly_roth=eff_roth,
        eff_monthly_match=eff_match,
        eff_monthly_roth_ira=eff_roth_ira,
    )


# ---------------------------------------------------------------------------
# Monte Carlo engine
# ---------------------------------------------------------------------------

def _simulate(
    current_value: float,
    annual_contribution: float,
    contribution_growth_rate: float,
    horizon: int,
    expected_return: float,
    volatility: float,
    n_simulations: int,
    rng: np.random.Generator,
    std_normals: np.ndarray | None = None,
) -> np.ndarray:
    """Run Monte Carlo for one scenario using a log-normal annual return model.

    Parameters
    ----------
    std_normals : np.ndarray | None
        Pre-computed standard normal samples of shape (n_simulations, horizon).
        When provided (fast mode), avoids new random generation.

    Returns
    -------
    np.ndarray  shape (n_simulations, horizon)
        Nominal portfolio values at end of each year.
    """
    sigma = volatility
    mu = np.log(1.0 + expected_return) - 0.5 * sigma ** 2

    if std_normals is not None:
        log_returns = mu + sigma * std_normals
    else:
        log_returns = rng.normal(mu, sigma, size=(n_simulations, horizon))
    annual_factors = np.exp(log_returns)

    portfolios = np.empty((n_simulations, horizon), dtype=float)
    pv = np.full(n_simulations, current_value)

    contrib = annual_contribution
    for t in range(horizon):
        pv = pv * annual_factors[:, t] + contrib
        portfolios[:, t] = pv
        contrib *= 1.0 + contribution_growth_rate

    return portfolios


def run_retirement_projection(params: RetirementParams) -> dict[str, ScenarioResult]:
    """Compute year-by-year retirement projections for each scenario.

    The MC starting value is ``current_value + trad_401k_balance +
    roth_401k_balance`` so the fan chart reflects total wealth across all
    account types.

    Scenarios run in parallel via ``ThreadPoolExecutor``.  When
    ``params.use_cached_randoms`` is True, a module-level cache of
    pre-computed standard-normal samples is shared across all scenarios,
    giving fast reproducible results.

    Returns
    -------
    dict[str, ScenarioResult]
        Mapping of scenario name -> ScenarioResult.

    Raises
    ------
    ValueError
        If ``retirement_age`` <= ``current_age``.
    """
    if params.retirement_age <= params.current_age:
        raise ValueError(
            f"retirement_age ({params.retirement_age}) must be > "
            f"current_age ({params.current_age})"
        )

    horizon = params.retirement_age - params.current_age
    scenarios = params.scenarios or DEFAULT_SCENARIOS

    # Total wealth as MC starting point (includes all account balances)
    mc_starting_value = (
        params.current_value
        + params.trad_401k_balance
        + params.roth_401k_balance
        + params.roth_ira_balance
    )

    # Optionally load pre-computed random normals (shared across all scenarios)
    std_normals: np.ndarray | None = None
    if params.use_cached_randoms:
        std_normals = _get_cached_randoms(params.n_simulations, horizon)

    inflation_factors = (1.0 + params.inflation_rate) ** np.arange(1, horizon + 1)

    def _process_scenario(
        name: str, assumptions: ScenarioAssumptions
    ) -> tuple[str, ScenarioResult]:
        # Each thread gets its own rng; only used when std_normals is None
        rng = np.random.default_rng(params.seed)
        portfolios = _simulate(
            current_value=mc_starting_value,
            annual_contribution=params.annual_contribution,
            contribution_growth_rate=params.contribution_growth_rate,
            horizon=horizon,
            expected_return=assumptions.expected_return,
            volatility=assumptions.volatility,
            n_simulations=params.n_simulations,
            rng=rng,
            std_normals=std_normals,
        )

        real_portfolios = portfolios / inflation_factors[np.newaxis, :]

        year_projections: list[YearProjection] = []
        for t in range(horizon):
            col = real_portfolios[:, t]
            year_projections.append(
                YearProjection(
                    age=params.current_age + t + 1,
                    year_offset=t + 1,
                    p10=float(np.percentile(col, 10)),
                    p50=float(np.percentile(col, 50)),
                    p90=float(np.percentile(col, 90)),
                    mean=float(np.mean(col)),
                )
            )

        final_col = real_portfolios[:, -1]
        final_p10 = float(np.percentile(final_col, 10))
        final_p50 = float(np.percentile(final_col, 50))
        final_p90 = float(np.percentile(final_col, 90))

        readiness: float | None = None
        if params.target_retirement_value is not None:
            real_target = params.target_retirement_value / (
                (1.0 + params.inflation_rate) ** horizon
            )
            readiness = float(np.mean(final_col >= real_target))

        result = ScenarioResult(
            label=assumptions.label,
            projections=year_projections,
            final_p10=final_p10,
            final_p50=final_p50,
            final_p90=final_p90,
            readiness_score=readiness,
        )
        logger.debug("Scenario %s: median@retirement = $%.0f", name, final_p50)
        return name, result

    results: dict[str, ScenarioResult] = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {
            executor.submit(_process_scenario, name, assumptions): name
            for name, assumptions in scenarios.items()
        }
        for future in as_completed(futures):
            name, result = future.result()
            results[name] = result

    return results
