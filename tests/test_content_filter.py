from kdp_studio.interior.qa import NUDITY_QUERIES, PEOPLE_QUERIES, decide_content
from kdp_studio.schema import QAOptions


def test_content_decision_thresholds():
    opts = QAOptions()
    flowers = {q: 0.0 for q in PEOPLE_QUERIES + NUDITY_QUERIES}
    flowers["a portrait of a woman with flowers in her hair"] = 0.21  # highest score seen on a flowers-only page
    assert decide_content(flowers, opts) == []
    person = dict(flowers, **{"a human face": 0.33})  # lowest score seen on a page with a person
    assert any("person" in r for r in decide_content(person, opts))
    nude = dict(flowers, **{"a naked body": 0.14})
    assert any("nudity" in r for r in decide_content(nude, opts))
    strict = QAOptions(people_threshold=0.1)
    assert decide_content(dict(flowers, **{"a girl": 0.12}), strict)
    assert decide_content({}, opts) == []
