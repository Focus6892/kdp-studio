from kdp_studio.interior.qa import NUDITY_LABELS, PEOPLE_LABELS, SAFE_LABELS, TEXT_LABELS, decide_content
from kdp_studio.schema import QAOptions


def test_content_decision_thresholds():
    opts = QAOptions()
    flowers = {k: 0.0 for k in PEOPLE_LABELS + NUDITY_LABELS + TEXT_LABELS}
    flowers.update({"a line drawing of flowers": 0.8, "a decorative pattern": 0.2})
    assert decide_content(flowers, opts) == []
    person = dict(flowers, **{"a line drawing of flowers": 0.4, "a drawing of a woman": 0.3, "a portrait of a human face": 0.2})
    assert any("person" in r for r in decide_content(person, opts))
    nude = dict(flowers, **{"a line drawing of flowers": 0.7, "a drawing of a naked person": 0.2})
    assert any("nudity" in r for r in decide_content(nude, opts))
    text = dict(flowers, **{"a line drawing of flowers": 0.3, "a page of text": 0.6})
    assert any("text" in r for r in decide_content(text, opts))
    strict = QAOptions(people_threshold=0.1)
    assert decide_content(dict(flowers, **{"a drawing of a man": 0.12}), strict)
