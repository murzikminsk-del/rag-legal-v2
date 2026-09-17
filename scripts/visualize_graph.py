# scripts/visualize_graph.py
from pathlib import Path

DOCS = Path(__file__).parent.parent / "docs"
DOCS.mkdir(exist_ok=True)


def save_mmd(graph, name: str) -> None:
    mmd = graph.get_graph().draw_mermaid()
    path = DOCS / f"{name}.mmd"
    path.write_text(mmd, encoding="utf-8")
    print(f"Сохранено: {path}")

    try:
        png_bytes = graph.get_graph().draw_mermaid_png()
        png_path = DOCS / f"{name}.png"
        png_path.write_bytes(png_bytes)
        print(f"Сохранено: {png_path}")
    except Exception as exc:
        print(f"PNG не создан (pyppeteer/playwright не установлен): {exc}")


if __name__ == "__main__":
    from app.services.agent_graph import custom_graph
    save_mmd(custom_graph, "agent-graph-custom")

    try:
        from app.services.agent_graph import prebuilt_graph
        save_mmd(prebuilt_graph, "agent-graph-prebuilt")
    except ImportError:
        print("prebuilt_graph не найден — пропущено (добавить после задачи 6)")