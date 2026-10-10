"""LangGraph agent that writes a "why this site" explanation and checks it against the facts.

Flow: draft -> verify -> (done | draft again with feedback | template fallback).
The check rejects any number that is not in the fact sheet, so the text cannot invent figures.
"""
from typing import Callable, Optional, TypedDict

from langgraph.graph import END, StateGraph

from .facts import template_explanation, unsupported_numbers

SYSTEM_PROMPT = (
    "You write short site assessments for battery storage developers. Use only the facts "
    "provided. Write 3 or 4 plain sentences. Copy every number exactly as written in the "
    "facts and do not introduce any other digits. Do not claim anything about land, "
    "permitting or costs, because that data is not available."
)


class ExplainState(TypedDict, total=False):
    facts: dict
    draft: str
    attempts: int
    problems: list
    explanation: str
    mode: str          # "llm", "template", or "template_fallback"
    verified: bool
    reason: str


def build_prompt(facts: dict, problems: list) -> str:
    prompt = "Facts:\n" + "\n".join(f"- {line}" for line in facts["lines"])
    if problems:
        prompt += (
            "\n\nYour previous draft used numbers that are not in the facts: "
            + ", ".join(problems)
            + ". Rewrite it using only numbers from the facts."
        )
    return prompt


def build_explainer(llm_call: Optional[Callable[[str, str], str]], max_attempts: int = 2):
    """Compile the graph. llm_call(system, prompt) returns text; None means template-only mode."""

    def draft_node(state: ExplainState) -> ExplainState:
        facts = state["facts"]
        if llm_call is None:
            return {"explanation": template_explanation(facts), "mode": "template", "verified": True}
        attempts = state.get("attempts", 0) + 1
        try:
            text = llm_call(SYSTEM_PROMPT, build_prompt(facts, state.get("problems", []))).strip()
        except Exception as error:  # network, auth, rate limit: fall back instead of failing the request
            return {"attempts": attempts, "mode": "template_fallback", "reason": f"LLM call failed: {error}",
                    "explanation": template_explanation(facts), "verified": True}
        return {"draft": text, "attempts": attempts}

    def verify_node(state: ExplainState) -> ExplainState:
        problems = unsupported_numbers(state["draft"], state["facts"])
        if not problems:
            return {"problems": [], "verified": True, "explanation": state["draft"], "mode": "llm"}
        return {"problems": problems, "verified": False}

    def fallback_node(state: ExplainState) -> ExplainState:
        return {"explanation": template_explanation(state["facts"]), "mode": "template_fallback",
                "reason": f"Draft used unsupported numbers: {', '.join(state['problems'])}", "verified": True}

    def after_draft(state: ExplainState) -> str:
        return "done" if state.get("explanation") else "verify"

    def after_verify(state: ExplainState) -> str:
        if state["verified"]:
            return "done"
        return "retry" if state["attempts"] < max_attempts else "fallback"

    graph = StateGraph(ExplainState)
    graph.add_node("draft", draft_node)
    graph.add_node("verify", verify_node)
    graph.add_node("fallback", fallback_node)
    graph.set_entry_point("draft")
    graph.add_conditional_edges("draft", after_draft, {"done": END, "verify": "verify"})
    graph.add_conditional_edges("verify", after_verify, {"done": END, "retry": "draft", "fallback": "fallback"})
    graph.add_edge("fallback", END)
    return graph.compile()
