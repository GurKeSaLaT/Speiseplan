"""Amount placeholders in recipe instructions, so amounts in the text scale
with the servings like the ingredient list does.

Syntax: {Name}, {Name*0.5}, {Name*1/4}, {Name#2}, {Name#2*0,5}
  - Name refers to one ingredient line of the same recipe. Matching is
    case-insensitive and tries, in order: the exact name, a unique line
    whose name starts with it, a unique line containing it as a word -
    so {Champignons} finds "Champignons (braune)". Aliases count as names.
  - #n picks the n-th of several matching lines (e.g. {Butter#2} for the
    second line with "Butter" in its name).
  - *factor renders only part of the line's amount (e.g. half the butter).

The server only resolves references (tokenize_instructions); the client
renders the scaled amounts (static/plan-detail.js). Anything that doesn't
resolve stays visible verbatim, and the recipe form warns about it.
"""

import re
from fractions import Fraction

from services.ingredient_aliases import normalize_name

PLACEHOLDER_RE = re.compile(
    r'\{\s*([^{}*#\n]+?)\s*(?:#\s*(\d+)\s*)?(?:\*\s*(\d+(?:[.,]\d+)?(?:\s*/\s*\d+(?:[.,]\d+)?)?)\s*)?\}'
)


def _key(name):
    return (name or '').strip().casefold()


def parse_factor(raw):
    """"0,5" / "0.5" / "1/4" -> float; None for nothing, 0 or division by zero."""
    if raw is None:
        return 1.0
    try:
        if '/' in raw:
            numerator, denominator = (Fraction(part.strip().replace(',', '.')) for part in raw.split('/', 1))
            value = numerator / denominator
        else:
            value = Fraction(raw.strip().replace(',', '.'))
    except (ValueError, ZeroDivisionError):
        return None
    return float(value) if value > 0 else None


def resolve_reference(ref, ingredient_names, aliases=None, nth=1):
    """Index into ingredient_names for a placeholder name, or None if it's
    unknown or ambiguous. aliases is {normalized raw name: canonical name}
    (the plan's IngredientAlias map). Tiers, first non-empty one wins:
    literal name, same alias target, name prefix, whole word in the name."""
    aliases = aliases or {}
    ref_key = _key(ref)
    if not ref_key:
        return None

    def canonical_key(name):
        normalized = normalize_name(name)
        return _key(aliases.get(normalized, normalized))

    keys = [_key(name) for name in ingredient_names]
    ref_canonical = canonical_key(ref)
    word_re = re.compile(r'(?<!\w)' + re.escape(ref_key) + r'(?!\w)')
    tiers = [
        [i for i, key in enumerate(keys) if key == ref_key],
        [i for i, name in enumerate(ingredient_names) if canonical_key(name) == ref_canonical],
        [i for i, key in enumerate(keys) if key.startswith(ref_key)],
        [i for i, key in enumerate(keys) if word_re.search(key)],
    ]
    if nth > 1:
        # #n counts within the first tier that has n lines at all, so
        # {Butter#2} finds "Butter (zusätzlich)" next to plain "Butter".
        for matches in tiers:
            if len(matches) >= nth:
                return matches[nth - 1]
        return None
    for matches in tiers:
        if not matches:
            continue
        # Several equally good lines are only fine when they carry the very
        # same name (then the first one is meant); else #n must pick.
        if len({keys[i] for i in matches}) == 1:
            return matches[0]
        return None
    return None


def tokenize_instructions(text, ingredient_names, aliases=None):
    """[{"text": str} | {"ing": index, "factor": float, "raw": str}, ...]
    covering the whole text; unresolvable placeholders stay text."""
    if not text:
        return []
    parts = []
    position = 0
    for match in PLACEHOLDER_RE.finditer(text):
        ref, nth, factor_raw = match.group(1), match.group(2), match.group(3)
        index = resolve_reference(ref, ingredient_names, aliases, int(nth) if nth else 1)
        factor = parse_factor(factor_raw)
        if index is None or factor is None:
            continue
        if match.start() > position:
            parts.append({"text": text[position:match.start()]})
        parts.append({"ing": index, "factor": factor, "raw": match.group(0)})
        position = match.end()
    if position < len(text):
        parts.append({"text": text[position:]})
    return parts


def unresolved_placeholders(text, ingredient_names, aliases=None):
    """The placeholders in text that would show up verbatim, in order."""
    if not text:
        return []
    unresolved = []
    for match in PLACEHOLDER_RE.finditer(text):
        ref, nth, factor_raw = match.group(1), match.group(2), match.group(3)
        index = resolve_reference(ref, ingredient_names, aliases, int(nth) if nth else 1)
        if index is None or parse_factor(factor_raw) is None:
            unresolved.append(match.group(0))
    # Text like "{foo" or "{}" isn't a placeholder at all, but is most
    # likely a typo of one.
    stripped = PLACEHOLDER_RE.sub('', text)
    unresolved.extend(re.findall(r'\{[^{}\n]{0,40}\}?', stripped))
    return unresolved
