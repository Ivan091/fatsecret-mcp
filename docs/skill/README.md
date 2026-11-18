# The meal-photo skill

`SKILL.md` is a claude.ai skill, in Polish, built from the "Food Image Analyzer (Raw Ingredients Summary)" skill you used before. Its recognition rules are kept: 3 to 5 main ingredients, raw or dry weights, hidden calories such as oil and sauces folded into the listed items, Polish output, no macros.

What it adds when the FatSecret connector is connected:

- Each ingredient is searched in FatSecret with an English name in its raw or dry form, since the free Basic key only reaches the US catalog in English. The list shows the Polish name, and the matched FatSecret food beside it.
- Weights are computed from the matched food's own `kcal_per_100g` and rounded to 5 g. The kcal are then recomputed from the rounded weight, so the logged entry shows exactly the kcal on the list. Items are drafted in grams (`grams`), so no serving maths is needed.
- The list is the draft. Claude always asks which meal it is and never guesses it (the server also refuses a draft without a meal). Naming the meal approves that exact list. `confirm_draft` stays on "Needs approval" in the connector settings, so the app asks once more before writing.
- A bad match is fixed by showing the next search results (`next_page`) or searching again.
- Undo, edits and deletions go through drafts, as do questions about the day so far.

Without the connector it behaves like the old skill: the same list format, nothing logged.

To install it, see step 6 in [fly.md](../fly.md).
