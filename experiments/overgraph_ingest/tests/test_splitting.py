from overgraph_ingest.segmentation.splitting import covering_ranges


def test_covering_ranges_concatenate_to_source() -> None:
    text = "Första stycket.\n\nAndra stycket är längre och behöver delas. Tredje meningen."
    ranges = covering_ranges(text, target=24, max_chars=40)
    assert "".join(text[start:end] for start, end in ranges) == text
    assert ranges[0][0] == 0
    assert ranges[-1][1] == len(text)


def test_hard_split_covers_long_token() -> None:
    text = "x" * 50
    ranges = covering_ranges(text, target=10, max_chars=10)
    assert [text[start:end] for start, end in ranges] == ["x" * 10] * 5
