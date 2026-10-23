import pytest

from kdp_studio import specs
from kdp_studio.cover.geometry import cover_geometry
from kdp_studio.pricing import min_list_price, printing_cost, royalty, royalty_rate


def test_spine_width_white_paper():
    assert specs.spine_width_in(66, "white_bw") == pytest.approx(66 * 0.002252)
    assert specs.spine_width_in(100, "cream_bw") == pytest.approx(0.25)


def test_groundwood_has_no_spine_factor():
    with pytest.raises(ValueError):
        specs.spine_width_in(100, "groundwood_bw")


def test_cover_geometry_8_5x11_66_pages():
    geo = cover_geometry("8.5x11", 66, "white_bw")
    assert geo.width_in == pytest.approx(0.25 + 17.0 + 66 * 0.002252)
    assert geo.height_in == pytest.approx(11.25)
    assert geo.width_px == round(geo.width_in * 300)
    assert geo.front.x == pytest.approx(0.125 + 8.5 + geo.spine_in)
    assert not geo.spine_text_allowed
    # barcode box sits inside the back cover trim, 0.25" from the right/bottom edges
    assert geo.barcode.x1 == pytest.approx(geo.back.x1 - 0.25)
    assert geo.barcode.y1 == pytest.approx(geo.back.y1 - 0.25)
    assert geo.barcode.w == 2.0 and geo.barcode.h == 1.2


def test_spine_text_allowed_from_79_pages():
    assert cover_geometry("6x9", 78, "white_bw").spine_text_allowed is False
    assert cover_geometry("6x9", 80, "white_bw").spine_text_allowed is True


def test_page_ranges():
    assert specs.page_range("8.5x11", "white_bw") == (24, 590)
    assert specs.page_range("6x9", "cream_bw") == (24, 776)
    with pytest.raises(ValueError):
        specs.page_range("8.27x11.69", "standard_color")


def test_margins():
    assert specs.gutter_in(66) == 0.375
    assert specs.gutter_in(200) == 0.5
    assert specs.page_size_in(specs.get_trim("8.5x11"), True) == (8.625, 11.25)
    assert specs.page_size_in(specs.get_trim("6x9"), False) == (6.0, 9.0)


def test_printing_cost_tables():
    assert printing_cost("8.5x11", "white_bw", 64) == 2.84        # large trim, fixed tier
    assert printing_cost("6x9", "white_bw", 300) == 4.60          # 1.00 + 300 * 0.012
    assert printing_cost("6x9", "premium_color", 100) == 7.50     # 1.00 + 100 * 0.065
    assert printing_cost("8.5x11", "standard_color", 100) == pytest.approx(5.02)


def test_royalty_tiers_amazon_com():
    assert royalty_rate(9.99) == 0.60
    assert royalty_rate(9.98) == 0.50
    assert royalty(9.99, "8.5x11", "white_bw", 64) == pytest.approx(3.15, abs=0.01)
    assert royalty(7.99, "8.5x11", "white_bw", 64) == pytest.approx(1.16, abs=0.01)
    assert royalty(12.99, "6x9", "white_bw", 300) == pytest.approx(3.19, abs=0.01)


def test_min_list_price_crosses_tier_boundary():
    assert min_list_price("8.5x11", "white_bw", 64) == pytest.approx(5.68)
    assert min_list_price("6x9", "white_bw", 300) == pytest.approx(9.20)
    # cost 5.51: 50% tier would need $11.02 (above $9.99), so the 60% tier applies -> $9.99
    assert min_list_price("6x9", "white_bw", 376) == pytest.approx(9.99)
