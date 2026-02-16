"""
Pickr AI - Catalog Matcher (DEPRECATED in v2)
Brand matching has been moved to pickr/engine/leverage.py → BrandMatcher class.
The BrandMatcher now queries the brands DB table directly with priority + category logic.
See: pickr/engine/leverage.py → BrandMatcher.match()
"""
# Brand matching is now in leverage.py with:
# - Hard cap at 3 brands (MAX_BRANDS_PER_EMAIL)
# - Priority brands first
# - Category adjacency fallback
# - Diversity rule (max 2 from same category)
