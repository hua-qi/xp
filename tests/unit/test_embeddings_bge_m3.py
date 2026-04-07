def test_local_bge_m3_default_model_name():
    from src.embeddings import LocalBGEProvider
    p = LocalBGEProvider()
    assert p._model_name == "BAAI/bge-m3"


def test_embedding_dim_constant():
    from src.embeddings import EMBEDDING_DIM
    assert EMBEDDING_DIM == 1024
