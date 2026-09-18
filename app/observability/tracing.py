import os

from openinference.instrumentation.openai import OpenAIInstrumentor
from phoenix.otel import register


def setup_tracing(settings=None) -> None:
    base = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "http://localhost:6006")
    endpoint = f"{base.rstrip('/')}/v1/traces"
    tracer_provider = register(project_name="rag-legal-v2", endpoint=endpoint)
    OpenAIInstrumentor().instrument(tracer_provider=tracer_provider)
    try:
        from openinference.instrumentation.llama_index import LlamaIndexInstrumentor
        LlamaIndexInstrumentor().instrument(tracer_provider=tracer_provider)
    except Exception:
        pass  # версия несовместима с llama-index 0.14 — трейсим через OpenAI