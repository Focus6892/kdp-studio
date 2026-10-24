import json
from pathlib import Path

import pytest

from kdp_studio.interior.generate import ProviderError, make_provider
from kdp_studio.interior.vector import catmull_rom, cubic_bezier, flatten, load_specs, render_spec, validate_spec
from kdp_studio.schema import ImageSource

ROOT = Path(__file__).resolve().parents[1]
DRAWINGS = ROOT / "examples" / "bold-easy-flowers" / "drawings"


def _ink(img) -> float:
    return 1.0 - sum(img.histogram()[200:]) / (img.width * img.height)


def test_sample_specs_render_as_bold_line_art():
    specs = load_specs(DRAWINGS)
    assert len(specs) >= 3
    for path, spec in specs:
        assert validate_spec(spec) == [], path.name
        img = render_spec(spec, (1000, 1500))
        assert img.mode == "L" and img.size == (1000, 1500)
        assert 0.03 < _ink(img) < 0.30, f"{path.name}: ink {_ink(img):.3f}"  # same band the QA accepts
        hist = img.histogram()
        assert sum(hist[1:200]) / (img.width * img.height) < 0.01  # pure black and white, no gray smear


def test_spec_scales_to_print_resolution_and_catches_errors(tmp_path):
    spec = {"canvas": [1000, 1500], "stroke": 10, "shapes": [{"type": "circle", "c": [500, 750], "r": 400}, {"type": "repeat", "count": 6, "center": [500, 750], "shapes": [{"type": "dot", "c": [500, 400], "r": 20}]}]}
    small, big = render_spec(spec, (500, 750)), render_spec(spec, (2550, 3300))
    assert abs(_ink(small) - _ink(big)) < 0.02  # stroke scales with the page
    assert validate_spec({"shapes": [{"type": "bezier", "points": [[0, 0], [1, 1]]}]})[0].startswith("shape error")
    assert validate_spec({"shapes": []}) == ["spec has no shapes"]
    assert len(catmull_rom([(0, 0), (10, 10), (20, 0)])) > 3 and len(cubic_bezier((0, 0), (0, 1), (1, 1), (1, 0))) == 41
    kinds = {k for k, _, _ in flatten([{"type": "mirror", "axis_x": 500, "shapes": [{"type": "line", "points": [[100, 100], [200, 200]]}]}])}
    assert kinds == {"poly"}
    folder = tmp_path / "d"
    folder.mkdir()
    (folder / "a.json").write_text(json.dumps(spec), encoding="utf-8")
    (folder / "b.json").write_text(json.dumps({"shapes": [{"type": "nope"}]}), encoding="utf-8")
    prov = make_provider(ImageSource(provider="spec", path="d"), tmp_path)
    assert prov.generate("ignored", 0, 0, tmp_path / "out0.png", (400, 600)).is_file()
    with pytest.raises(ProviderError):
        prov.generate("ignored", 1, 0, tmp_path / "out1.png", (400, 600))
