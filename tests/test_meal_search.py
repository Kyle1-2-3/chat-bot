"""Menu items carry a Google image-search link so students can see unfamiliar
dishes (e.g. "Banh Mi Vietnamese Pork Roll ...") instead of just a name."""
import urllib.parse

import app as appmod
import set_up_db


def seed(tmp_path, monkeypatch):
    db = tmp_path / "school.db"
    monkeypatch.setattr(set_up_db, "DB_PATH", str(db))
    monkeypatch.chdir(tmp_path)
    set_up_db.init_db()
    monkeypatch.setattr(appmod, "DB_PATH", str(db))
    return db


def test_single_dish_gets_image_search_url():
    items = appmod.menu_search_items("Ravioli")
    assert len(items) == 1
    assert items[0]["name"] == "Ravioli"
    assert items[0]["search_url"] == "https://www.google.com/search?tbm=isch&q=Ravioli"


def test_multiline_menu_splits_into_one_item_per_dish():
    content = (
        "Banh Mi Vietnamese Pork Roll with Cucumber, Carrot & Sriracha Mayo\n"
        "Sea Salt Edamame Beans"
    )
    items = appmod.menu_search_items(content)
    assert [i["name"] for i in items] == [
        "Banh Mi Vietnamese Pork Roll with Cucumber, Carrot & Sriracha Mayo",
        "Sea Salt Edamame Beans",
    ]


def test_special_characters_are_url_encoded():
    # Spaces, &, and / must be encoded so the link is valid and safe to embed.
    items = appmod.menu_search_items("Jalapeno/Red Pepper & Mayo")
    q = items[0]["search_url"].split("&q=", 1)[1]
    assert urllib.parse.unquote_plus(q) == "Jalapeno/Red Pepper & Mayo"
    assert " " not in items[0]["search_url"]
    assert "/Red" not in q  # the slash inside the dish name is encoded


def test_blank_and_none_yield_no_items():
    assert appmod.menu_search_items("") == []
    assert appmod.menu_search_items(None) == []
    # Blank lines (e.g. Sunday brunch's two halves joined by "\n\n") are dropped.
    assert [i["name"] for i in appmod.menu_search_items("A\n\n\nB")] == ["A", "B"]


def test_meal_result_rows_include_menu_items(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    result = appmod.build_result_from_classification(
        {"intent": "MEAL", "day_ref": "Monday", "meal_type": "LUNCH"}, "monday lunch"
    )
    assert result["type"] == "MEAL"
    assert result["rows"], "expected seeded Monday lunch rows"
    for row in result["rows"]:
        assert row["menu_items"] == appmod.menu_search_items(row["menu_content"])
        assert all(i["search_url"].startswith("https://www.google.com/search") for i in row["menu_items"])


def test_meals_day_rows_include_menu_items(tmp_path, monkeypatch):
    seed(tmp_path, monkeypatch)
    result = appmod.build_result_from_classification(
        {"intent": "MEALS_DAY", "day_ref": "Monday"}, "monday meals"
    )
    assert result["type"] == "MEALS_DAY"
    assert result["rows"]
    assert all("menu_items" in row for row in result["rows"])
