from app.ai.router import RouteDecision, RuleBasedRouter, RoutingInput


class RouterAgent:
    def __init__(self, router: RuleBasedRouter | None = None) -> None:
        self._router = router or RuleBasedRouter()

    def route(self, prompt: str, *, requires_sources: bool) -> RouteDecision:
        return self._router.decide(RoutingInput(prompt=prompt, requires_sources=requires_sources))
