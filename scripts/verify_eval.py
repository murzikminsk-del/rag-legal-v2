import importlib, sys

def check(pkg, label=None):
    label = label or pkg
    try:
        importlib.import_module(pkg)
        print(f"  OK  {label}")
    except ImportError as e:
        print(f"  FAIL {label}: {e}")

print("=== eval ===")
check("ragas")
check("ragas.metrics.collections", "ragas.metrics.collections")
check("anthropic")
check("pandas")
check("phoenix", "arize-phoenix")

print("=== tracing ===")
check("openinference.instrumentation.llama_index", "openinference-llama-index")
check("opentelemetry.sdk", "opentelemetry-sdk")
check("opentelemetry.exporter.otlp", "opentelemetry-exporter-otlp")

print("done")