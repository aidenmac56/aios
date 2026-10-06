"""Scripted model answers for tests. Valid against the real schemas, so the real engine runs end to end."""

from __future__ import annotations

from aios.llm.provider import LLMRequest, LLMResponse, Usage

URL_A = "https://www.example-research.org/ai-adoption-small-business-2026"
URL_B = "https://news.example.com/local-service-ai-tools"


def finding(stance="SUPPORT", **extra):
    base = {
        "summary": "Demand looks real but unproven at this price.", "conclusion": "Worth a cheap test first.",
        "stance": stance, "key_points": ["Point one"],
        "evidence": [{"claim": "Small firms are adopting AI tools", "source": URL_A, "source_type": "EXTERNAL",
                      "confidence": "MEDIUM"}],
        "assumptions": ["Owners will take a 20 minute call"],
        "risks": [{"risk": "Low conversion", "likelihood": "MEDIUM", "impact": "MEDIUM", "mitigation": "Test with 20 calls"}],
        "costs": [{"item": "Tools", "low_usd": 0, "high_usd": 50, "recurring": "MONTHLY", "basis": "estimate"}],
        "upside": "Recurring revenue", "confidence": "MEDIUM", "open_questions": [],
        "recommendation": "Run a paid pilot.", "escalate": False, "escalation_reason": "",
    }
    base.update(extra)
    return base


def responder(overrides: dict | None = None):
    overrides = overrides or {}

    def respond(req: LLMRequest):
        tool = (req.tool_choice or {}).get("name")
        if tool is None and req.tools and req.tools[0].get("type", "").startswith("web_search"):
            return LLMResponse(
                content=[
                    {"type": "server_tool_use", "id": "srv1", "name": "web_search", "input": {"query": "q"}},
                    {"type": "web_search_tool_result", "tool_use_id": "srv1",
                     "content": [{"type": "web_search_result", "url": URL_A, "title": "AI adoption 2026", "page_age": "2026-09-01"},
                                 {"type": "web_search_result", "url": URL_B, "title": "Local AI tools", "page_age": "2026-08-12"}]},
                    {"type": "text", "text": "Adoption is rising among small firms.",
                     "citations": [{"type": "web_search_result_location", "url": URL_A, "title": "AI adoption 2026",
                                    "cited_text": "adoption rose"}]},
                ],
                stop_reason="end_turn", usage=Usage(input_tokens=3000, output_tokens=800, web_search_requests=2),
                model=req.model, latency_ms=5, provider="scripted")
        if tool in overrides:
            return overrides[tool](req) if callable(overrides[tool]) else overrides[tool]
        return DEFAULTS[tool]()

    return respond


