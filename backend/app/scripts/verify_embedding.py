from app.rag.embeddings import LangChainEmbeddingService


def main() -> None:
    vector = LangChainEmbeddingService().embed_query("劳动合同中的工资支付规定")
    print(f"Embedding verification passed: dimension={len(vector)}")


if __name__ == "__main__":
    main()
