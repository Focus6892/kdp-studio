from kdp_studio.interior.qa import NUDITY_QUERIES, PEOPLE_QUERIES, TEXT_QUERIES, decide_content
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


def test_text_and_signatures_are_rejected_by_the_watermark_score():
    from kdp_studio.schema import QAOptions

    opts = QAOptions()
    clean = {q: 0.02 for q in PEOPLE_QUERIES + NUDITY_QUERIES + TEXT_QUERIES}
    assert decide_content(clean, opts) == []
    signed = dict(clean, **{"a watermark": 0.46})  # measured on a page with 'Cdoorine Llloddna' written along the bottom
    assert any("text or a signature" in r for r in decide_content(signed, opts))
    assert decide_content(dict(clean, **{"a watermark": 0.10}), opts) == []  # the highest score among the 26 clean pages
    assert decide_content(signed, QAOptions(reject_text=False)) == []

