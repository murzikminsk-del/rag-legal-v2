"""Генерация golden dataset через RAGAS TestsetGenerator (группа eval)."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from llama_index.core import SimpleDirectoryReader
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI as OpenAILLM
from ragas.testset import TestsetGenerator
from ragas.testset.transforms.splitters.headline import HeadlineSplitter as _HS

from app.core.config import get_settings

_orig_split = _HS.split


async def _safe_split(self, node):
    try:
        return await _orig_split(self, node)
    except ValueError:
        return [], []


_HS.split = _safe_split


def main() -> None:
    parser = argparse.ArgumentParser(description="RAGAS TestsetGenerator")
    parser.add_argument("--size", type=int, default=30)
    parser.add_argument("--out", default="tests/eval/golden_dataset_raw.csv")
    args = parser.parse_args()

    settings = get_settings()
    docs = SimpleDirectoryReader(
        str(settings.rag_data_dir), recursive=True
    ).load_data()
    print(f"Loaded {len(docs)} documents")

    generator = TestsetGenerator.from_llama_index(
        llm=OpenAILLM(
            model="gpt-4o-mini",
            api_key=settings.llm.openai_api_key.get_secret_value(),
        ),
        embedding_model=OpenAIEmbedding(model=settings.embedding_model),
    )
    testset = generator.generate_with_llamaindex_docs(docs, testset_size=args.size)

    df = testset.to_pandas()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False)
    print(df[["user_input", "reference", "reference_contexts"]].head())
    print(f"\nСохранено: {out} ({len(df)} строк). Дальше — ручная вычитка.")

# import networkx as nx
# import matplotlib
# matplotlib.use("Agg")  # без GUI, сохраняем в файл
# import matplotlib.pyplot as plt

# kg = generator.knowledge_graph
# G = nx.Graph()

# for node in kg.nodes:
#     label = node.properties.get("title", str(node.id)[:20])
#     G.add_node(node.id, label=label)

# for rel in kg.relationships:
#     G.add_edge(rel.source.id, rel.target.id, label=rel.type)

# plt.figure(figsize=(18, 12))
# pos = nx.spring_layout(G, seed=42)
# nx.draw_networkx(G, pos, labels=nx.get_node_attributes(G, "label"),
#                  node_size=800, font_size=6, arrows=False)
# plt.savefig("tests/eval/knowledge_graph.png", dpi=150, bbox_inches="tight")
# print("Граф сохранён: tests/eval/knowledge_graph.png")

if __name__ == "__main__":
    main()