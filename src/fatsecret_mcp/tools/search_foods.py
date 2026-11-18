"""search_foods: catalog matches for a description, with Servings that can be logged."""

from __future__ import annotations

from typing import Annotated

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, ToolAnnotations

from fatsecret_mcp.fatsecret.catalog import loggable_page
from fatsecret_mcp.fatsecret.errors import FatSecretError
from fatsecret_mcp.fatsecret.food_cache import FoodCache
from fatsecret_mcp.fatsecret.gateway import FatSecretGateway
from fatsecret_mcp.tools.schemas import (
    EnglishRendering,
    FoodDescription,
    FoodMatch,
    FoodSearch,
    SearchPage,
    as_tool_result,
)


def register(server: MCPServer, fatsecret: FatSecretGateway, food_cache: FoodCache) -> None:
    annotations = ToolAnnotations(
        title="Search Foods",
        read_only_hint=True,
    )

    @server.tool(annotations=annotations)
    async def search_foods(
        description: FoodDescription, english_rendering: EnglishRendering = None, page: SearchPage = 0
    ) -> Annotated[CallToolResult, FoodSearch]:
        """Find catalog Foods with loggable Servings, kcal and Macros.

        Search one food at a time. Search a composed dish, such as a plate in a photo, as a whole first
        (e.g. "beef bibimbap"), and its components separately only when the dish has no good match.
        Pass the User's original description and, for non-English input, an English rendering: the
        catalog is searched with the English rendering, or the original when omitted. Nutrition and
        metric amounts describe the whole Serving; number_of_units is its FatSecret unit count.
        kcal_per_100g is the value a Food item drafted in grams uses: compute an item's grams from it,
        so the logged kcal match what the User was shown. When no match fits, search again with
        page=next_page for the next matches, or with a better English rendering. A not_found result
        is normal. When a branded product isn't among the matches, ask the User for
        a photo of its Nutrition Label and draft it as a Stand-in with draft_entries. This tool does
        not write to the Food Diary.
        """
        if not description.strip():
            raise ToolError("description must not be blank.")

        query = (english_rendering if english_rendering is not None else description).strip()

        if not query:
            raise ToolError("english_rendering must not be blank.")

        try:
            found_page = await loggable_page(fatsecret, food_cache, query, page=page)
        except FatSecretError as error:
            raise ToolError(str(error)) from error

        matches = [FoodMatch.of(food) for food in found_page.foods]
        found = FoodSearch(
            status="found" if matches else "not_found",
            matches=matches,
            page=page,
            next_page=page + 1 if found_page.has_next_page else None,
        )

        return as_tool_result(found)
