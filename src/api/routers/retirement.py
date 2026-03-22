"""
src.api.routers.retirement
==========================
POST /retirement -- run retirement planning + Monte Carlo projection.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from src.api.schemas import (
    PlanningResultSchema,
    RetirementRequest,
    RetirementResponse,
    ScenarioResultSchema,
    YearProjectionSchema,
)
from src.retirement import (
    RetirementParams,
    PlanningResult,
    calculate_retirement_planning,
    run_retirement_projection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/retirement", tags=["retirement"])


@router.post("", response_model=RetirementResponse)
def project_retirement(request: RetirementRequest) -> RetirementResponse:
    """Run retirement planning analysis (deterministic + Monte Carlo).

    The response contains two parts:
    - ``planning``: deterministic result (required nest egg, required return
      rate, 401k-aware account breakdown).  ``null`` when ``monthly_spending``
      is 0 (planning mode skipped).
    - ``scenarios``: three Monte Carlo fan charts (conservative / expected /
      optimistic) with P10/P50/P90 year-by-year projections.

    When planning mode is active and no explicit ``target_retirement_value``
    is provided, the required nest egg is used as the Monte Carlo readiness
    target automatically.
    """
    params = RetirementParams(
        # ---- Monte Carlo (existing) ----
        current_value=request.current_value,
        current_age=request.current_age,
        retirement_age=request.retirement_age,
        annual_contribution=request.annual_contribution,
        contribution_growth_rate=request.contribution_growth_rate,
        target_retirement_value=request.target_retirement_value,
        inflation_rate=request.inflation_rate,
        n_simulations=request.n_simulations,
        # ---- Planning engine ----
        monthly_spending=request.monthly_spending,
        life_expectancy=request.life_expectancy,
        monthly_taxable_contribution=request.monthly_taxable_contribution,
        trad_401k_balance=request.trad_401k_balance,
        roth_401k_balance=request.roth_401k_balance,
        monthly_trad_401k=request.monthly_trad_401k,
        monthly_roth_401k=request.monthly_roth_401k,
        employer_match_rate=request.employer_match_rate,
        employer_match_cap=request.employer_match_cap,
        annual_salary=request.annual_salary,
        irs_limit_401k=request.irs_limit_401k,
        # ---- Roth IRA ----
        roth_ira_balance=request.roth_ira_balance,
        monthly_roth_ira=request.monthly_roth_ira,
        irs_limit_roth_ira=request.irs_limit_roth_ira,
        # ---- Tax rates ----
        ordinary_income_rate=request.ordinary_income_rate,
        capital_gains_rate=request.capital_gains_rate,
        cost_basis_ratio=request.cost_basis_ratio,
        post_retirement_return=request.post_retirement_return,
        use_cached_randoms=request.use_cached_randoms,
    )

    # ── Deterministic planning pass ──────────────────────────────────────────
    planning_result: PlanningResult | None = calculate_retirement_planning(params)

    # When planning is active, use required_nest_egg as MC readiness target
    # (only if the caller did not supply an explicit target)
    if planning_result is not None and params.target_retirement_value is None:
        params.target_retirement_value = planning_result.required_nest_egg

    # ── Monte Carlo pass (skipped when run_mc=False) ──────────────────────────
    scenarios_out: dict[str, ScenarioResultSchema] = {}
    if request.run_mc:
        mc_results = run_retirement_projection(params)
    else:
        mc_results = {}

    # ── Serialise MC results ──────────────────────────────────────────────────
    for name, res in mc_results.items():
        projections = [
            YearProjectionSchema(
                age=p.age,
                year_offset=p.year_offset,
                p10=round(p.p10, 2),
                p50=round(p.p50, 2),
                p90=round(p.p90, 2),
                mean=round(p.mean, 2),
            )
            for p in res.projections
        ]
        scenarios_out[name] = ScenarioResultSchema(
            label=res.label,
            projections=projections,
            final_p10=round(res.final_p10, 2),
            final_p50=round(res.final_p50, 2),
            final_p90=round(res.final_p90, 2),
            readiness_score=(
                round(res.readiness_score, 4)
                if res.readiness_score is not None
                else None
            ),
        )

    # ── Serialise planning result ─────────────────────────────────────────────
    planning_out: PlanningResultSchema | None = None
    if planning_result is not None:
        planning_out = PlanningResultSchema(
            monthly_spending_at_retirement=round(
                planning_result.monthly_spending_at_retirement, 2
            ),
            required_nest_egg=round(planning_result.required_nest_egg, 2),
            required_return_rate=round(planning_result.required_return_rate, 6),
            fv_taxable=round(planning_result.fv_taxable, 2),
            fv_trad_401k=round(planning_result.fv_trad_401k, 2),
            fv_roth_401k=round(planning_result.fv_roth_401k, 2),
            fv_roth_ira=round(planning_result.fv_roth_ira, 2),
            after_tax_total=round(planning_result.after_tax_total, 2),
            eff_monthly_trad=round(planning_result.eff_monthly_trad, 2),
            eff_monthly_roth=round(planning_result.eff_monthly_roth, 2),
            eff_monthly_match=round(planning_result.eff_monthly_match, 2),
            eff_monthly_roth_ira=round(planning_result.eff_monthly_roth_ira, 2),
        )

    total_portfolio_value = round(
        request.current_value
        + request.trad_401k_balance
        + request.roth_401k_balance
        + request.roth_ira_balance,
        2,
    )

    return RetirementResponse(
        scenarios=scenarios_out,
        horizon_years=request.retirement_age - request.current_age,
        total_portfolio_value=total_portfolio_value,
        planning=planning_out,
    )
