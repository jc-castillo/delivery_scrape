"""
Just Eat (Spain) restaurant extractor.

Just Eat page structure (as of 2022-2024):
- Restaurant listings with cards
- Often has structured data
- Spanish version uses just-eat.es domain
"""
import json
import re
from typing import Optional
from bs4 import BeautifulSoup, Tag

from .base import BaseExtractor, Restaurant


class JustEatExtractor(BaseExtractor):
    """Extract restaurant data from Just Eat Spain pages."""

    platform_name = "Just Eat"

    def extract_restaurants(self, html: str, url: str,
                           timestamp: str, crawl_id: str) -> list[Restaurant]:
        """Extract restaurants from Just Eat listing page."""
        soup = self._get_soup(html)
        restaurants = []

        date = self._parse_date(timestamp)
        city = self._extract_city_from_url(url)

        # Try JSON-LD extraction first
        json_restaurants = self._extract_from_json_ld(soup, url, date, city, crawl_id)
        if json_restaurants:
            restaurants.extend(json_restaurants)

        # Try embedded data
        script_restaurants = self._extract_from_scripts(soup, url, date, city, crawl_id)
        if script_restaurants:
            restaurants.extend(script_restaurants)

        # Try HTML extraction
        if not restaurants:
            html_restaurants = self._extract_from_html(soup, url, date, city, crawl_id)
            restaurants.extend(html_restaurants)

        return restaurants

    def _extract_city_from_url(self, url: str) -> Optional[str]:
        """
        Extract city from Just Eat URL.
        Formats:
        - just-eat.es/area/{postalcode}-{city}
        - just-eat.es/restaurants-{restaurant-name}
        - just-eat.es/{city}
        """
        # Try area URL pattern first (e.g., /area/28006-madrid)
        area_match = re.search(r'just-?eat\.es/area/\d+-([^/\?]+)', url)
        if area_match:
            city = area_match.group(1)
            city = city.replace('-', ' ').title()
            return city

        # Try restaurant URL pattern
        rest_match = re.search(r'just-?eat\.es/restaurants-[^/]+/menu', url)
        if rest_match:
            # For restaurant pages, city might be in address - return None and let JSON-LD provide it
            return None

        # Try simple city pattern
        city_match = re.search(r'just-?eat\.es/([^/\?]+)$', url)
        if city_match:
            city = city_match.group(1)
            # Skip non-city paths
            if city in ['restaurants', 'menu', 'order', 'checkout', 'account', 'a-domicilio',
                        'es', 'en', 'blog', 'repartidor', 'info']:
                return None
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
                    if data.get('@type') == 'ItemList':
                        for item in data.get('itemListElement', []):
                            rest = self._parse_json_ld_item(item, url, date, city, crawl_id)
                            if rest:
                                restaurants.append(rest)
                    elif data.get('@type') == 'SearchResultsPage':
                        # Just Eat sometimes uses this type
                        main_entity = data.get('mainEntity', {})
                        if main_entity.get('@type') == 'ItemList':
                            for item in main_entity.get('itemListElement', []):
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

        # Extract address
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
            neighborhood = address_obj.get('addressLocality')
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

        # Extract geo coordinates
        lat = lon = None
        geo = item.get('geo', {})
        if isinstance(geo, dict):
            lat = geo.get('latitude')
            lon = geo.get('longitude')

        return Restaurant(
            name=self._clean_text(name),
            platform=self.platform_name,
            city=city or '',
            date=date,
            address=self._clean_text(address),
            neighborhood=neighborhood,
            food_type=cuisine[0] if cuisine else None,
            categories=cuisine,
            rating=float(rating) if rating else None,
            num_ratings=int(num_ratings) if num_ratings else None,
            price_range=item.get('priceRange'),
            latitude=lat,
            longitude=lon,
            restaurant_url=item.get('url'),
            image_url=item.get('image'),
            source_url=url,
            crawl_id=crawl_id,
        )

    def _extract_from_scripts(self, soup: BeautifulSoup, url: str,
                              date: str, city: str, crawl_id: str) -> list[Restaurant]:
        """Extract from embedded JavaScript data."""
        restaurants = []

        for script in soup.find_all('script'):
            if not script.string:
                continue

            script_text = script.string

            # Just Eat specific patterns
            patterns = [
                r'window\.__INITIAL_STATE__\s*=\s*({.+?});?\s*(?:</script>|window\.|$)',
                r'window\.je\s*=\s*({.+?});?\s*(?:</script>|$)',
                r'"restaurants"\s*:\s*(\[.+?\])',
                r'"searchResults"\s*:\s*(\[.+?\])',
                r'data-restaurant-list\s*=\s*[\'"](.+?)[\'"]',
            ]

            for pattern in patterns:
                matches = re.finditer(pattern, script_text, re.DOTALL)
                for match in matches:
                    try:
                        data_str = match.group(1)
                        # Unescape HTML entities if needed
                        data_str = data_str.replace('&quot;', '"').replace('&amp;', '&')
                        data = json.loads(data_str)
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
                    rest = self._parse_restaurant_item(item, url, date, city, crawl_id)
                    if rest:
                        restaurants.append(rest)

        elif isinstance(data, dict):
            # Navigate nested structures common in Just Eat
            for key in ['restaurants', 'searchResults', 'data', 'results',
                       'restaurantsList', 'entities']:
                if key in data:
                    nested = data[key]
                    if isinstance(nested, list):
                        restaurants.extend(
                            self._parse_embedded_data(nested, url, date, city, crawl_id)
                        )
                    elif isinstance(nested, dict):
                        for k, v in nested.items():
                            if isinstance(v, dict):
                                rest = self._parse_restaurant_item(v, url, date, city, crawl_id)
                                if rest:
                                    restaurants.append(rest)
                            elif isinstance(v, list):
                                restaurants.extend(
                                    self._parse_embedded_data(v, url, date, city, crawl_id)
                                )

        return restaurants

    def _parse_restaurant_item(self, item: dict, url: str,
                              date: str, city: str, crawl_id: str) -> Optional[Restaurant]:
        """Parse a restaurant item from embedded data."""
        # Common Just Eat field names
        name = (
            item.get('name') or item.get('restaurantName') or
            item.get('title') or item.get('displayName')
        )

        if not name:
            return None

        # Extract rating
        rating = None
        num_ratings = None
        rating_data = item.get('rating') or item.get('ratings') or {}
        if isinstance(rating_data, dict):
            rating = rating_data.get('starRating') or rating_data.get('value') or rating_data.get('average')
            num_ratings = rating_data.get('count') or rating_data.get('total')
        elif isinstance(rating_data, (int, float)):
            rating = rating_data

        # Extract address
        address = item.get('address') or item.get('streetAddress')
        if isinstance(address, dict):
            parts = [
                address.get('firstLine', ''),
                address.get('city', ''),
                address.get('postcode', ''),
            ]
            address = ', '.join(p for p in parts if p)

        # Extract cuisine/categories
        cuisines = []
        cuisine_data = item.get('cuisines') or item.get('categories') or item.get('tags') or []
        if isinstance(cuisine_data, list):
            for c in cuisine_data:
                if isinstance(c, dict):
                    cuisines.append(c.get('name', '') or c.get('displayName', ''))
                elif isinstance(c, str):
                    cuisines.append(c)

        # Extract delivery info
        delivery_info = item.get('deliveryInfo') or item.get('delivery') or {}
        delivery_fee = None
        delivery_time = None
        min_order = None

        if isinstance(delivery_info, dict):
            delivery_fee = delivery_info.get('cost') or delivery_info.get('fee')
            eta = delivery_info.get('etaMinutes') or delivery_info.get('time')
            if eta:
                delivery_time = f"{eta} min" if isinstance(eta, (int, float)) else str(eta)
            min_order = delivery_info.get('minimumOrder') or delivery_info.get('minOrderValue')

        # Geo coordinates
        lat = item.get('latitude') or item.get('lat')
        lon = item.get('longitude') or item.get('lng') or item.get('lon')

        # Restaurant URL
        rest_url = item.get('url') or item.get('seoName') or item.get('urlName')
        if rest_url and not rest_url.startswith('http'):
            rest_url = f"https://www.just-eat.es/restaurants-{rest_url}"

        return Restaurant(
            name=self._clean_text(name),
            platform=self.platform_name,
            city=city or '',
            date=date,
            address=self._clean_text(address) if isinstance(address, str) else None,
            neighborhood=item.get('neighborhood') or item.get('area'),
            food_type=cuisines[0] if cuisines else None,
            categories=[c for c in cuisines if c],
            rating=float(rating) if rating else None,
            num_ratings=int(num_ratings) if num_ratings else None,
            price_range=item.get('priceCategory'),
            delivery_fee=str(delivery_fee) if delivery_fee else None,
            delivery_time=delivery_time,
            min_order=str(min_order) if min_order else None,
            is_promoted=item.get('isSponsored', False) or item.get('promoted', False),
            is_new=item.get('isNew', False) or item.get('isNewlyOnPlatform', False),
            latitude=float(lat) if lat else None,
            longitude=float(lon) if lon else None,
            restaurant_url=rest_url,
            image_url=item.get('logoUrl') or item.get('image'),
            source_url=url,
            crawl_id=crawl_id,
        )

    def _extract_from_html(self, soup: BeautifulSoup, url: str,
                          date: str, city: str, crawl_id: str) -> list[Restaurant]:
        """Extract from HTML structure."""
        restaurants = []
        seen_names = set()

        # Just Eat card selectors - multiple patterns based on page type
        card_selectors = [
            # Area/listing pages - cards with restaurant-id
            'a[data-restaurant-id]',
            '[class*="RestaurantCard_c-restaurantCard_"]',
            # Other patterns
            'article[data-test-id="restaurant"]',
            'div[data-test-id="restaurant-card"]',
            'a[data-test-id="restaurant-link"]',
            '[data-test-id="f-restaurant-card--restaurant-card-component"]',
        ]

        for selector in card_selectors:
            cards = soup.select(selector)
            if cards:
                for card in cards:
                    rest = self._parse_html_card(card, url, date, city, crawl_id)
                    if rest and rest.name and rest.name.lower() not in seen_names:
                        seen_names.add(rest.name.lower())
                        restaurants.append(rest)
                # Found cards with this selector, no need to try others
                if restaurants:
                    break

        return restaurants

    def _parse_html_card(self, card: Tag, url: str,
                        date: str, city: str, crawl_id: str) -> Optional[Restaurant]:
        """Parse a restaurant card from HTML."""
        # Find restaurant name - try multiple patterns
        name = None
        name_selectors = [
            '[data-test-id="restaurant_name"]',
            '[data-test-id="restaurant-name"]',
            '[class*="restaurantCard-name"]',
            'h2', 'h3',
            '[class*="name"]',
        ]

        for selector in name_selectors:
            name_elem = card.select_one(selector)
            if name_elem:
                text = self._clean_text(name_elem.get_text())
                if text and len(text) > 1 and len(text) < 100:
                    name = text
                    break

        if not name:
            return None

        # Extract restaurant ID if available
        restaurant_id = card.get('data-restaurant-id')

        # Extract rating
        rating = None
        rating_elem = card.select_one(
            '[data-test-id="rating"], '
            '[class*="rating"], '
            '[class*="RatingLabel"]'
        )
        if rating_elem:
            rating_text = rating_elem.get_text()
            # Just Eat uses star ratings like "4.4"
            rating = self._parse_rating(rating_text)

        # Extract num ratings
        num_ratings = None
        count_elem = card.select_one('[class*="rating-count"], [class*="RatingCount"]')
        if count_elem:
            num_ratings = self._parse_num_ratings(count_elem.get_text())

        # Extract delivery time
        delivery_time = None
        time_elem = card.select_one(
            '[data-test-id="eta"], '
            '[class*="deliveryTime"], '
            '[class*="EtaText"]'
        )
        if time_elem:
            delivery_time = self._clean_text(time_elem.get_text())

        # Extract cuisines
        categories = []
        cuisine_elem = card.select_one('[data-test-id="cuisines"], [class*="cuisine"]')
        if cuisine_elem:
            text = cuisine_elem.get_text()
            categories = [c.strip() for c in text.split(',') if c.strip()]

        # Extract address
        address = None
        addr_elem = card.select_one('[class*="address"], [data-test-id="address"]')
        if addr_elem:
            address = self._clean_text(addr_elem.get_text())

        # Get restaurant URL
        rest_url = None
        if card.name == 'a':
            rest_url = card.get('href', '')
        else:
            link = card.find('a', href=True)
            if link:
                rest_url = link['href']

        if rest_url and not rest_url.startswith('http'):
            rest_url = f"https://www.just-eat.es{rest_url}"

        # Extract image URL
        image_url = None
        img = card.select_one('img[data-test-id="restaurant_logo"], img[src]')
        if img:
            image_url = img.get('src')

        return Restaurant(
            name=name,
            platform=self.platform_name,
            city=city or '',
            date=date,
            address=address,
            food_type=categories[0] if categories else None,
            categories=categories,
            rating=rating,
            num_ratings=num_ratings,
            delivery_time=delivery_time,
            restaurant_url=rest_url,
            image_url=image_url,
            source_url=url,
            crawl_id=crawl_id,
        )
