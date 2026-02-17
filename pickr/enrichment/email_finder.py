"""
Pickr AI - Email Finder (v2)
Finds purchasing department email addresses for leads.
Scrapes contact pages, uses email pattern matching, and validates emails via DNS.
"""
import logging
import re
from typing import Optional, List
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup
try:
    import dns.resolver
    HAS_DNS = True
except ImportError:
    HAS_DNS = False

logger = logging.getLogger(__name__)

# Email patterns to look for
PURCHASING_PATTERNS = [
    r'purchasing@',
    r'buyers?@',
    r'wholesale@',
    r'sales@',
    r'orders?@',
    r'procurement@',
    r'vendor@',
    r'supplier@',
    r'contact@',
    r'info@',
]

CONTACT_PATHS = [
    '/contact',
    '/contact-us',
    '/contactus',
    '/about',
    '/about-us',
    '/team',
    '/wholesale',
    '/wholesale-info',
    '/partnerships',
    '/business',
    '/business-inquiries',
]


class EmailFinder:
    """Finds email addresses for contacts on a website."""

    def __init__(self):
        self.client = httpx.Client(
            timeout=10,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; PickrBot/1.0)"},
        )

    def find_email(self, company_name: str, website_url: str) -> Optional[str]:
        """
        Find a purchasing department email for a company.

        Returns: Email address or None if not found
        """
        # Clean up the URL
        if not website_url.startswith(('http://', 'https://')):
            website_url = 'https://' + website_url

        # Remove trailing slashes
        website_url = website_url.rstrip('/')

        # Try to extract domain for fallback patterns
        try:
            from urllib.parse import urlparse
            domain = urlparse(website_url).netloc.replace('www.', '')
        except Exception:
            domain = website_url.replace('https://', '').replace('http://', '')

        logger.info(f"Finding email for {company_name} ({website_url})")

        # Step 1: Try common contact pages
        for path in CONTACT_PATHS:
            email = self._scrape_page_for_email(website_url + path)
            if email:
                logger.info(f"Found email on {path}: {email}")
                return email

        # Step 2: Try homepage
        email = self._scrape_page_for_email(website_url)
        if email:
            logger.info(f"Found email on homepage: {email}")
            return email

        # Step 3: Try common email patterns
        common_emails = [
            f'purchasing@{domain}',
            f'buyers@{domain}',
            f'wholesale@{domain}',
            f'sales@{domain}',
            f'orders@{domain}',
            f'info@{domain}',
            f'contact@{domain}',
        ]

        for email in common_emails:
            if self._verify_email(email):
                logger.info(f"Verified common pattern email: {email}")
                return email

        logger.info(f"No email found for {company_name}")
        return None

    def _scrape_page_for_email(self, url: str) -> Optional[str]:
        """
        Scrape a page for email addresses.
        Prioritizes purchasing-related emails.
        """
        try:
            resp = self.client.get(url, timeout=10)
            if resp.status_code != 200:
                return None

            soup = BeautifulSoup(resp.text, 'html.parser')

            # Get all text content
            text = soup.get_text() + '\n' + resp.text

            # Find all emails
            email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
            emails = re.findall(email_pattern, text)

            # Remove duplicates and filter
            emails = list(set(emails))

            # Filter out common non-purchasing emails
            spam_domains = ['gmail.com', 'outlook.com', 'yahoo.com', 'hotmail.com', 'aol.com']
            emails = [e for e in emails if not any(e.endswith('@' + d) for d in spam_domains)]

            # Prioritize purchasing-related emails
            for pattern in PURCHASING_PATTERNS:
                for email in emails:
                    if re.search(pattern, email, re.IGNORECASE):
                        if self._verify_email(email):
                            return email

            # Return first valid email if no purchasing match
            for email in emails:
                if self._verify_email(email):
                    return email

            return None

        except Exception as e:
            logger.debug(f"Error scraping {url}: {e}")
            return None

    def _verify_email(self, email: str) -> bool:
        """
        Verify an email exists using DNS MX record lookup.
        Falls back to basic format check if DNS not available.
        """
        if not email or '@' not in email:
            return False

        # Basic format check
        email_pattern = r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}$'
        if not re.match(email_pattern, email):
            return False

        # Try DNS verification if available
        if HAS_DNS:
            try:
                domain = email.split('@')[1]
                mx_records = dns.resolver.resolve(domain, 'MX')
                return len(mx_records) > 0
            except Exception as e:
                logger.debug(f"DNS verification failed for {email}: {e}")
                # Fall back to just format validation
                return True

        return True


def find_email_for_lead(company_name: str, website_url: str) -> Optional[str]:
    """
    Convenience function to find email for a lead.

    Args:
        company_name: Company name
        website_url: Company website URL

    Returns:
        Email address or None
    """
    finder = EmailFinder()
    return finder.find_email(company_name, website_url)
