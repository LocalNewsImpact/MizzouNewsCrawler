"""News crawler module for discovering and fetching articles."""

import hashlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from bs4.element import Tag
from dateutil import parser as dateparser

logger = logging.getLogger(__name__)


class NewsCrawler:
    """Main crawler class for discovering and fetching news articles."""
    
    def __init__(self, user_agent: str = None, timeout: int = 20, 
                 delay: float = 1.0):
        self.user_agent = user_agent or 'Mozilla/5.0 (compatible; MizzouCrawler/1.0)'
        self.timeout = timeout
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': self.user_agent})
    
    def is_valid_url(self, url: str) -> bool:
        """Check if URL is valid and properly formatted."""
        try:
            parsed = urlparse(url)
            # Only allow http and https schemes for crawling
            if not parsed.scheme or not parsed.netloc:
                return False
            return parsed.scheme.lower() in ("http", "https")
        except Exception:
            return False
    
    def discover_links(self, seed_url: str) -> Tuple[Set[str], Set[str]]:
        """Discover internal and external links from a seed URL.
        
        Returns:
            Tuple of (internal_urls, external_urls)
        """
        domain_name = urlparse(seed_url).netloc
        internal_urls = set()
        external_urls = set()
        
        try:
            logger.info(f"Discovering links from: {seed_url}")
            resp = self.session.get(seed_url, timeout=self.timeout)
            resp.raise_for_status()
            
            soup = BeautifulSoup(resp.content, 'html.parser')
            
            for a_tag in soup.find_all('a', href=True):
                href = a_tag.get('href')
                if not href:
                    continue
                
                # Resolve relative URLs
                href = urljoin(seed_url, href)
                parsed_href = urlparse(href)
                
                # Normalize URL (remove fragment, query params for deduplication)
                normalized_url = (
                    f"{parsed_href.scheme}://{parsed_href.netloc}{parsed_href.path}"
                )
                
                if not self.is_valid_url(normalized_url):
                    continue
                
                if domain_name in parsed_href.netloc:
                    internal_urls.add(normalized_url)
                else:
                    external_urls.add(normalized_url)
            
            logger.info(f"Found {len(internal_urls)} internal, {len(external_urls)} external links")
            
        except Exception as e:
            logger.error(f"Error discovering links from {seed_url}: {e}")
        
        # Add delay between requests
        time.sleep(self.delay)
        
        return internal_urls, external_urls
    
    def fetch_page(self, url: str) -> Optional[str]:
        """Fetch HTML content from a URL.
        
        Returns:
            Raw HTML content or None if fetch failed
        """
        try:
            logger.debug(f"Fetching: {url}")
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            
            # Add delay between requests
            time.sleep(self.delay)
            
            return resp.text
            
        except Exception as e:
            logger.warning(f"Error fetching {url}: {e}")
            return None
    
    def filter_article_urls(self, urls: Set[str], 
                           site_rules: Dict[str, any] = None) -> List[str]:
        """Filter URLs to identify likely article pages.
        
        Args:
            urls: Set of URLs to filter
            site_rules: Site-specific filtering rules
            
        Returns:
            List of URLs that appear to be articles
        """
        article_urls = []
        
        for url in urls:
            if self._is_likely_article(url, site_rules):
                article_urls.append(url)
        
        logger.info(f"Filtered {len(urls)} URLs to {len(article_urls)} article candidates")
        return sorted(article_urls)
    
    def _is_likely_article(self, url: str, site_rules: Dict[str, any] = None) -> bool:
        """Determine if a URL is likely an article page."""
        # Default filters - skip known non-article paths
        skip_patterns = [
            '/show', '/podcast', '/category', '/tag', '/author',
            '/page/', '/search', '/login', '/register', '/contact',
            '/about', '/privacy', '/terms', '/sitemap'
        ]
        
        url_lower = url.lower()
        
        # Check skip patterns
        if any(pattern in url_lower for pattern in skip_patterns):
            return False
        
        # Apply site-specific rules if provided
        if site_rules:
            include_patterns = site_rules.get('include_patterns', [])
            exclude_patterns = site_rules.get('exclude_patterns', [])
            
            # Must match include patterns if specified
            if include_patterns and not any(pattern in url_lower for pattern in include_patterns):
                return False
            
            # Must not match exclude patterns
            if any(pattern in url_lower for pattern in exclude_patterns):
                return False
        
        return True


