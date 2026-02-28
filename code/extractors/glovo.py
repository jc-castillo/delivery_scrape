"""
Glovo restaurant extractor.

Based on analysis of Common Crawl pages:
- Listing pages: /es/es/{city}/restaurantes_1/
- Uses __NUXT__ for embedded data
- HTML has store-card elements with restaurant info
- Rating shown as percentage (e.g., "81%")
"""
import json
import re
from typing import Optional
from bs4 import BeautifulSoup, Tag

from .base import BaseExtractor, Restaurant


class GlovoExtractor(BaseExtractor):
    """Extract restaurant data from Glovo pages."""

    platform_name = "Glovo"

    def extract_restaurants(self, html: str, url: str,
                           timestamp: str, crawl_id: str) -> list[Restaurant]:
        """Extract restaurants from Glovo listing page."""
        # Skip non-restaurant URLs (supermarkets, pharmacies, shops)
        non_restaurant_paths = ['/supermercados', '/parafarmacia', '/tiendas']
        if any(p in url.lower() for p in non_restaurant_paths):
            return []

        soup = self._get_soup(html)
        restaurants = []

        date = self._parse_date(timestamp)
        city = self._extract_city_from_url(url)

        # Check if this is an individual restaurant page (no store cards)
        # For individual pages, JSON-LD is more reliable
        # Use card container selectors (not sub-elements like rating-info)
        listing_selectors = [
            '[data-test-id="category-store-card"]',
            'a.collection-item',
            '[class*="store-card"]:not([class*="store-card-rating"]):not([class*="store-card-info"])',
            '[class*="StoreCard"]',
        ]
        is_listing_page = any(soup.select(sel) for sel in listing_selectors)

        if is_listing_page:
            # Listing page: Extract from HTML store cards (most reliable)
            html_restaurants = self._extract_from_html_cards(soup, url, date, city, crawl_id)
            if html_restaurants:
                restaurants.extend(html_restaurants)
        else:
            # Individual restaurant page: Try JSON-LD first (has correct restaurant name)
            json_restaurants = self._extract_from_json_ld(soup, url, date, city, crawl_id)
            if json_restaurants:
                restaurants.extend(json_restaurants)
            else:
                # Fallback to HTML extraction
                html_restaurants = self._extract_from_html_cards(soup, url, date, city, crawl_id)
                if html_restaurants:
                    restaurants.extend(html_restaurants)

        return restaurants

    def _extract_city_from_url(self, url: str) -> Optional[str]:
        """
        Extract city from Glovo URL.
        Format: glovoapp.com/es/{lang}/{city}/...
        """
        match = re.search(r'glovoapp\.com/es/[^/]+/([^/]+)', url)
        if match:
            city = match.group(1)
            # Clean city name - remove restaurantes suffix, trailing numbers
            city = re.sub(r'[-_]?restaurantes.*$', '', city, flags=re.IGNORECASE)
            city = re.sub(r'[-_]?\d+$', '', city)
            city = city.replace('-', ' ').replace('_', ' ').strip().title()
            if not city:
                return None
            # Filter out non-city values (UI labels, generic strings)
            non_city_patterns = ['domicilio', 'delivery', 'glovo', 'banaketa']
            if any(p in city.lower() for p in non_city_patterns):
                return None
            return city
        return None

    def _extract_from_html_cards(self, soup: BeautifulSoup, url: str,
                                  date: str, city: str, crawl_id: str) -> list[Restaurant]:
        """Extract restaurants from HTML store card elements."""
        restaurants = []
        seen_names = set()  # Deduplicate within page

        # Find store card containers (not sub-elements like rating-info)
        cards = soup.select('[data-test-id="category-store-card"]')

        if not cards:
            cards = soup.select('a.collection-item')

        if not cards:
            # Broader selectors, excluding known sub-elements
            cards = soup.select(
                '[class*="StoreCard"], [data-test-id*="store"],'
                ' a[href*="/es/es/"][href$="/"]'
            )

        for card in cards:
            try:
                rest = self._parse_store_card(card, url, date, city, crawl_id)
                if rest and rest.name and rest.name.lower() not in seen_names:
                    seen_names.add(rest.name.lower())
                    restaurants.append(rest)
            except Exception:
                continue

        return restaurants

    def _parse_store_card(self, card: Tag, url: str,
                         date: str, city: str, crawl_id: str) -> Optional[Restaurant]:
        """Parse a single store card element."""
        # Find restaurant name - look for common name patterns
        name = None
        name_selectors = [
            '[class*="name"]',
            '[class*="title"]',
            'h2', 'h3', 'h4',
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

        # Skip if name looks like a category, navigation item, or promo
        skip_patterns = ['restaurantes', 'ver más', 'ver todo', 'categoría', 'filtro',
                        'ordenar', 'buscar', 'envío', 'delivery',
                        # Discount / promo strings
                        '-30%', '-20%', '-10%', '2x1', '1+1',
                        'sort by', 'ordenar por',
                        # Category names (not restaurant names)
                        'comida', 'supermercado', 'snacks', 'tiendas', 'parafarmacia']
        if any(p in name.lower() for p in skip_patterns):
            return None

        # Extract rating - Glovo shows as percentage like "81%" or "(43)"
        rating = None
        num_ratings = None

        rating_elem = card.select_one('[class*="rating"]')
        if rating_elem:
            rating_text = rating_elem.get_text()

            # Parse percentage rating (e.g., "81%")
            pct_match = re.search(r'(\d+)\s*%', rating_text)
            if pct_match:
                # Convert percentage to 5-star scale
                rating = float(pct_match.group(1)) / 20.0

            # Parse number of ratings (e.g., "(43)" or "(1.2k)")
            count_match = re.search(r'\((\d+[,.]?\d*[kK]?)\)', rating_text)
            if count_match:
                num_ratings = self._parse_num_ratings(count_match.group(1))

        # Extract delivery time / ETA
        delivery_time = None
        eta_elem = card.select_one('[class*="eta"], [class*="time"]')
        if eta_elem:
            eta_text = self._clean_text(eta_elem.get_text())
            # Filter out non-ETA text
            if re.search(r'\d+\s*(min|hora|hr)', eta_text, re.IGNORECASE):
                delivery_time = eta_text

        # Extract restaurant URL from link
        rest_url = None
        if card.name == 'a':
            rest_url = card.get('href', '')
        else:
            link = card.find('a', href=True)
            if link:
                rest_url = link['href']

        if rest_url and not rest_url.startswith('http'):
            rest_url = f"https://glovoapp.com{rest_url}"

        # Extract image URL
        image_url = None
        img = card.select_one('img[src], img[data-src], [style*="background-image"]')
        if img:
            if img.get('src'):
                image_url = img['src']
            elif img.get('data-src'):
                image_url = img['data-src']
            elif img.get('style'):
                bg_match = re.search(r'url\(["\']?([^"\']+)["\']?\)', img['style'])
                if bg_match:
                    image_url = bg_match.group(1)

        # Extract food category from URL path
        food_type = None
        if url:
            # URL patterns: /restaurantes_1/{category}/, /restaurants_1/{category}/,
            # /menjar_1/{category}/, /comida_1/{category}/
            cat_match = re.search(r'/(?:restaurantes|restaurants|menjar|comida)[^/]*/([^/]+)', url)
            if cat_match:
                cat = cat_match.group(1)
                # Strip trailing numeric IDs (e.g., "_34835")
                cat = re.sub(r'_\d+$', '', cat)
                if cat not in ['search-glovo', 'gasthof'] and not cat.startswith('search'):
                    food_type = cat.replace('-', ' ').replace('_', ' ').title()

        return Restaurant(
            name=name,
            platform=self.platform_name,
            city=city or '',
            date=date,
            food_type=food_type,
            rating=round(rating, 2) if rating else None,
            num_ratings=num_ratings,
            delivery_time=delivery_time,
            restaurant_url=rest_url,
            image_url=image_url,
            source_url=url,
            crawl_id=crawl_id,
        )

    def _extract_from_json_ld(self, soup: BeautifulSoup, url: str,
                              date: str, city: str, crawl_id: str) -> list[Restaurant]:
        """Extract from JSON-LD structured data (fallback)."""
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
                    else:
                        rest = self._parse_json_ld_item(data, url, date, city, crawl_id)
                        if rest:
                            restaurants.append(rest)

            except (json.JSONDecodeError, TypeError):
                continue

        return restaurants

    def _parse_json_ld_item(self, item: dict, url: str,
                           date: str, city: str, crawl_id: str) -> Optional[Restaurant]:
        """Parse a single JSON-LD item into a Restaurant."""
        if not isinstance(item, dict):
            return None

        item_type = item.get('@type', '')

        # Handle ListItem wrapper
        if item_type == 'ListItem':
            item = item.get('item', {})
            if not item:
                return None
            item_type = item.get('@type', '')

        if item_type not in ['Restaurant', 'LocalBusiness', 'FoodEstablishment', 'Store']:
            return None

        name = item.get('name')
        if not name:
            return None

        # Skip generic names like "Glovo"
        if name.lower() in ['glovo', 'glovoapp']:
            return None

        # Extract address
        address = None
        address_obj = item.get('address', {})
        if isinstance(address_obj, dict):
            parts = [
                address_obj.get('streetAddress', ''),
                address_obj.get('addressLocality', ''),
                address_obj.get('postalCode', ''),
            ]
            address = ', '.join(p for p in parts if p)
        elif isinstance(address_obj, str):
            address = address_obj

        # Extract rating
        rating = None
        num_ratings = None
        rating_obj = item.get('aggregateRating', {})
        if rating_obj:
            rating_val = rating_obj.get('ratingValue')
            # Handle percentage ratings (e.g., "95%")
            if isinstance(rating_val, str) and '%' in rating_val:
                try:
                    rating = float(rating_val.replace('%', '').strip()) / 20.0  # Convert to 5-star scale
                except ValueError:
                    rating = None
            elif rating_val:
                try:
                    rating = float(rating_val)
                except (ValueError, TypeError):
                    rating = None
            num_ratings = rating_obj.get('ratingCount') or rating_obj.get('reviewCount')

        # Extract cuisine
        cuisine = item.get('servesCuisine', [])
        if isinstance(cuisine, str):
            cuisine = [cuisine]

        # Parse num_ratings safely
        parsed_num_ratings = None
        if num_ratings:
            try:
                parsed_num_ratings = int(str(num_ratings).replace(',', ''))
            except (ValueError, TypeError):
                parsed_num_ratings = None

        return Restaurant(
            name=self._clean_text(name),
            platform=self.platform_name,
            city=city or '',
            date=date,
            address=self._clean_text(address),
            food_type=cuisine[0] if cuisine else None,
            categories=cuisine,
            rating=round(rating, 2) if rating else None,
            num_ratings=parsed_num_ratings,
            price_range=item.get('priceRange'),
            restaurant_url=item.get('url'),
            image_url=item.get('image'),
            latitude=item.get('geo', {}).get('latitude') if isinstance(item.get('geo'), dict) else None,
            longitude=item.get('geo', {}).get('longitude') if isinstance(item.get('geo'), dict) else None,
            source_url=url,
            crawl_id=crawl_id,
        )
