"""
HTML extractors for food delivery platforms.
"""
from .base import BaseExtractor, Restaurant
from .glovo import GlovoExtractor
from .ubereats import UberEatsExtractor
from .justeat import JustEatExtractor

EXTRACTORS = {
    'glovo': GlovoExtractor,
    'ubereats': UberEatsExtractor,
    'justeat': JustEatExtractor,
}


def get_extractor(platform: str) -> BaseExtractor:
    """Get the appropriate extractor for a platform."""
    if platform not in EXTRACTORS:
        raise ValueError(f"Unknown platform: {platform}")
    return EXTRACTORS[platform]()
