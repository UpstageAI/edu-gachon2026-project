from app.rag.regulations import REGULATIONS


def test_regulations_is_not_empty():
    assert len(REGULATIONS) > 0


def test_regulations_keys_are_sequential_ints():
    keys = sorted(REGULATIONS.keys())
    assert keys == list(range(1, len(keys) + 1))


def test_regulations_values_are_nonempty_strings():
    for regulation_id, text in REGULATIONS.items():
        assert isinstance(text, str)
        assert text.strip(), f"제{regulation_id}조 내용이 비어 있습니다."
