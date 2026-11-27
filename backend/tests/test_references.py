import pytest

from generationstation.runtimes import CatalogError, parse_catalog

SCORE = {"metric": "Intelligence Index v5 (Artificial Analysis)", "score": 60.1, "source": "https://example.com/aa", "as_of": "2026-11-26"}


def test_reference_models_are_read_with_their_scores():
    catalog = parse_catalog({"runtimes": {}, "references": [{"name": "Claude Sonnet", "scores": [SCORE, {**SCORE, "metric": "GPQA Diamond", "score": 88.1}]}]})
    (reference,) = catalog.references
    assert reference.name == "Claude Sonnet" and reference.workload == "text"
    assert [score.metric for score in reference.scores] == ["Intelligence Index v5 (Artificial Analysis)", "GPQA Diamond"]
    assert not reference.scores[0].estimated


def test_a_catalog_without_references_has_none():
    assert parse_catalog({"runtimes": {}}).references == []


@pytest.mark.parametrize("references", [
    [{"name": "A", "scores": []}],  # no scores
    [{"name": "A", "scores": [SCORE, SCORE]}],  # one metric twice
    [{"name": "A", "scores": [{**SCORE, "source": "http://insecure"}]}],  # not https
    [{"name": "", "scores": [SCORE]}],
    [{"name": "A", "scores": [SCORE], "extra": 1}],
    "not a list",
])
def test_bad_references_are_refused(references):
    with pytest.raises(CatalogError):
        parse_catalog({"runtimes": {}, "references": references})
