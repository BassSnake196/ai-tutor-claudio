from app.ai.router import RouteKind, RoutingInput, RuleBasedRouter


def test_routes_simple_question_to_local_model() -> None:
    decision = RuleBasedRouter().decide(RoutingInput(prompt="Explica qué es una variable."))

    assert decision.route is RouteKind.LOCAL
    assert decision.intent == "general_question"


def test_routes_pedagogical_generation_to_cloud() -> None:
    decision = RuleBasedRouter().decide(RoutingInput(prompt="Crea un temario de álgebra para preparatoria."))

    assert decision.route is RouteKind.CLOUD


def test_routes_source_question_to_retrieval() -> None:
    decision = RuleBasedRouter().decide(RoutingInput(prompt="Resume este documento.", requires_sources=True))

    assert decision.route is RouteKind.RETRIEVAL
