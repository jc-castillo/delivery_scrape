"""
Uber Eats restaurant extractor.

Uber Eats page structure (as of 2022-2024):
- Heavy use of React with __REACT_QUERY_STATE__ or similar
- Restaurant cards with structured data
- Often has JSON-LD for SEO
"""
import json
import re
from typing import Optional
from bs4 import BeautifulSoup, Tag

from .base import BaseExtractor, Restaurant


class UberEatsExtractor(BaseExtractor):
    """Extract restaurant data from Uber Eats pages."""

    platform_name = "Uber Eats"

    def extract_restaurants(self, html: str, url: str,
                           timestamp: str, crawl_id: str) -> list[Restaurant]:
        """Extract restaurants from Uber Eats listing page."""
        soup = self._get_soup(html)
        restaurants = []

        date = self._parse_date(timestamp)
        city = self._extract_city_from_url(url)

        # Try JSON-LD extraction first
        json_restaurants = self._extract_from_json_ld(soup, url, date, city, crawl_id)
        if json_restaurants:
            restaurants.extend(json_restaurants)

        # Try embedded React/Redux state
        script_restaurants = self._extract_from_scripts(soup, url, date, city, crawl_id)
        if script_restaurants:
            restaurants.extend(script_restaurants)

        # Try HTML extraction if no data from JSON
        if not restaurants:
            html_restaurants = self._extract_from_html(soup, url, date, city, crawl_id)
            restaurants.extend(html_restaurants)

        return restaurants

    def _extract_city_from_url(self, url: str) -> Optional[str]:
        """
        Extract city from Uber Eats URL.
        Formats:
        - ubereats.com/es/city/{city}
        - ubereats.com/es-en/city/{city}
        - ubereats.com/es-ES/city/{city}
        """
        patterns = [
            r'ubereats\.com/es[^/]*/city/([^/\?]+)',
            r'ubereats\.com/city/([^/\?]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                city = match.group(1)
                # Remove country/region suffix like "-es-an" or "-es-md"
                city = re.sub(r'-es-[a-z]{2}$', '', city)
                city = city.replace('-', ' ').title()
                return city
        return None

    def _extract_from_json_ld(self, soup: BeautifulSoup, url: str,
                              date: str, city: str, crawl_id: str) -> list[Restaurant]:
        """Extract from JSON-LD structured data."""
        restaurants = []

        for script in soup.find_all('script', type='application/ld+json'):
            try:
                data = json.loads(script.string)

                if isinstance(data, list):
                    for item in data:
                        rest = self._parse_json_ld_item(item, url, date, city, crawl_id)
                        if rest:
                            restaurants.append(rest)
                elif isinstance(data, dict):
                    # Check for ItemList
                    if data.get('@type') == 'ItemList':
                        for item in data.get('itemListElement', []):
                            rest = self._parse_json_ld_item(item, url, date, city, crawl_id)
                            if rest:
                                restaurants.append(rest)
                    else:
                        rest = self._parse_json_ld_item(data, url, date, city, crawl_id)
                        if rest:
                            restaurants.append(rest)

            except (json.JSONDecodeError, TypeError):
                continue

        return restaurants

    def _parse_json_ld_item(self, item: dict, url: str,
                           date: str, city: str, crawl_id: str) -> Optional[Restaurant]:
        """Parse a single JSON-LD item."""
        if not isinstance(item, dict):
            return None

        item_type = item.get('@type', '')

        # Handle ListItem wrapper
        if item_type == 'ListItem':
            item = item.get('item', {})
            if not item:
                return None
            item_type = item.get('@type', '')

        if item_type not in ['Restaurant', 'LocalBusiness', 'FoodEstablishment',
                             'FoodService', 'Organization']:
            return None

        name = item.get('name')
        if not name:
            return None

        # Extract address and locality
        address = None
        neighborhood = None
        address_obj = item.get('address', {})
        if isinstance(address_obj, dict):
            parts = [
                address_obj.get('streetAddress', ''),
                address_obj.get('addressLocality', ''),
                address_obj.get('postalCode', ''),
            ]
            address = ', '.join(p for p in parts if p)
            # Use addressLocality as the city/neighborhood
            neighborhood = address_obj.get('addressLocality', '')
        elif isinstance(address_obj, str):
            address = address_obj

        # Extract rating
        rating = None
        num_ratings = None
        rating_obj = item.get('aggregateRating', {})
        if rating_obj:
            rating = rating_obj.get('ratingValue')
            num_ratings = rating_obj.get('ratingCount') or rating_obj.get('reviewCount')

        # Extract cuisine
        cuisine = item.get('servesCuisine', [])
        if isinstance(cuisine, str):
            cuisine = [cuisine]

        # Use neighborhood as city if city wasn't extracted from URL
        actual_city = city or neighborhood or ''

        return Restaurant(
            name=self._clean_text(name),
            platform=self.platform_name,
            city=actual_city,
            date=date,
            address=self._clean_text(address),
            neighborhood=neighborhood,
            food_type=cuisine[0] if cuisine else None,
            categories=cuisine,
            rating=float(rating) if rating else None,
            num_ratings=int(num_ratings) if num_ratings else None,
            price_range=item.get('priceRange'),
            restaurant_url=item.get('url'),
            image_url=item.get('image'),
            source_url=url,
            crawl_id=crawl_id,
        )

    def _extract_from_scripts(self, soup: BeautifulSoup, url: str,
                              date: str, city: str, crawl_id: str) -> list[Restaurant]:
        """Extract from embedded JavaScript state."""
        restaurants = []

        for script in soup.find_all('script'):
            if not script.string:
                continue

            script_text = script.string

            # Uber Eats specific patterns
            patterns = [
                r'window\.__REACT_QUERY_STATE__\s*=\s*({.+?});?\s*(?:</script>|$)',
                r'window\.__PRELOADED_STATE__\s*=\s*({.+?});?\s*(?:</script>|$)',
                r'"stores"\s*:\s*(\[.+?\])',
                r'"feedItems"\s*:\s*(\[.+?\])',
                r'"storesMap"\s*:\s*({.+?})\s*[,}]',
            ]

            for pattern in patterns:
                matches = re.finditer(pattern, script_text, re.DOTALL)
                for match in matches:
                    try:
                        data = json.loads(match.group(1))
                        rests = self._parse_embedded_data(data, url, date, city, crawl_id)
                        restaurants.extend(rests)
                    except json.JSONDecodeError:
                        continue

        return restaurants

    def _parse_embedded_data(self, data: dict | list, url: str,
                            date: str, city: str, crawl_id: str) -> list[Restaurant]:
        """Parse embedded JSON data."""
        restaurants = []

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    # Check if this looks like a restaurant/store
                    rest = self._parse_store_item(item, url, date, city, crawl_id)
                    if rest:
                        restaurants.append(rest)

        elif isinstance(data, dict):
            # Navigate nested structures
            for key in ['stores', 'feedItems', 'storesMap', 'data', 'queries', 'state']:
                if key in data:
                    nested = data[key]
                    if isinstance(nested, list):
                        restaurants.extend(
                            self._parse_embedded_data(nested, url, date, city, crawl_id)
                        )
                    elif isinstance(nested, dict):
                        # Check if it's a map of stores
                        for k, v in nested.items():
                            if isinstance(v, dict):
                                rest = self._parse_store_item(v, url, date, city, crawl_id)
                                if rest:
                                    restaurants.append(rest)
                            elif isinstance(v, list):
                                restaurants.extend(
                                    self._parse_embedded_data(v, url, date, city, crawl_id)
                                )

        return restaurants

    def _parse_store_item(self, item: dict, url: str,
                         date: str, city: str, crawl_id: str) -> Optional[Restaurant]:
        """Parse a store/restaurant item from embedded data."""
        # Common Uber Eats field names
        name = (
            item.get('title') or item.get('name') or
            item.get('store', {}).get('title') or item.get('store', {}).get('name')
        )

        if not name:
            return None

        # Handle nested store object
        store = item.get('store', item)

        # Extract rating info
        rating_data = store.get('rating', {})
        if isinstance(rating_data, dict):
            rating = rating_data.get('ratingValue') or rating_data.get('value')
            num_ratings = rating_data.get('ratingCount') or rating_data.get('count')
        else:
            rating = rating_data if isinstance(rating_data, (int, float)) else None
            num_ratings = None

        # Extract delivery info
        eta = store.get('etaRange') or store.get('deliveryTime')
        if isinstance(eta, dict):
            eta = f"{eta.get('min', '')}-{eta.get('max', '')} min"

        # Extract categories/cuisine
        categories = []
        category_data = store.get('categories') or store.get('cuisines') or store.get('tags')
        if isinstance(category_data, list):
            for cat in category_data:
                if isinstance(cat, dict):
                    categories.append(cat.get('name', '') or cat.get('title', ''))
                elif isinstance(cat, str):
                    categories.append(cat)

        return Restaurant(
            name=self._clean_text(name),
            platform=self.platform_name,
            city=city or '',
            date=date,
            address=self._clean_text(store.get('address') or store.get('location', {}).get('address')),
            food_type=categories[0] if categories else None,
            categories=[c for c in categories if c],
            rating=float(rating) if rating else None,
            num_ratings=int(num_ratings) if num_ratings else None,
            price_range=store.get('priceBucket') or store.get('priceRange'),
            delivery_fee=store.get('deliveryFee'),
            delivery_time=str(eta) if eta else None,
            is_promoted=store.get('isPromoted', False) or store.get('promoted', False),
            is_new=store.get('isNew', False),
            latitude=store.get('location', {}).get('latitude') if isinstance(store.get('location'), dict) else None,
            longitude=store.get('location', {}).get('longitude') if isinstance(store.get('location'), dict) else None,
            restaurant_url=store.get('url') or store.get('slug'),
            image_url=store.get('heroImageUrl') or store.get('imageUrl'),
            source_url=url,
            crawl_id=crawl_id,
        )

    def _extract_from_html(self, soup: BeautifulSoup, url: str,
                          date: str, city: str, crawl_id: str) -> list[Restaurant]:
        """Extract from HTML structure."""
        restaurants = []

        # Uber Eats card selectors
        card_selectors = [
            'a[data-testid="store-card"]',
            'div[data-testid="feed-item"]',
            'a[href*="/store/"]',
            'div[class*="StoreCard"]',
            'article[class*="store"]',
        ]

        for selector in card_selectors:
            cards = soup.select(selector)
            for card in cards:
                rest = self._parse_html_card(card, url, date, city, crawl_id)
                if rest:
                    restaurants.append(rest)

        return restaurants

    def _parse_html_card(self, card: Tag, url: str,
                        date: str, city: str, crawl_id: str) -> Optional[Restaurant]:
        """Parse a restaurant card from HTML."""
        # Find restaurant name
        name_elem = card.select_one('h3, [class*="StoreTitle"], [class*="name"]')
        if not name_elem:
            # Try getting from aria-label
            name = card.get('aria-label', '')
        else:
            name = name_elem.get_text()

        name = self._clean_text(name)
        if not name or len(name) < 2:
            return None

        # Extract rating
        rating = None
        rating_elem = card.select_one('[class*="rating"], [class*="RatingText"]')
        if rating_elem:
            rating = self._parse_rating(rating_elem.get_text())

        # Extract delivery time
        delivery_time = None
        time_elem = card.select_one('[class*="time"], [class*="eta"], [class*="EtaText"]')
        if time_elem:
            delivery_time = self._clean_text(time_elem.get_text())

        # Extract categories
        categories = []
        cat_elem = card.select_one('[class*="category"], [class*="cuisine"]')
        if cat_elem:
            categories = [c.strip() for c in cat_elem.get_text().split('•') if c.strip()]

        # Get restaurant URL
        rest_url = None
        if card.name == 'a':
            rest_url = card.get('href', '')
        else:
            link = card.find('a', href=True)
            if link:
                rest_url = link['href']

        if rest_url and not rest_url.startswith('http'):
            rest_url = f"https://www.ubereats.com{rest_url}"

        return Restaurant(
            name=name,
            platform=self.platform_name,
            city=city or '',
            date=date,
            food_type=categories[0] if categories else None,
            categories=categories,
            rating=rating,
            delivery_time=delivery_time,
            restaurant_url=rest_url,
            source_url=url,
            crawl_id=crawl_id,
        )
