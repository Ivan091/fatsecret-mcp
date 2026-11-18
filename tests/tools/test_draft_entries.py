"""Drafts through MCP: proposed entries and totals without writing to the Food Diary."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Any

import pytest
from mcp import Client

from fatsecret_mcp.config.models import Household, User
from fatsecret_mcp.domain.models import Food, Meal, Nutrition, Serving
from fatsecret_mcp.fatsecret.budget import daily_budget
from fatsecret_mcp.fatsecret.food_cache import FoodCache
from fatsecret_mcp.server import build_server
from tests.conftest import FakeClock
from tests.fatsecret.fake import FakeFatSecret, food_entry

pytestmark = pytest.mark.anyio
Connect = Callable[[str], Client]
TODAY = date(
    year=2026,
    month=10,
    day=14,
)
YESTERDAY = date(
    year=2026,
    month=10,
    day=13,
)


@pytest.fixture
def rice(fatsecret: FakeFatSecret) -> Food:
    serving = Serving(
        id="rice-100g",
        description="100 g",
        metric_amount=100,
        metric_unit="g",
        number_of_units=100,
        nutrition=Nutrition(
            kcal=130,
            protein=2.7,
            fat=0.3,
            carbohydrate=28.2,
        ),
    )
    food = Food(
        id="rice",
        name="Cooked Rice",
        brand=None,
        servings=[serving],
    )

    fatsecret.add_food(food)

    return food


def kaiser_roll() -> Food:
    """A US catalog Food counted in rolls of a known weight, which also has a Serving in grams."""
    roll = Serving(
        id="roll-1",
        description='1 roll (3-1/2" dia)',
        metric_amount=57,
        metric_unit="g",
        number_of_units=1,
        nutrition=Nutrition(
            kcal=167,
            protein=5.6,
            fat=2.5,
            carbohydrate=30,
        ),
    )
    hundred_grams = Serving(
        id="roll-100g",
        description="100 g",
        metric_amount=100,
        metric_unit="g",
        number_of_units=100,
        nutrition=Nutrition(
            kcal=293,
            protein=9.9,
            fat=4.3,
            carbohydrate=52.7,
        ),
    )

    return Food(
        id="kaiser-roll",
        name="Hard Rolls (Includes Kaiser)",
        brand=None,
        servings=[roll, hundred_grams],
    )


@pytest.fixture
def nutella(fatsecret: FakeFatSecret) -> Food:
    """A branded US catalog Food with a weight but no Serving in grams, as brands usually have."""
    serving = Serving(
        id="nutella-2-tbsp",
        description="2 tbsp",
        metric_amount=37,
        metric_unit="g",
        number_of_units=1,
        nutrition=Nutrition(
            kcal=200,
            protein=2,
            fat=11,
            carbohydrate=22,
        ),
    )
    food = Food(
        id="nutella",
        name="Hazelnut Spread",
        brand="Nutella",
        servings=[serving],
    )

    fatsecret.add_food(food)

    return food


def meal_for(items: list[dict[str, Any]], meal: str | None) -> str | None:
    """The given meal, or lunch when the items add new Food Entries and none was given."""
    if meal is not None or all("change" in item for item in items):
        return meal

    return "lunch"


async def draft(
    client: Client,
    items: list[dict[str, Any]],
    *,
    meal: str | None = None,
    diary_day: str | None = None,
) -> dict[str, Any]:
    arguments = {
        "items": items,
        "meal": meal_for(items, meal),
        "diary_day": diary_day,
    }
    result = await client.call_tool("draft_entries", arguments)

    assert not result.is_error, result.content
    assert result.structured_content is not None

    return result.structured_content


async def test_a_draft_shows_amount_assumption_totals_and_the_day_after_without_writing(
    connect: Connect, fatsecret: FakeFatSecret, household: Household, rice: Food
) -> None:
    eaten = food_entry(
        name="Breakfast",
        meal=Meal.BREAKFAST,
        diary_day=TODAY,
        kcal=2300,
        protein=150,
        fat=75,
        carbohydrate=250,
    )
    items = [
        {
            "food_id": rice.id,
            "serving_id": "rice-100g",
            "number_of_units": 150,
            "assumption": "A bowl ≈ 150 g",
        },
        {"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 50},
    ]

    fatsecret.add_food_entry(household.user("jakub").fatsecret, eaten)

    async with connect("jakub") as client:
        before = await client.call_tool("get_diary_day", {})
        proposed = await draft(client, items)
        after = await client.call_tool("get_diary_day", {})

    assert before.structured_content == after.structured_content
    assert proposed["meal"] == "lunch"
    assert proposed["diary_day"] == "2026-10-14"
    assert proposed["expires_at"] == "2026-10-14T10:30:00Z"
    assert proposed["items"][0] == {
        "food_id": "rice",
        "serving_id": "rice-100g",
        "name": "Cooked Rice",
        "serving": "100 g",
        "number_of_units": 150,
        "amount": "150 g",
        "kcal": 195,
        "protein": 4.1,
        "fat": 0.4,
        "carbohydrate": 42.3,
        "assumption": "A bowl ≈ 150 g",
        "catalog_name": None,
        "stand_in": None,
        "repeated_from": None,
    }
    assert proposed["items"][1]["assumption"] is None
    assert proposed["totals"] == {"kcal": 260, "protein": 5.4, "fat": 0.6, "carbohydrate": 56.4}
    assert proposed["day_after"] == {
        "consumed": {"kcal": 2560, "protein": 155.4, "fat": 75.6, "carbohydrate": 306.4},
        "daily_targets": {"kcal": 2500, "protein": 160, "fat": 80, "carbohydrate": 280},
        "remaining": {"kcal": -60, "protein": 4.6, "fat": 4.4, "carbohydrate": -26.4},
    }


async def test_a_food_item_named_in_the_users_words_is_drafted_and_saved_under_that_name(
    connect: Connect, fatsecret: FakeFatSecret, household: Household, rice: Food
) -> None:
    named = {
        "food_id": rice.id,
        "serving_id": "rice-100g",
        "number_of_units": 150,
        "food_entry_name": "Ryż",
    }
    named_as_in_the_catalog = {
        "food_id": rice.id,
        "serving_id": "rice-100g",
        "number_of_units": 50,
        "food_entry_name": "Cooked Rice",
    }

    async with connect("jakub") as client:
        proposed = await draft(client, [named, named_as_in_the_catalog])
        confirmed = await client.call_tool("confirm_draft", {"draft_id": proposed["draft_id"]})

    entries = await fatsecret.list_food_entries(household.user("jakub").fatsecret, TODAY)
    names = [(item["name"], item["catalog_name"]) for item in proposed["items"]]
    written = [entry.name for entry in entries]

    assert not confirmed.is_error, confirmed.content
    assert names == [("Ryż", "Cooked Rice"), ("Cooked Rice", None)]
    assert written == ["Ryż", "Cooked Rice"]


async def test_two_rolls_of_a_known_weight_are_drafted_and_saved_as_grams_of_the_food(
    connect: Connect, fatsecret: FakeFatSecret, household: Household
) -> None:
    fatsecret.add_food(kaiser_roll())
    two_rolls = {
        "food_id": "kaiser-roll",
        "serving_id": "roll-1",
        "number_of_units": 2,
        "food_entry_name": "Kajzerka (katalog USA)",
    }

    async with connect("jakub") as client:
        proposed = await draft(client, [two_rolls])
        confirmed = await client.call_tool("confirm_draft", {"draft_id": proposed["draft_id"]})

    [item] = proposed["items"]
    [written] = await fatsecret.list_food_entries(household.user("jakub").fatsecret, TODAY)

    assert not confirmed.is_error, confirmed.content
    assert (item["serving_id"], item["serving"], item["number_of_units"]) == ("roll-100g", "100 g", 114)
    assert (item["amount"], item["kcal"], item["protein"]) == ("114 g", 334, 11.3)
    assert (written.serving_id, written.number_of_units, round(written.nutrition.kcal)) == (
        "roll-100g",
        114,
        334,
    )


async def test_a_cup_in_ml_is_logged_in_the_foods_largest_serving_in_ml(
    connect: Connect, fatsecret: FakeFatSecret
) -> None:
    cup = Serving(
        id="milk-cup",
        description="1 cup",
        metric_amount=244,
        metric_unit="ml",
        number_of_units=1,
        nutrition=Nutrition(
            kcal=149,
        ),
    )
    one_ml = Serving(
        id="milk-1ml",
        description="1 ml",
        metric_amount=1,
        metric_unit="ml",
        number_of_units=1,
        nutrition=Nutrition(
            kcal=1,
        ),
    )
    hundred_ml = Serving(
        id="milk-100ml",
        description="100 ml",
        metric_amount=100,
        metric_unit="ml",
        number_of_units=100,
        nutrition=Nutrition(
            kcal=61,
        ),
    )
    milk = Food(
        id="milk",
        name="Milk",
        brand=None,
        servings=[cup, one_ml, hundred_ml],
    )
    item = {"food_id": milk.id, "serving_id": "milk-cup", "number_of_units": 1}

    fatsecret.add_food(milk)

    async with connect("jakub") as client:
        proposed = await draft(client, [item])

    [drafted] = proposed["items"]

    assert (drafted["serving_id"], drafted["number_of_units"], drafted["amount"]) == (
        "milk-100ml",
        244,
        "244 ml",
    )
    assert drafted["kcal"] == 149


async def test_a_serving_stays_as_chosen_when_the_food_has_no_serving_in_its_unit(
    connect: Connect, fatsecret: FakeFatSecret, nutella: Food
) -> None:
    cup = Serving(
        id="milk-cup",
        description="1 cup",
        metric_amount=244,
        metric_unit="ml",
        number_of_units=1,
        nutrition=Nutrition(
            kcal=149,
        ),
    )
    hundred_grams = Serving(
        id="milk-100g",
        description="100 g",
        metric_amount=100,
        metric_unit="g",
        number_of_units=100,
        nutrition=Nutrition(
            kcal=61,
        ),
    )
    milk = Food(
        id="milk",
        name="Milk",
        brand=None,
        servings=[cup, hundred_grams],
    )
    items = [
        {"food_id": nutella.id, "serving_id": "nutella-2-tbsp", "number_of_units": 1},
        {"food_id": milk.id, "serving_id": "milk-cup", "number_of_units": 1},
    ]

    fatsecret.add_food(milk)

    async with connect("jakub") as client:
        proposed = await draft(client, items)

    logged = [(item["serving_id"], item["number_of_units"], item["amount"]) for item in proposed["items"]]

    assert logged == [("nutella-2-tbsp", 1, "37 g"), ("milk-cup", 1, "244 ml")]


@pytest.mark.parametrize(
    ("explicit_meal", "explicit_day", "day"),
    [
        ("dinner", "2026-10-13", "2026-10-13"),
        ("snacks", None, "2026-10-14"),
        ("breakfast", "2026-10-14", "2026-10-14"),
    ],
)
async def test_the_explicit_meal_and_diary_day_are_used_and_the_day_after_uses_that_days_totals(
    connect: Connect,
    fatsecret: FakeFatSecret,
    household: Household,
    clock: FakeClock,
    rice: Food,
    explicit_meal: str,
    explicit_day: str | None,
    day: str,
) -> None:
    clock.now = datetime(
        year=2026,
        month=10,
        day=13,
        hour=23,
        tzinfo=UTC,
    )
    yesterday = food_entry(
        name="Yesterday's dinner",
        meal=Meal.DINNER,
        diary_day=YESTERDAY,
        kcal=500,
    )
    items = [{"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 100}]

    fatsecret.add_food_entry(household.user("jakub").fatsecret, yesterday)

    async with connect("jakub") as client:
        proposed = await draft(client, items, meal=explicit_meal, diary_day=explicit_day)

    assert proposed["meal"] == explicit_meal
    assert proposed["diary_day"] == day
    assert proposed["day_after"]["consumed"]["kcal"] == (630 if day == "2026-10-13" else 130)


async def test_new_items_without_a_meal_are_refused_and_the_error_asks_for_it(
    connect: Connect, rice: Food
) -> None:
    items = [{"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 100}]

    async with connect("jakub") as client:
        result = await client.call_tool("draft_entries", {"items": items})

    assert result.is_error
    assert "need a meal" in str(result.content)


async def test_a_draft_of_only_changes_needs_no_meal(
    connect: Connect, fatsecret: FakeFatSecret, household: Household
) -> None:
    eaten = food_entry(
        name="Breakfast",
        meal=Meal.BREAKFAST,
        diary_day=TODAY,
        kcal=300,
    )
    removal = {"change": "remove", "diary_day": "2026-10-14", "food_entry_id": eaten.id}

    fatsecret.add_food_entry(household.user("jakub").fatsecret, eaten)

    async with connect("jakub") as client:
        result = await client.call_tool("draft_entries", {"items": [removal]})

    assert not result.is_error, result.content
    assert result.structured_content is not None
    assert result.structured_content["meal"] is None
    assert len(result.structured_content["changes"]) == 1


@pytest.mark.parametrize(
    ("food_id", "serving_id", "units", "message"),
    [
        ("missing", "rice-100g", 100, "Unknown Food"),
        ("rice", "other-food-serving", 100, "Serving"),
        ("rice", "0", 100, "Serving"),
        ("rice", "rice-100g", 0, "greater than 0"),
        ("rice", "rice-100g", -1, "greater than 0"),
        ("rice", "rice-100g", 10001, "10000"),
        ("rice", "rice-100g", "NaN", "finite"),
        ("rice", "rice-100g", "Infinity", "finite"),
        ("rice", "scoop", 30, "implausibly large"),
        ("rice", "unknown-weight", 201, "implausibly large"),
    ],
)
async def test_unknown_food_wrong_serving_and_invalid_or_implausible_amounts_are_rejected(
    connect: Connect,
    fatsecret: FakeFatSecret,
    rice: Food,
    food_id: str,
    serving_id: str,
    units: float | str,
    message: str,
) -> None:
    derived = replace(rice.servings[0], id="0")
    scoop = replace(rice.servings[0], id="scoop", number_of_units=1, metric_amount=500)
    unknown_weight = replace(
        rice.servings[0],
        id="unknown-weight",
        number_of_units=1,
        metric_amount=None,
        metric_unit=None,
    )
    food = replace(rice, servings=[*rice.servings, derived, scoop, unknown_weight])
    items = [{"food_id": food_id, "serving_id": serving_id, "number_of_units": units}]

    fatsecret.add_food(food)

    async with connect("jakub") as client:
        result = await client.call_tool("draft_entries", {"items": items, "meal": "lunch"})

    assert result.is_error
    assert message in str(result.content)


async def test_a_food_item_in_grams_is_drafted_in_the_foods_gram_serving(
    connect: Connect, rice: Food
) -> None:
    item = {"food_id": rice.id, "grams": 150}

    async with connect("jakub") as client:
        proposed = await draft(client, [item])

    [drafted] = proposed["items"]

    assert (drafted["serving_id"], drafted["number_of_units"]) == ("rice-100g", 150)
    assert (drafted["amount"], drafted["kcal"]) == ("150 g", 195)


async def test_grams_of_a_food_known_only_by_a_counted_serving_become_that_servings_units(
    connect: Connect, nutella: Food
) -> None:
    item = {"food_id": nutella.id, "grams": 74}

    async with connect("jakub") as client:
        proposed = await draft(client, [item])

    [drafted] = proposed["items"]

    assert (drafted["serving_id"], drafted["number_of_units"]) == ("nutella-2-tbsp", 2)
    assert (drafted["amount"], drafted["kcal"]) == ("74 g", 400)


async def test_grams_of_a_food_without_a_serving_of_known_grams_are_refused(
    connect: Connect, fatsecret: FakeFatSecret, rice: Food
) -> None:
    cup = replace(rice.servings[0], id="cup", metric_amount=240, metric_unit="ml", number_of_units=1)
    milk = replace(rice, id="milk", name="Milk", servings=[cup])

    fatsecret.add_food(milk)

    async with connect("jakub") as client:
        result = await client.call_tool(
            "draft_entries", {"items": [{"food_id": milk.id, "grams": 100}], "meal": "lunch"}
        )

    assert result.is_error
    assert "no Serving of known grams" in str(result.content)


@pytest.mark.parametrize(
    "item",
    [
        {"food_id": "rice", "grams": 100, "serving_id": "rice-100g", "number_of_units": 100},
        {"food_id": "rice", "grams": 100, "serving_id": "rice-100g"},
        {"food_id": "rice", "grams": 100, "number_of_units": 100},
        {"food_id": "rice"},
        {"food_id": "rice", "serving_id": "rice-100g"},
        {"food_id": "rice", "number_of_units": 100},
    ],
)
async def test_a_food_item_gives_either_grams_or_a_serving_with_units_never_both_or_neither(
    connect: Connect, fatsecret: FakeFatSecret, rice: Food, item: dict[str, Any]
) -> None:
    async with connect("jakub") as client:
        result = await client.call_tool("draft_entries", {"items": [item], "meal": "lunch"})

    assert result.is_error
    assert fatsecret.requests == 0


def decode_base64url(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


async def test_the_signed_draft_contains_only_write_values_and_survives_a_new_server_session(
    connect: Connect,
    household: Household,
    rice: Food,
) -> None:
    items = [
        {
            "food_id": rice.id,
            "serving_id": "rice-100g",
            "number_of_units": 150,
            "assumption": "This assumption must not be in the sealed Draft",
        }
    ]

    async with connect("jakub") as client:
        first = await draft(client, items)

    async with connect("jakub") as restarted:
        second = await draft(restarted, items)

    encoded, signature = first["draft_id"].split(".")
    payload = json.loads(decode_base64url(encoded))
    key = household.signing_key.get_secret_value().encode()
    expected_signature = hmac.digest(key, encoded.encode(), hashlib.sha256)

    assert hmac.compare_digest(decode_base64url(signature), expected_signature)
    assert second["draft_id"] == first["draft_id"]
    assert payload == {
        "user_id": "jakub",
        "items": [
            {
                "food_id": "rice",
                "serving_id": "rice-100g",
                "number_of_units": 150,
                "entry_name": "Cooked Rice",
            }
        ],
        "meal": "lunch",
        "diary_day": "2026-10-14",
        "expires_at": "2026-10-14T10:30:00+00:00",
    }
    assert key.decode() not in json.dumps(first)


async def test_a_draft_is_bound_to_the_calling_user_and_their_daily_targets(
    connect: Connect,
    rice: Food,
) -> None:
    items = [{"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 100}]

    async with connect("jakub") as client:
        jakubs = await draft(client, items)

    async with connect("ola") as client:
        olas = await draft(client, items)

    encoded = olas["draft_id"].split(".")[0]
    payload = json.loads(decode_base64url(encoded))

    assert payload["user_id"] == "ola"
    assert olas["draft_id"] != jakubs["draft_id"]
    assert olas["day_after"]["daily_targets"]["kcal"] == 1900


async def test_the_draft_tool_is_read_only_has_a_result_schema_and_instructs_claude_to_ask(
    connect: Connect,
    rice: Food,
) -> None:
    items = [{"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 100}]

    async with connect("jakub") as client:
        listed = (await client.list_tools()).tools
        tool = next(tool for tool in listed if tool.name == "draft_entries")
        result = await client.call_tool("draft_entries", {"items": items, "meal": "lunch"})

    [block] = result.content
    text = block.model_dump()["text"]

    assert not result.is_error
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.output_schema is not None
    assert "ask the User" in (tool.description or "")
    assert "which Meal they are for" in (tool.description or "")
    assert json.loads(text) == result.structured_content
    assert "\n" not in text
    assert ": " not in text


@pytest.mark.parametrize(
    ("timezone", "day"),
    [
        ("Europe/Warsaw", "2026-10-15"),
        ("UTC", "2026-10-14"),
        ("America/Los_Angeles", "2026-10-14"),
        ("Asia/Tokyo", "2026-10-15"),
    ],
)
async def test_the_same_utc_instant_uses_each_users_timezone_for_the_diary_day(
    household: Household,
    fatsecret: FakeFatSecret,
    clock: FakeClock,
    rice: Food,
    timezone: str,
    day: str,
) -> None:
    settings = household.user("jakub").model_dump()
    settings["timezone"] = timezone
    user = User.model_validate(settings)
    clock.now = datetime(
        year=2026,
        month=10,
        day=14,
        hour=22,
        tzinfo=UTC,
    )
    server = build_server(
        user=user,
        fatsecret=fatsecret,
        clock=clock,
        signing_key=household.signing_key,
        daily_requests=daily_budget(len(household.users)),
        food_cache=FoodCache(clock=clock),
    )
    items = [{"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 100}]

    async with Client(server) as client:
        proposed = await draft(client, items)

    assert proposed["diary_day"] == day
    assert proposed["meal"] == "lunch"
    assert proposed["expires_at"] == "2026-10-14T22:30:00Z"


async def test_six_hundred_items_are_refused_before_any_fatsecret_request(
    connect: Connect, fatsecret: FakeFatSecret, rice: Food
) -> None:
    items = [{"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 100}] * 600

    async with connect("jakub") as client:
        result = await client.call_tool("draft_entries", {"items": items})

    assert result.is_error
    assert "at most 20 items" in str(result.content)
    assert fatsecret.requests == 0


async def test_a_large_meal_of_twenty_items_fits_one_draft(connect: Connect, rice: Food) -> None:
    items = [{"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 50}] * 20

    async with connect("jakub") as client:
        result = await draft(client, items)

    assert len(result["items"]) == 20


async def test_the_draft_tool_tells_claude_to_split_a_larger_meal(connect: Connect) -> None:
    async with connect("jakub") as client:
        listed = (await client.list_tools()).tools

    tool = next(tool for tool in listed if tool.name == "draft_entries")
    items = tool.input_schema["properties"]["items"]

    assert items["maxItems"] == 20
    assert "several Drafts" in items["description"]
    assert "split a larger meal into several Drafts" in (tool.description or "")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("food_id", "1" * 21),
        ("serving_id", "1" * 21),
        ("assumption", "x" * 301),
    ],
)
async def test_overlong_food_item_text_is_refused_before_any_fatsecret_request(
    connect: Connect, fatsecret: FakeFatSecret, rice: Food, field: str, value: str
) -> None:
    item: dict[str, Any] = {"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 100}

    item[field] = value

    async with connect("jakub") as client:
        result = await client.call_tool("draft_entries", {"items": [item]})

    assert result.is_error
    assert "at most" in str(result.content)
    assert fatsecret.requests == 0


async def test_a_draft_too_long_to_confirm_is_refused_with_a_request_to_split_it(
    connect: Connect, fatsecret: FakeFatSecret, rice: Food
) -> None:
    fatsecret.add_food(replace(rice, name="Ryż " + "ż" * 2000))
    items = [{"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 50}] * 20

    async with connect("jakub") as client:
        result = await client.call_tool("draft_entries", {"items": items, "meal": "lunch"})

    assert result.is_error
    assert "several Drafts" in str(result.content)


@pytest.mark.parametrize("diary_day", ["2025-10-13", "2026-10-22", "0001-01-01", "9999-12-31"])
async def test_a_diary_day_over_a_year_back_or_over_a_week_ahead_is_refused_before_any_request(
    connect: Connect, fatsecret: FakeFatSecret, rice: Food, diary_day: str
) -> None:
    items = [{"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 100}]

    async with connect("jakub") as client:
        result = await client.call_tool(
            "draft_entries", {"items": items, "meal": "lunch", "diary_day": diary_day}
        )

    assert result.is_error
    assert "a year back" in str(result.content)
    assert fatsecret.requests == 0


@pytest.mark.parametrize("diary_day", ["2025-10-14", "2026-10-21"])
async def test_a_diary_day_a_year_back_or_a_week_ahead_can_be_drafted(
    connect: Connect, rice: Food, diary_day: str
) -> None:
    items = [{"food_id": rice.id, "serving_id": "rice-100g", "number_of_units": 100}]

    async with connect("jakub") as client:
        result = await draft(client, items, meal="lunch", diary_day=diary_day)

    assert result["diary_day"] == diary_day
