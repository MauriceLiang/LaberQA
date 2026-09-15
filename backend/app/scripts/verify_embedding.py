from app.services.embedding import EmbeddingService


def main() -> None:
    vector = EmbeddingService().embed_query("劳动合同中的工资支付规定")
    print(f"Embedding verification passed: dimension={len(vector)}")


if __name__ == "__main__":
    main()
