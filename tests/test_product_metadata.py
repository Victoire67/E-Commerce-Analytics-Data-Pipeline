"""JSONB metadata queries and updates."""

from decimal import Decimal

import pytest

from ecommerce_pipeline import crud
from ecommerce_pipeline import product_metadata as pm

pytestmark = pytest.mark.usefixtures("clean_db")


@pytest.fixture
def catalogue():
    tee = crud.add_product(
        "CLO-1",
        "Tee",
        "Clothing",
        Decimal("10"),
        5,
        {"colors": ["red", "blue"], "sizes": ["M", "L"], "material": "cotton"},
    )
    hoodie = crud.add_product(
        "CLO-2",
        "Hoodie",
        "Clothing",
        Decimal("40"),
        5,
        {"colors": ["black"], "sizes": ["L"], "material": "polyester"},
    )
    phones = crud.add_product(
        "ELE-1",
        "Headphones",
        "Electronics",
        Decimal("99"),
        5,
        {"brand": "Voltix", "specs": {"wireless": True}, "colors": ["red"]},
    )
    return {"tee": tee, "hoodie": hoodie, "phones": phones}


def ids(rows):
    return [row["product_id"] for row in rows]


def test_containment_matches_array_members(catalogue):
    red = pm.find_products_by_metadata({"colors": ["red"]})

    assert ids(red) == [catalogue["tee"], catalogue["phones"]]


def test_containment_requires_every_criterion(catalogue):
    rows = pm.find_products_by_metadata({"colors": ["red"], "sizes": ["L"]})

    assert ids(rows) == [catalogue["tee"]]


def test_containment_on_nested_object(catalogue):
    rows = pm.find_products_by_metadata({"specs": {"wireless": True}})

    assert ids(rows) == [catalogue["phones"]]
    assert rows[0]["category"] == "Electronics"


def test_any_key_operator(catalogue):
    assert ids(pm.find_products_with_any_key(["brand", "warranty_months"])) == [catalogue["phones"]]


def test_count_by_attribute(catalogue):
    assert pm.count_products_by_attribute("material") == [
        {"value": "cotton", "products": 1},
        {"value": "polyester", "products": 1},
    ]


def test_available_colors_unnests_arrays(catalogue):
    colors = {row["color"]: row["products"] for row in pm.available_colors()}

    assert colors == {"red": 2, "blue": 1, "black": 1}


def test_merge_metadata_adds_and_overwrites_keys(catalogue):
    merged = pm.merge_product_metadata(catalogue["hoodie"], {"material": "wool", "hooded": True})

    assert merged == {"colors": ["black"], "sizes": ["L"], "material": "wool", "hooded": True}


def test_remove_metadata_key(catalogue):
    assert "material" not in pm.remove_metadata_key(catalogue["tee"], "material")


def test_metadata_updates_on_missing_product_return_none():
    assert pm.merge_product_metadata(999, {"a": 1}) is None


def test_injection_in_metadata_value_is_just_data(catalogue):
    assert pm.find_products_by_metadata({"material": "x' OR '1'='1"}) == []
