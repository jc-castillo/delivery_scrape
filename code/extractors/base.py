"""
Base extractor class and data models.
"""
import html as html_module
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional
from bs4 import BeautifulSoup


@dataclass
class Restaurant:
    """Restaurant data model."""
    # Required fields
    name: str
    platform: str
    city: str
    date: str  # YYYY-MM-DD format

    # Optional fields
    address: Optional[str] = None
    neighborhood: Optional[str] = None
    food_type: Optional[str] = None  # cuisine type
    categories: list[str] = field(default_factory=list)
    rating: Optional[float] = None
    num_ratings: Optional[int] = None
    price_range: Optional[str] = None  # e.g., "€", "€€", "€€€"
    delivery_fee: Optional[str] = None
    delivery_time: Optional[str] = None  # e.g., "20-30 min"
    min_order: Optional[str] = None
    is_promoted: bool = False
    is_new: bool = False
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    restaurant_url: Optional[str] = None
    image_url: Optional[str] = None

    # Metadata
    source_url: Optional[str] = None
    crawl_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for CSV export."""
        return asdict(self)

    @classmethod
    def csv_headers(cls) -> list[str]:
        """Get CSV column headers."""
        return [
            'date', 'city', 'name', 'platform', 'address', 'neighborhood',
            'food_type', 'categories', 'rating', 'num_ratings', 'price_range',
            'delivery_fee', 'delivery_time', 'min_order', 'is_promoted',
            'is_new', 'latitude', 'longitude', 'restaurant_url', 'image_url',
            'source_url', 'crawl_id'
        ]


class BaseExtractor(ABC):
    """Base class for platform-specific extractors."""

    platform_name: str = "unknown"

    @abstractmethod
    def extract_restaurants(self, html: str, url: str,
                           timestamp: str, crawl_id: str) -> list[Restaurant]:
        """
        Extract restaurant data from HTML content.

        Args:
            html: HTML content of the page
            url: Original URL of the page
            timestamp: Crawl timestamp
            crawl_id: Common Crawl ID

        Returns:
            List of Restaurant objects
        """
        pass

    def _parse_date(self, timestamp: str) -> str:
        """Convert Common Crawl timestamp to date string."""
        if not timestamp:
            return ""

        # Try ISO format first: 2023-06-01T08:32:22
        if 'T' in timestamp or '-' in timestamp:
            try:
                # Handle ISO format with or without T
                date_part = timestamp.split('T')[0] if 'T' in timestamp else timestamp[:10]
                dt = datetime.strptime(date_part, "%Y-%m-%d")
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                pass

        # CC timestamp format: YYYYMMDDhhmmss
        try:
            dt = datetime.strptime(timestamp[:8], "%Y%m%d")
            return dt.strftime("%Y-%m-%d")
        except ValueError:
            return timestamp[:10] if len(timestamp) >= 10 else timestamp

    def _get_soup(self, html: str) -> BeautifulSoup:
        """Parse HTML with BeautifulSoup."""
        return BeautifulSoup(html, 'html.parser')

    def _extract_city_from_url(self, url: str) -> Optional[str]:
        """Extract city name from URL. Override in subclasses."""
        return None

    def _clean_text(self, text: Optional[str]) -> Optional[str]:
        """Clean and normalize text."""
        if text is None:
            return None
        text = html_module.unescape(text)
        return ' '.join(text.strip().split())

    def _parse_rating(self, text: Optional[str]) -> Optional[float]:
        """Parse rating from text."""
        if text is None:
            return None
        import re
        match = re.search(r'(\d+[.,]\d+|\d+)', text)
        if match:
            return float(match.group(1).replace(',', '.'))
        return None

    def _parse_num_ratings(self, text: Optional[str]) -> Optional[int]:
        """Parse number of ratings from text."""
        if text is None:
            return None
        import re
        # Match patterns like "1.2k", "500+", "(1234)"
        text = text.lower().replace(',', '.').replace('(', '').replace(')', '')
        text = text.replace('+', '').strip()

        if 'k' in text:
            match = re.search(r'(\d+\.?\d*)\s*k', text)
            if match:
                return int(float(match.group(1)) * 1000)
        else:
            match = re.search(r'(\d+)', text)
            if match:
                return int(match.group(1))
        return None