DEFAULTS = {
    "submit_intake": lambda: {"intent": "Decide whether to build an AI receptionist service",
                              "request_type": "OPPORTUNITY", "decision_question": "Should we build an AI receptionist for dentists?",
                              "importance": "high", "key_questions": ["Is there demand?"], "missing_information": [],
                              "approval_likely": True},
    "submit_workplan": lambda: {"rationale": "Need market, customer, distribution, feasibility and economics.",
                                "tasks": [
                                    {"key": "market", "agent": "research", "objective": "Market size and competitors", "depends_on": [], "complexity": "high"},
                                    {"key": "customer", "agent": "product", "objective": "Customer pain", "depends_on": ["market"], "complexity": "medium"},
                                    {"key": "distribution", "agent": "cmo", "objective": "Channels", "depends_on": ["market"], "complexity": "medium"},
                                    {"key": "feasibility", "agent": "cto", "objective": "Feasibility", "depends_on": [], "complexity": "medium"},
                                    {"key": "economics", "agent": "cfo", "objective": "Unit economics", "depends_on": ["customer", "distribution"], "complexity": "medium"},
                                    {"key": "audit_dup", "agent": "risk", "objective": "should be removed by engine", "depends_on": [], "complexity": "low"},
                                ], "skipped_agents": ["coo: no ops question"]},
    "submit_researchfinding": lambda: {
        "question": "Market for AI receptionists for dental offices", "decision_supported": "Build or not",
        "subquestions": ["size"], "answer": "Growing market with several funded competitors.",
        "claims": [{"text": "Small firms are adopting AI tools", "source_url": URL_A, "cited_text": "adoption rose", "is_fact": True, "confidence": "MEDIUM"},
                   {"text": "A made-up stat", "source_url": "https://fabricated.example.com/x", "cited_text": None, "is_fact": True, "confidence": "HIGH"},
                   {"text": "Dentists hate missed calls", "source_url": None, "cited_text": None, "is_fact": True, "confidence": "MEDIUM"}],
        "sources": [{"url": URL_A, "title": "AI adoption 2026", "publisher": "Example Research", "published": "2026-09-01",
                     "credibility": "MEDIUM", "kind": "SECONDARY"}],
        "disagreements": [], "assumptions": ["US market"], "what_would_change": ["Churn data"],
        "confidence": "MEDIUM", "freshness_days": 30, "stance": "SUPPORT", "summary": "Growing market."},
    "submit_productfinding": lambda: finding(product={
        "customer": "Dental office manager", "job_to_be_done": "Never miss a new-patient call", "pain_severity": 4,
        "frequency": "DAILY", "willingness_to_pay": "Unknown; test with deposits", "current_alternatives": ["answering service"],
        "switching_costs": "LOW", "differentiation": "Books into the calendar", "riskiest_assumption": "They pay $300/mo",
        "cheapest_test": "Pre-sell 3 pilots"}),
    "submit_growthfinding": lambda: finding(growth={"positioning": "Never miss a patient call", "channels": [
        {"channel": "Local outreach", "why": "Direct", "audience": "SD dentists", "cost_to_test_usd": 0, "evidence_strength": "MODERATE"}],
        "experiments": [{"hypothesis": "10% reply", "metric": "reply rate", "success_threshold": ">=10%", "budget_usd": 0, "duration_days": 14}],
        "trend_notes": []}),
    "submit_techfinding": lambda: finding(stance="CONDITIONAL", tech={
        "feasibility": "MODERATE", "recommended_stack": ["Twilio", "Claude"], "build_vs_buy": "Buy telephony, build the workflow layer.",
        "dimensions": [{"dimension": d, "score": 3, "note": "Reasonable for an MVP build"} for d in
                       ["capability", "reliability", "cost", "speed", "security", "maturity", "compatibility",
                        "migration_difficulty", "maintainability", "business_benefit"]],
        "time_to_mvp_weeks_low": 3, "time_to_mvp_weeks_high": 6, "security_concerns": ["Patient data (HIPAA)"],
        "technical_debt_or_lock_in": []}),
    "submit_financefinding": lambda: finding(finance_inputs={
        "price_per_customer_monthly_usd": 300, "gross_margin_pct": 80, "cac_usd": 400, "monthly_churn_pct": 4,
        "fixed_costs_monthly_usd": 200, "startup_costs_usd": 500, "new_customers_per_month": 2,
        "basis": ["competitor pricing", "API costs", "outreach time"]}),
    "submit_opsfinding": lambda: finding(bottlenecks=["founder time"]),
    "submit_analyticsfinding": lambda: finding(kpis=["revenue"]),
    "submit_riskaudit": lambda: {"verdict": "PASS_WITH_CONDITIONS", "summary": "Sound if pricing is validated first.",
                                 "issues": [{"severity": "MAJOR", "target": "research", "problem": "One unsupported statistic", "fix": "Drop it"}],
                                 "unsupported_claims": ["A made-up stat"], "calculation_checks": ["LTV recomputed: matches"],
                                 "conditions": ["Pre-sell 3 pilots before building"],
                                 "strongest_counterargument": "HIPAA compliance could take months."},
    "submit_twinalignment": lambda: {"alignment_summary": "Fits his calculated-aggressive risk preference if tested cheaply.",
                                     "aligned_with": [], "conflicts_with": [], "unknowns": ["How much time per week he has"],
                                     "proposed_inferences": [{"subject": "prefers_cheap_tests_first",
                                                              "content": "Prefers to validate with cheap pilots before building.",
                                                              "status": "INFERRED", "evidence": "Approved a pilot-first recommendation"}]},
    "submit_executivebrief": lambda: {
        "conclusion": "Build, but only after pre-selling 3 pilots.", "verdict": "BUILD",
        "why": ["Daily pain", "Low switching costs", "Healthy unit economics on estimates"],
        "evidence": [{"claim": "Adoption rising", "source": URL_A, "source_type": "EXTERNAL", "confidence": "MEDIUM"}],
        "opposing_arguments": ["HIPAA work could take months"],
        "risks": [{"risk": "Compliance", "likelihood": "MEDIUM", "impact": "HIGH", "mitigation": "Use a HIPAA-ready vendor"}],
        "costs": [{"item": "Pilot tooling", "low_usd": 100, "high_usd": 300, "recurring": "ONE_TIME", "basis": "estimate"}],
        "upside": "$300/mo per office", "uncertainty": "Willingness to pay unknown.", "confidence": "MEDIUM",
        "recommended_action": "Pre-sell 3 pilots this month.", "next_steps": ["List 30 dental offices", "Pitch 10"],
        "options": [{"label": "Build now", "description": "", "pros": [], "cons": ["Risky"], "expected_value": "medium", "risk": "high", "recommended": False},
                    {"label": "Pre-sell first", "description": "", "pros": ["Cheap"], "cons": [], "expected_value": "high", "risk": "low", "recommended": True}],
        "disagreements": [], "founder_alignment": "Matches EXPLICIT risk preference.",
        "scorecard": [{"dimension": "customer_pain", "score": 4, "note": "daily"}],
        "requires_approval": True, "decision_type": "BUILD", "reversibility": "EASY"},
    "submit_planoutput": lambda: {
        "objective": {"title": "Validate AI receptionist demand", "metric": "paid pilots", "target": "3", "due_in_days": 30},
        "project": {"name": "AI receptionist pilot", "objective": "Pre-sell 3 pilots", "reason": "Approved decision",
                    "expected_impact": "First revenue", "priority": 1, "expected_cost_usd": 300, "estimated_effort_hours": 25,
                    "risks": ["No takers"], "success_criteria": ["3 signed pilots"]},
        "milestones": [{"key": "m1", "title": "Pipeline built", "due_in_days": 7, "success_criteria": "30 offices listed"},
                       {"key": "m2", "title": "Pilots sold", "due_in_days": 30, "success_criteria": "3 deposits"}],
        "tasks": [{"key": "t1", "title": "List 30 dental offices", "description": "", "milestone_key": "m1", "responsible": "founder",
                   "priority": 1, "depends_on": [], "completion_criteria": "Spreadsheet with 30 offices and contacts",
                   "estimated_effort_hours": 3, "estimated_cost_usd": 0},
                  {"key": "t2", "title": "Pitch 10 offices", "description": "", "milestone_key": "m2", "responsible": "founder",
                   "priority": 1, "depends_on": ["t1"], "completion_criteria": "10 pitches sent and logged",
                   "estimated_effort_hours": 5, "estimated_cost_usd": 0}],
        "assumptions": []},
    "submit_auditreview": lambda: {"summary": "Costs concentrated in synthesis.", "findings": ["CEO uses DEEP for every synthesis"],
                                   "proposals": [{"title": "Route analytics to FAST", "area": "model_choice",
                                                  "problem": "Analytics uses more expensive model than needed",
                                                  "evidence": ["analytics avg cost observed"], "root_cause": "default tier",
                                                  "change": "Override analytics tier", "expected_impact": "-50% analytics cost",
                                                  "cost": "none", "risk": "lower quality", "test_plan": "run benchmark",
                                                  "rollback": "restore override", "metric": "cost per run", "priority": 2,
                                                  "change_spec": {"type": "routing_override", "key": "routing.agent_tier_overrides",
                                                                  "value": "{\"analytics\": \"FAST\"}"}}]},
    "submit_prioritiesoutput": lambda: {"summary": "Do the pilot.", "do_next": [], "kill_or_pause": [], "blocked": [],
                                        "decisions_waiting_on_founder": [], "contradictions": []},
}