class ContentExtractor:
    """Extracts structured content from HTML pages."""
    
    def extract_article_data(self, html: str, url: str) -> Dict[str, any]:
        """Extract article metadata and content from HTML.
        
        Returns:
            Dictionary with extracted article data
        """
        if not html:
            return {}
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
        except Exception as e:
            logger.error(f"Error parsing HTML for {url}: {e}")
            return {}
        
        data = {
            'url': url,
            'title': self._extract_title(soup),
            'author': self._extract_author(soup),
            'published_date': self._extract_published_date(soup, html),
            'content': self._extract_content(soup),
            'meta_description': self._extract_meta_description(soup),
            'extracted_at': datetime.utcnow().isoformat(),
            'content_hash': None  # Will be calculated later
        }
        
        # Calculate content hash
        if data['content']:
            data['content_hash'] = hashlib.sha256(
                data['content'].encode('utf-8')
            ).hexdigest()
        
        return data
    
    def _extract_title(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article title."""
        # Try Open Graph title first
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            return og_title['content'].strip()
        
        # Try standard title tag
        title_tag = soup.find('title')
        if title_tag:
            return title_tag.get_text().strip()
        
        # Try h1 as fallback
        h1_tag = soup.find('h1')
        if h1_tag:
            return h1_tag.get_text().strip()
        
        return None
    
    def _extract_author(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract article author."""
        # Try common meta tags
        author_selectors = [
            ('meta', {'name': 'author'}),
            ('meta', {'property': 'article:author'}),
            ('meta', {'name': 'article:author'}),
            ('[rel="author"]', {}),
            ('.author', {}),
            ('.byline', {})
        ]
        
        for selector, attrs in author_selectors:
            element = soup.find(selector, attrs)
            if element:
                if element.name == 'meta':
                    author = element.get('content')
                else:
                    author = element.get_text().strip()
                
                if author:
                    return author
        
        return None
    
    def _extract_published_date(self, soup: BeautifulSoup, html: str) -> Optional[str]:
        """Extract publication date using multiple heuristics."""
        # Try JSON-LD first
        try:
            for script in soup.find_all('script', type='application/ld+json'):
                try:
                    data = json.loads(script.string or '{}')
                    if isinstance(data, list):
                        items = data
                    else:
                        items = [data]
                    
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        
                        date_published = (
                            item.get('datePublished') or 
                            item.get('dateCreated') or
                            item.get('publishedDate')
                        )
                        
                        if date_published:
                            if isinstance(date_published, (list, tuple)):
                                date_published = date_published[0] if date_published else None
                            if isinstance(date_published, dict):
                                date_published = (
                                    date_published.get('@value') or 
                                    date_published.get('value') or 
                                    str(date_published)
                                )
                            
                            if date_published:
                                try:
                                    parsed_date = dateparser.parse(str(date_published))
                                    return parsed_date.isoformat() if parsed_date else None
                                except Exception:
                                    continue
                                    
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass
        
        # Try meta tags
        meta_selectors = [
            ('property', 'article:published_time'),
            ('name', 'pubdate'),
            ('name', 'publishdate'),
            ('name', 'date'),
            ('itemprop', 'datePublished'),
            ('name', 'publish_date'),
            ('property', 'article:published')
        ]
        
        for attr, value in meta_selectors:
            meta_tag = soup.find('meta', attrs={attr: value})
            if meta_tag and isinstance(meta_tag, Tag):
                content = meta_tag.get('content')
                if content:
                    try:
                        parsed_date = dateparser.parse(str(content))
                        return parsed_date.isoformat() if parsed_date else None
                    except Exception:
                        continue
        
        # Try time element
        time_tag = soup.find('time')
        if time_tag and isinstance(time_tag, Tag):
            datetime_attr = time_tag.get('datetime')
            if datetime_attr:
                try:
                    parsed_date = dateparser.parse(str(datetime_attr))
                    return parsed_date.isoformat() if parsed_date else None
                except Exception:
                    pass
            
            # Try time text content
            time_text = time_tag.get_text().strip()
            if time_text:
                try:
                    parsed_date = dateparser.parse(time_text)
                    return parsed_date.isoformat() if parsed_date else None
                except Exception:
                    pass
        
        return None
    
    def _extract_content(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract main article content."""
        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            element.decompose()
        
        # Try common content selectors
        content_selectors = [
            'article',
            '[role="main"]',
            '.article-content',
            '.post-content',
            '.entry-content',
            '.content',
            '.story-body',
            '.article-body',
            'main'
        ]
        
        for selector in content_selectors:
            content_element = soup.select_one(selector)
            if content_element:
                text = content_element.get_text(separator=' ', strip=True)
                if len(text) > 100:  # Minimum content length
                    return text
        
        # Fallback to body
        body = soup.find('body')
        if body:
            text = body.get_text(separator=' ', strip=True)
            if len(text) > 100:
                return text
        
        return None
    
    def _extract_meta_description(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract meta description."""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            return meta_desc['content'].strip()
        
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content'):
            return og_desc['content'].strip()
        
        return None