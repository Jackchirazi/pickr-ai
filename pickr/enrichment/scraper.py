"""
Pickr AI - Storefront Scraper (v2)
Spec steps 16-30: Fetch homepage, store HTML snapshot, extract signals.
Stores artifacts with content hashes for audit.
"""
import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup
from pickr.config import ARTIFACTS_DIR, SCRAPE_BUDGET_MS, SCRAPE_MAX_PAGES

logger = logging.getLogger(__name__)

PLATFORM_SIGNATURES = {
    "shopify": ["cdn.shopify.com", "Shopify.theme", "myshopify.com"],
    "bigcommerce": ["bigcommerce.com", "stencil-utils"],
    "woocommerce": ["woocommerce", "wp-content/plugins/woocommerce"],
    "magento": ["magento", "mage/cookies"],
    "amazon": ["amazon.com", "amzn.to"],
    "walmart": ["walmart.com"],
}


class StorefrontScraper:
    """Scrapes storefronts and returns structured signals for lead_signals table."""

    def __init__(self):
        self.client = httpx.Client(
            timeout=15, follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PickrBot/1.0)"},
        )

    def scrape(self, url: str, lead_id: str) -> dict:
        """Full scrape pipeline. Returns signals dict."""
        start = time.time()
        r = {
            "success": False, "url": url, "final_url": None, "status_code": None,
            "detected_platform": None, "site_excerpt": None, "categories": [],
            "sample_products": [], "brand_mentions_raw": [], "sku_count_estimate": 0,
            "price_range_min": None, "price_range_max": None,
            "map_text_found": False, "map_text_excerpt": None,
            "private_label_ratio": 0.0, "scrape_artifact_path": None,
            "scrape_artifact_hash": None, "pages_fetched": 0, "error": None,
        }
        try:
            resp = self.client.get(url)
            r["status_code"] = resp.status_code
            r["final_url"] = str(resp.url)
            html = resp.text

            # Store HTML snapshot
            adir = ARTIFACTS_DIR / lead_id
            adir.mkdir(parents=True, exist_ok=True)
            apath = adir / "home.html"
            apath.write_text(html, encoding="utf-8")
            r["scrape_artifact_path"] = str(apath)
            r["scrape_artifact_hash"] = hashlib.sha256(html.encode()).hexdigest()
            r["pages_fetched"] = 1

            soup = BeautifulSoup(html, "lxml")
            text = soup.get_text(separator=" ", strip=True)
            r["site_excerpt"] = text[:2000]
            r["detected_platform"] = self._detect_platform(html)
            r["categories"] = self._extract_categories(soup)

            # Fetch sample products
            purls = self._find_product_urls(soup, r["final_url"])
            products = []
            for purl in purls[:min(SCRAPE_MAX_PAGES - 1, 6)]:
                if (time.time() - start) * 1000 > SCRAPE_BUDGET_MS:
                    break
                try:
                    p = self._fetch_product(purl)
                    if p:
                        products.append(p)
                        r["pages_fetched"] += 1
                except Exception:
                    pass
            r["sample_products"] = products
            r["sku_count_estimate"] = self._estimate_skus(soup, html)

            prices = [p["price"] for p in products if p.get("price")]
            if prices:
                r["price_range_min"] = min(prices)
                r["price_range_max"] = max(prices)

            r["brand_mentions_raw"] = self._extract_brands(soup, products)

            mp = self._detect_map(soup, html)
            r["map_text_found"] = mp["found"]
            r["map_text_excerpt"] = mp.get("excerpt")

            r["private_label_ratio"] = self._pl_ratio(soup, products)
            r["success"] = True
        except Exception as e:
            r["error"] = str(e)
            logger.error(f"Scrape failed {url}: {e}")
        return r

    def _detect_platform(self, html: str) -> str:
        hl = html.lower()
        for plat, sigs in PLATFORM_SIGNATURES.items():
            if any(s.lower() in hl for s in sigs):
                return plat
        return "custom"

    def _extract_categories(self, soup: BeautifulSoup) -> list[str]:
        cats = set()
        skip = {"home","about","contact","blog","faq","cart","login","register","account","search","help"}
        for nav in soup.find_all("nav"):
            for a in nav.find_all("a"):
                t = a.get_text(strip=True)
                if t and 2 < len(t) < 50 and t.lower() not in skip:
                    cats.add(t)
        return list(cats)[:20]

    def _find_product_urls(self, soup: BeautifulSoup, base: str) -> list[str]:
        urls = set()
        for a in soup.find_all("a", href=True):
            h = a["href"]
            if any(p in h for p in ["/products/", "/product/", "/dp/", "/item/"]):
                if h.startswith("/"):
                    h = urljoin(base, h)
                if h.startswith("http"):
                    urls.add(h)
        return list(urls)[:10]

    def _fetch_product(self, url: str) -> Optional[dict]:
        resp = self.client.get(url)
        soup = BeautifulSoup(resp.text, "lxml")
        p = {"url": url, "title": None, "price": None, "vendor": None}
        for s in soup.find_all("script", type="application/ld+json"):
            try:
                d = json.loads(s.string)
                if isinstance(d, dict) and d.get("@type") == "Product":
                    p["title"] = d.get("name")
                    o = d.get("offers", {})
                    if isinstance(o, dict):
                        try: p["price"] = float(o.get("price", ""))
                        except: pass
                    p["vendor"] = (d.get("brand") or {}).get("name")
            except: pass
        if not p["title"]:
            t = soup.find("title")
            if t: p["title"] = t.get_text(strip=True)[:200]
        if p["price"] is None:
            m = soup.find("meta", {"property": "product:price:amount"})
            if m:
                try: p["price"] = float(m.get("content", ""))
                except: pass
        return p if p["title"] else None

    def _estimate_skus(self, soup: BeautifulSoup, html: str) -> int:
        for pat in [r'(\d+)\s*products?\b', r'(\d+)\s*items?\b', r'showing.*?of\s*(\d+)']:
            m = re.search(pat, html, re.IGNORECASE)
            if m:
                try:
                    c = int(m.group(1))
                    if 1 < c < 100000: return c
                except: pass
        return max(len(soup.find_all("a", href=re.compile(r'/products?/'))), 0)

    def _extract_brands(self, soup: BeautifulSoup, products: list) -> list[str]:
        brands = set()
        for p in products:
            if p.get("vendor"): brands.add(p["vendor"])
        for m in soup.find_all("meta", {"property": "product:brand"}):
            c = m.get("content", "").strip()
            if c: brands.add(c)
        return list(brands)[:50]

    def _detect_map(self, soup: BeautifulSoup, html: str) -> dict:
        kws = ["MAP pricing", "minimum advertised price", "MSRP", "pricing policy", "authorized dealer"]
        hl = html.lower()
        for kw in kws:
            if kw.lower() in hl:
                i = hl.index(kw.lower())
                excerpt = re.sub(r'<[^>]+>', ' ', html[max(0,i-100):i+200]).strip()
                return {"found": True, "excerpt": excerpt[:300]}
        return {"found": False}

    def _pl_ratio(self, soup: BeautifulSoup, products: list) -> float:
        if not products: return 0.0
        t = soup.find("title")
        if not t: return 0.0
        sb = t.get_text(strip=True).split("|")[0].split("-")[0].strip().lower()
        if not sb: return 0.0
        ct = sum(1 for p in products if sb in (p.get("vendor") or "").lower() or sb in (p.get("title") or "").lower())
        return round(ct / len(products), 2) if products else 0.0
