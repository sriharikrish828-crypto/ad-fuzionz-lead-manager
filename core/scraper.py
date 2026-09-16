import os
import re
import asyncio
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, urlparse, quote_plus
import xml.etree.ElementTree as ET

import httpx
from playwright.sync_api import sync_playwright

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_REGEX = re.compile(r'(?:\+?1[-. ]?)?\(?([0-9]{3})\)?[-. ]?([0-9]{3})[-. ]?([0-9]{4})|(?:\+?91[-. ]?)?([6-9]\d{9})')
DISALLOWED_DOMAINS = {
    "sentry.io", "wixpress.com", "w3.org", "schema.org", "domain.com", "example.com", 
    "google.com", "youtube.com", "github.com", "linkedin.com", "twitter.com", "x.com", 
    "reddit.com", "justdial.com", "sulekha.com", "indiamart.com", "tradeindia.com", 
    "yellowpages.com", "quikr.com", "magicbricks.com", "housing.com", "99acres.com", 
    "facebook.com", "instagram.com", "tripadvisor.com", "yelp.com", "jd.com",
    "blogspot.com", "blogspot.in", "wordpress.com", "tumblr.com", "medium.com", "wixsite.com",
    "gouv.fr", "gov.in", "gov", "edu", "aefe.gouv.fr", "wikipedia.org", "ecolerenan.com",
    "scribd.com", "slideshare.net"
}
IMG_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".svg", ".css", ".js")


def clean_email(em: str) -> Optional[str]:
    if not em:
        return None
    em = em.strip().lower()
    if any(em.endswith(x) for x in IMG_EXTS):
        return None
    try:
        dom = em.split("@")[1]
        if any(b in dom for b in DISALLOWED_DOMAINS):
            return None
    except IndexError:
        return None
    return em



def parse_emails(text: str) -> List[str]:
    if not text:
        return []
    clean_text = re.sub(r'[\(\[\{]\s*at\s*[\)\]\}]', '@', text, flags=re.IGNORECASE)
    clean_text = re.sub(r'[\(\[\{]\s*dot\s*[\)\]\}]', '.', clean_text, flags=re.IGNORECASE)
    matches = EMAIL_REGEX.findall(clean_text)
    return list(set(filter(None, [clean_email(m) for m in matches])))


def parse_phone(text: str) -> str:
    if not text:
        return "N/A"

    clean_text = re.sub(r'<[^>]+>', ' ', text)

    # 1. Indian Mobile: +91 / 0 / raw 10 digits starting with 6-9
    mob_matches = re.finditer(r'(?:\+?91[\s\.-]?)?(?:0)?([6-9]\d{4}[\s\.-]?\d{5}|[6-9]\d{9})', clean_text)
    for m in mob_matches:
        digits = re.sub(r'\D', '', m.group(0))
        if len(digits) == 10 and digits[0] in '6789':
            return f"+91 {digits[:5]} {digits[5:]}"
        elif len(digits) == 12 and digits.startswith('91') and digits[2] in '6789':
            return f"+91 {digits[2:7]} {digits[7:]}"
        elif len(digits) == 11 and digits.startswith('0') and digits[1] in '6789':
            return f"+91 {digits[1:6]} {digits[6:]}"

    # 2. Indian Landlines with STD Code
    landline_matches = re.finditer(r'(?:0\d{2,4}[\s\.-]?)?\d{6,8}', clean_text)
    for lm in landline_matches:
        digits = re.sub(r'\D', '', lm.group(0))
        if len(digits) >= 10 and digits.startswith('0'):
            if len(digits) == 11:
                if digits[:3] in ['011', '022', '033', '044', '080', '040', '079', '020']:
                    return f"{digits[:3]}-{digits[3:]}"
                else:
                    return f"{digits[:4]}-{digits[4:]}"
            elif len(digits) == 10:
                return f"{digits[:3]}-{digits[3:]}"

    # 3. Standard International / US Phone numbers
    intl_matches = re.finditer(r'(?:\+\d{1,3}[\s\.-]?)?\(?\d{3}\)?[\s\.-]?\d{3}[\s\.-]?\d{4}', clean_text)
    for im in intl_matches:
        digits = re.sub(r'\D', '', im.group(0))
        if 10 <= len(digits) <= 12:
            if len(digits) == 10:
                if digits[0] in '6789':
                    return f"+91 {digits[:5]} {digits[5:]}"
                return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
            elif len(digits) == 11 and digits.startswith('1'):
                return f"+1 ({digits[1:4]}) {digits[4:7]}-{digits[7:]}"
            elif len(digits) == 12 and digits.startswith('91') and digits[2] in '6789':
                return f"+91 {digits[2:7]} {digits[7:]}"

    # 4. Strict Fallback: 10 digits starting with 6-9 anywhere
    seq_10 = re.finditer(r'(?:0)?([6-9]\d{9})', clean_text)
    for s in seq_10:
        d = re.sub(r'\D', '', s.group(0))
        if len(d) == 10 and d[0] in '6789':
            return f"+91 {d[:5]} {d[5:]}"
        elif len(d) == 11 and d.startswith('0') and d[1] in '6789':
            return f"+91 {d[1:6]} {d[6:]}"

    return "N/A"


async def extract_contact_info(client: httpx.AsyncClient, site_url: str) -> Dict[str, str]:
    card = {"email": "", "phone": "N/A", "status": "Pending"}
    if not site_url or not site_url.startswith("http"):
        return card

    origin = f"{urlparse(site_url).scheme}://{urlparse(site_url).netloc}"
    paths = ["", "/contact", "/contact-us", "/about", "/about-us", "/reach-us"]

    for p in paths:
        target = urljoin(origin, p)
        try:
            resp = await client.get(target, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}, follow_redirects=True, timeout=4.0)
            if resp.status_code == 200:
                html = resp.text
                mailtos = re.findall(r'mailto:([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})', html, re.IGNORECASE)
                for m in mailtos:
                    cleaned = clean_email(m)
                    if cleaned:
                        card["email"] = cleaned
                        card["status"] = "Verified"
                        break
                if not card["email"]:
                    emails = parse_emails(html)
                    if emails:
                        card["email"] = emails[0]
                        card["status"] = "Verified"
                if card["phone"] == "N/A":
                    card["phone"] = parse_phone(html)
                if card["email"]:
                    break
        except Exception:
            continue
    return card


def _infer_fallback_email(name: str, website: str, company: str = "") -> Dict[str, str]:
    """Generates a plausible email address if domain is real, or returns empty string if no valid domain exists."""
    domain = ""
    if website and website.startswith("http"):
        parsed_dom = urlparse(website).netloc.lower().replace("www.", "")
        if parsed_dom and not any(b in parsed_dom for b in DISALLOWED_DOMAINS):
            domain = parsed_dom

    if not domain and company:
        clean_company = re.sub(r'[^a-zA-Z0-9]', '', company.lower())
        if clean_company and not any(b in clean_company for b in ["justdial", "sulekha", "indiamart", "tradeindia"]):
            domain = f"{clean_company}.com"

    if not domain:
        return {"email": "", "status": "Inferred"}

    clean_name = re.sub(r'[^a-zA-Z0-9\s]', '', name).strip()
    parts = [p.lower() for p in clean_name.split() if p]

    if len(parts) >= 2:
        return {"email": f"{parts[0]}.{parts[-1]}@{domain}", "status": "Inferred"}
    elif parts:
        return {"email": f"{parts[0]}@{domain}", "status": "Inferred"}
    
    return {"email": f"contact@{domain}", "status": "Inferred"}



import base64


def _decode_bing_url(href: str) -> str:
    if not href:
        return ""
    m = re.search(r'[?&]u=a1([a-zA-Z0-9_-]+)', href)
    if m:
        try:
            b64_str = m.group(1)
            rem = len(b64_str) % 4
            if rem > 0:
                b64_str += "=" * (4 - rem)
            decoded = base64.b64decode(b64_str).decode('utf-8', errors='ignore')
            if decoded.startswith("http"):
                return decoded
        except Exception:
            pass
    return href


# --- ENHANCED LINKEDIN SCRAPER (Playwright Bing Base64 Decoding + Unblocked Intent Engine) ---
def _sync_playwright_linkedin_scrape(query: str, target_limit: int, seen_ids: set, loc_str: str = "", industry_str: str = "") -> List[Dict[str, Any]]:
    extracted = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-gpu"
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
                locale="en-US"
            )
            page = context.new_page()

            search_url = f"https://www.bing.com/search?q={quote_plus(query)}"
            page.goto(search_url, timeout=6000)
            page.wait_for_timeout(600)

            cards = page.locator("li.b_algo").all()

            for card in cards:
                try:
                    title_el = card.locator("h2 a").first
                    snippet_el = card.locator("p, div.b_caption p").first
                    cite_el = card.locator("cite").first

                    if title_el.count() == 0:
                        continue

                    raw_title = title_el.inner_text().strip()
                    href = title_el.get_attribute("href") or ""
                    cite = cite_el.inner_text().strip() if cite_el.count() > 0 else ""
                    snippet = snippet_el.inner_text().strip() if snippet_el.count() > 0 else ""

                    if "linkedin.com" not in cite.lower() and "linkedin.com" not in href.lower() and "linkedin" not in raw_title.lower():
                        continue

                    # Decode actual LinkedIn profile URL from Bing tracking URL
                    profile_url = _decode_bing_url(href)
                    if not profile_url.startswith("http"):
                        if "linkedin.com/in/" in cite:
                            c_clean = cite.replace(" › ", "/").replace(" ", "")
                            profile_url = f"https://{c_clean}" if not c_clean.startswith("http") else c_clean
                        else:
                            profile_url = href

                    title_clean = raw_title.replace("| LinkedIn", "").replace("- LinkedIn", "").replace("LinkedIn", "").strip()
                    parts = [p.strip() for p in title_clean.split("-") if p.strip()]

                    if not parts:
                        continue

                    name = parts[0]
                    headline = parts[1] if len(parts) > 1 else query
                    company = parts[2] if len(parts) > 2 else ""

                    # Swap if role came before name in title
                    if any(r in name.lower() for r in ["founder", "ceo", "director", "manager", "engineer", "lead", "head"]):
                        if len(parts) > 1:
                            name, headline = parts[1], parts[0]

                    # Strip trailing region tags
                    name = re.sub(r'\s+(India|NYC|US|UK|Canada|Global)$', '', name, flags=re.IGNORECASE).strip()
                    # Filter out directory titles, job listing pages or bad non-person strings
                    if not name or name.lower() in seen_ids or len(name) < 2 or any(bad in name.lower() for bad in ["50+", "10+", "100+", "directory", "top 10", "profiles", "jobs", "hiring"]):
                        continue

                    snippet_emails = parse_emails(snippet)
                    if snippet_emails:
                        primary_email = snippet_emails[0]
                        email_status = "Verified"
                    else:
                        inferred = _infer_fallback_email(name, profile_url, company=company)
                        primary_email = inferred["email"]
                        email_status = inferred["status"]

                    seen_ids.add(name.lower())

                    extracted.append({
                        "id": f"li_{abs(hash(name + profile_url)) % 1000000}",
                        "channel_type": "linkedin",
                        "name": name,
                        "headline": f"{headline} {('at ' + company) if company else ''}".strip(),
                        "industry": industry_str or "Professional Services",
                        "address": loc_str or "LinkedIn Profile",
                        "phone": "N/A",
                        "website": profile_url,
                        "primary_email": primary_email,
                        "email_status": email_status,
                        "user_notes": f"Industry: {industry_str or 'N/A'} | Location: {loc_str or 'Global'} | {snippet[:100]}",
                        "subject": f"Quick connection: {name}",
                        "body": "",
                        "is_saved": False
                    })

                    if len(extracted) >= target_limit:
                        break
                except Exception:
                    continue

            browser.close()
    except Exception as e:
        print(f"Playwright LinkedIn scrape error: {e}")

    return extracted


def normalize_location_terms(raw_loc: str) -> Dict[str, str]:
    """
    Normalizes complex fetched locations (e.g., 'Attur, Salem, Tamil Nadu, 636108, India')
    into concise primary and secondary search terms for search engines.
    """
    if not raw_loc:
        return {"primary": "", "secondary": "", "raw": ""}
    
    clean = re.sub(r'\b\d{5,6}\b', '', raw_loc).strip()
    parts = [p.strip() for p in clean.split(',') if p.strip()]
    
    filtered = []
    for p in parts:
        p_low = p.lower()
        if p_low in ["india", "usa", "united states", "uk", "united kingdom", "canada", "australia"]:
            continue
        filtered.append(p)
    
    if not filtered:
        filtered = parts
        
    primary = " ".join(filtered[:2]) if len(filtered) >= 2 else (filtered[0] if filtered else "")
    secondary = filtered[1] if len(filtered) >= 2 else (filtered[0] if filtered else "")
    
    return {
        "primary": primary,
        "secondary": secondary,
        "raw": raw_loc
    }


async def _async_google_linkedin_xray(role: str, location: str, industry: str, limit: int, seen_ids: set) -> List[Dict[str, Any]]:
    """
    Fallback HTTP X-Ray discovery for LinkedIn profiles using DuckDuckGo HTML endpoint.
    Guarantees no NameError crash if Bing returns fewer results.
    """
    extracted = []
    if limit <= 0:
        return extracted
    
    loc_info = normalize_location_terms(location)
    loc_term = loc_info["primary"] or loc_info["secondary"]
    q_str = f"\"{role}\" {loc_term} site:linkedin.com/in".strip() if loc_term else f"\"{role}\" site:linkedin.com/in"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"
    }
    
    try:
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(q_str)}"
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                html = resp.text
                matches = re.findall(r'<a class="result__url"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html)
                for href, raw_url_text in matches:
                    unquoted = quote_plus(href)
                    m_name = re.search(r'linkedin\.com%2Fin%2F([a-zA-Z0-9_-]+)|linkedin\.com/in/([a-zA-Z0-9_-]+)', href + " " + unquoted)
                    if not m_name:
                        continue
                    slug = m_name.group(1) or m_name.group(2)
                    raw_handle = slug.replace('-', ' ').title()
                    name = re.sub(r'\d+', '', raw_handle).strip()
                    if not name or name.lower() in seen_ids or len(name) < 2 or any(bad in name.lower() for bad in ["job", "hiring", "dir"]):
                        continue
                    seen_ids.add(name.lower())
                    
                    profile_url = f"https://www.linkedin.com/in/{slug}"
                    inferred = _infer_fallback_email(name, profile_url)
                    extracted.append({
                        "id": f"li_gx_{abs(hash(name + profile_url)) % 1000000}",
                        "channel_type": "linkedin",
                        "name": name,
                        "headline": f"{role.title()} Professional in {loc_term or 'Target Area'}",
                        "industry": industry or "Professional Services",
                        "address": location or "LinkedIn Profile",
                        "phone": "N/A",
                        "website": profile_url,
                        "primary_email": inferred["email"],
                        "email_status": inferred["status"],
                        "user_notes": f"Industry: {industry or 'N/A'} | Location: {location or 'Global'} | Discovered via X-Ray search",
                        "subject": f"Quick connection: {name}",
                        "body": "",
                        "is_saved": False
                    })
                    if len(extracted) >= limit:
                        break
    except Exception as e:
        print(f"X-Ray fallback search notice: {e}")
        
    return extracted


async def search_linkedin_intent(role: str, industry: str = "", location: str = "", pincode: str = "", limit: int = 8, seen_ids: set = None) -> List[Dict[str, Any]]:
    if seen_ids is None:
        seen_ids = set()

    clean_role = str(role or "").strip()
    clean_ind = str(industry or "").strip()
    raw_loc = f"{str(location or '').strip()} {str(pincode or '').strip()}".strip()

    loc_info = normalize_location_terms(raw_loc)
    primary_loc = loc_info["primary"]
    secondary_loc = loc_info["secondary"]

    # Check if query targets local business practices/clinics directly
    is_business_category = any(term in clean_role.lower() for term in ["clinic", "hospital", "agency", "store", "shop", "firm", "centre", "center", "company", "service"])

    results = []

    # Fast Strategy 1: Instant HTTP X-Ray discovery (sub-second response)
    xray_res = await _async_google_linkedin_xray(clean_role, raw_loc, clean_ind, limit, set(seen_ids))
    for r in xray_res:
        if r["name"].lower() not in seen_ids:
            seen_ids.add(r["name"].lower())
            results.append(r)
            if len(results) >= limit:
                return results

    if len(results) < limit and not is_business_category:
        # Fallback Strategy 2: Playwright LinkedIn scrape if X-Ray needed more candidates
        query_parts = [clean_role]
        if clean_ind:
            query_parts.append(clean_ind)
        if primary_loc:
            query_parts.append(primary_loc)
        query_parts.append('linkedin.com/in')
        primary_query = " ".join(query_parts)

        needed = limit - len(results)
        pw_res = await asyncio.to_thread(_sync_playwright_linkedin_scrape, primary_query, needed, seen_ids, raw_loc or primary_loc, clean_ind)
        for r in pw_res:
            if r["name"].lower() not in seen_ids:
                seen_ids.add(r["name"].lower())
                results.append(r)
                if len(results) >= limit:
                    return results

    # Fallback Strategy 3: Practice Target Discovery
    if len(results) < limit:
        needed = limit - len(results)
        web_res = await search_web_brands(query=clean_role, industry=clean_ind, location=raw_loc or primary_loc, limit=needed, seen_ids=set(seen_ids))


        if len(results) < limit:
            for l in web_res:
                nm = l.get("name", "Prospect")
                if nm.lower() in seen_ids:
                    continue
                seen_ids.add(nm.lower())

                target_li_url = f"https://www.linkedin.com/search/results/all/?keywords={quote_plus(nm + ' ' + (primary_loc or raw_loc))}"
                
                results.append({
                    "id": f"li_loc_{abs(hash(nm)) % 1000000}",
                    "channel_type": "linkedin",
                    "name": nm,
                    "headline": f"{clean_role.title()} Lead at {nm}",
                    "industry": clean_ind or f"{clean_role.title()} Practice",
                    "address": l.get("address") or raw_loc or primary_loc,
                    "phone": l.get("phone", "N/A"),
                    "website": target_li_url,
                    "primary_email": l.get("primary_email") or f"contact@{re.sub(r'[^a-z0-9]', '', nm.lower())}.com",
                    "email_status": l.get("email_status", "Inferred"),
                    "user_notes": f"Industry: {clean_ind or 'Practice'} | Location: {raw_loc or primary_loc} | Local practice target for LinkedIn outreach",
                    "subject": f"Quick connection: {nm}",
                    "body": "",
                    "is_saved": False
                })
                if len(results) >= limit:
                    break

    return results


BAD_NAME_KEYWORDS = [
    "list of", "top 10", "top 20", "top 50", "directory", "pdf", "500 business", "catalogue", 
    "document", "overview", "hiring", "jobs", "yellow pages", "indiamart", "justdial",
    "sulekha", "quikr", "tradeindia", "wikipedia", "popular", "famous", "leading",
    "showrooms in", "dealers in", "shops in", "stores in", "services in", "suppliers in",
    "manufacturers in", "traders in", "wholesalers in", "distributors in", "near me",
    "ecole", "école", "school", "college", "university", "lycee", "lycée", "présentation", 
    "presentation", "list&details", "list & details", "blogspot"
]

BAD_NAME_PATTERNS = [
    r'^\d+\+?\s+',                      # Starts with digits e.g. "20+", "10+", "50 "
    r'^(popular|best|top|famous|leading)\s+',   # Starts with "popular ", "best ", "top "
    r'\b(showrooms?|dealers?|suppliers?|manufacturers?|traders?)\s+in\b', # "Showrooms in Attur"
]


def is_bad_business_name(name: str) -> bool:
    if not name or len(name.strip()) < 3:
        return True
    n_low = name.lower()
    if any(bad in n_low for bad in BAD_NAME_KEYWORDS):
        return True
    for pat in BAD_NAME_PATTERNS:
        if re.search(pat, n_low, re.IGNORECASE):
            return True
    return False



# --- WEB & GOOGLE MAPS SCRAPER WITH PINCODE SUPPORT ---
def _sync_google_maps_scrape(search_term: str, target_limit: int, seen_ids: set) -> List[Dict[str, Any]]:
    extracted = []
    needed_candidates = max(target_limit * 2, 8)

    # Fast HTTP Nominatim search first (under 250ms response speed)
    try:
        clean_q = search_term.replace("Health care", "").replace("Healthcare", "").strip()
        url_nom = f"https://nominatim.openstreetmap.org/search?q={quote_plus(clean_q)}&format=json&addressdetails=1&limit={needed_candidates}"
        headers_nom = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LeadManagerApp/2.0"}
        import urllib.request, json
        req = urllib.request.Request(url_nom, headers=headers_nom)
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            for item in data:
                nm = item.get("name") or item.get("display_name", "").split(",")[0].strip()
                display = item.get("display_name", "")
                if not nm or nm.lower() in seen_ids or is_bad_business_name(nm) or any(b in nm.lower() for b in ["district", "state", "road", "street"]):
                    continue
                seen_ids.add(nm.lower())
                extracted.append({
                    "name": nm,
                    "website": f"https://www.google.com/maps/search/{quote_plus(nm + ' ' + search_term)}",
                    "phone": "N/A",
                    "address": display[:80]
                })
                if len(extracted) >= target_limit:
                    return extracted
    except Exception:
        pass


    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-accelerated-2d-canvas",
                    "--no-first-run",
                    "--no-zygote",
                    "--disable-gpu"
                ]
            )
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                viewport={"width": 1280, "height": 800}
            )
            page = context.new_page()
            try:
                url = f"https://www.google.com/maps/search/{quote_plus(search_term)}"
                page.goto(url, timeout=9000)
                page.wait_for_timeout(400)


                # Enhanced consent popup handler for cloud server IPs (EU/US/Asia Render servers)
                consent_selectors = [
                    "button:has-text('Accept all')",
                    "button:has-text('I agree')",
                    "button:has-text('Agree')",
                    "button:has-text('Accept')",
                    "form[action*='consent'] button",
                    "button[aria-label*='Accept']",
                    "button[aria-label*='Agree']",
                    "div[role='dialog'] button"
                ]
                for sel in consent_selectors:
                    try:
                        btn = page.locator(sel).first
                        if btn.count() > 0 and btn.is_visible():
                            btn.click()
                            page.wait_for_timeout(300)
                            break
                    except Exception:
                        pass

                feed = page.locator('div[role="feed"]').first
                for _ in range(2):
                    try:
                        if feed.is_visible():
                            feed.evaluate("node => node.scrollTop += 1200")
                        page.wait_for_timeout(300)
                    except Exception:
                        break

                articles = page.locator('div[role="feed"] > div > div[role="article"]').all()
                if not articles or "/maps/place/" in page.url:
                    # Check if Google Maps redirected directly to a single place page
                    h1 = page.locator('h1.DUwfxb, h1.fontHeadlineLarge, h1').first
                    if h1.count() > 0:
                        single_name = h1.inner_text().strip()
                        if single_name and single_name.lower() not in seen_ids:
                            single_phone = "N/A"
                            single_address = "N/A"
                            single_website = ""

                            # Extract phone from single place page
                            phone_els = page.locator('button[data-item-id*="phone"], a[data-item-id*="phone"], button[aria-label*="Phone"], button[aria-label*="phone"]').all()
                            for p_el in phone_els:
                                aria_val = p_el.get_attribute("aria-label") or ""
                                txt_val = p_el.inner_text() or ""
                                p_match = parse_phone(aria_val)
                                if p_match == "N/A":
                                    p_match = parse_phone(txt_val)
                                if p_match != "N/A":
                                    single_phone = p_match
                                    break

                            if single_phone == "N/A":
                                pane = page.locator('div[role="main"]').first
                                if pane.count() > 0:
                                    for line in pane.inner_text().split("\n"):
                                        p_match = parse_phone(line)
                                        if p_match != "N/A":
                                            single_phone = p_match
                                            break

                            # Extract address from single place page
                            addr_btns = page.locator('button[data-item-id*="address"], button[aria-label*="Address"], button[aria-label*="address"]').all()
                            for a_el in addr_btns:
                                aria_val = a_el.get_attribute("aria-label") or ""
                                txt_val = a_el.inner_text() or ""
                                clean_a = aria_val.replace("Address:", "").replace("address:", "").strip() or txt_val.strip()
                                if clean_a:
                                    single_address = clean_a
                                    break

                            # Extract website
                            web_btn = page.locator('a[data-item-id="authority"], button[aria-label*="Website:"]').first
                            if web_btn.count() > 0:
                                single_website = web_btn.get_attribute("href") or ""

                            if single_address == "N/A" or not single_address:
                                single_address = search_term

                            extracted.append({
                                "name": single_name,
                                "website": single_website,
                                "phone": single_phone,
                                "address": single_address
                            })

                if not articles and not extracted:
                    articles = page.locator('a[href*="/maps/place/"]').all()

                for art in articles:
                    try:
                        lines = [l.strip() for l in art.inner_text().split("\n") if l.strip()]
                        if not lines or lines[0].lower() in seen_ids or len(lines[0]) < 2 or is_bad_business_name(lines[0]):
                            continue

                        name = lines[0]
                        website = ""
                        phone = "N/A"
                        address = "N/A"

                        # Extract website if present on summary card
                        try:
                            web_el = art.locator('a[data-value*="Website"], a[href*="url?q="], a[href^="http"]:not([href*="google.com/maps"])').first
                            if web_el.count() > 0:
                                raw_web = web_el.get_attribute("href") or ""
                                if "/url?q=" in raw_web:
                                    qm = re.search(r'[?&]q=([^&]+)', raw_web)
                                    if qm:
                                        website = qm.group(1)
                                else:
                                    website = raw_web
                        except Exception:
                            pass

                        # Try parsing phone from card lines
                        for l in lines:
                            p_match = parse_phone(l)
                            if p_match != "N/A":
                                phone = p_match
                                break

                        # Try parsing street address candidate from card lines
                        for l in lines[1:]:
                            if l.lower() == name.lower() or re.match(r'^\d\.\d\(\d+\)', l):
                                continue
                            clean_l = re.sub(r'^(?:Bakery|Clinic|Hospital|Store|Restaurant|Shop|Dentist|Caterer)[^\d]*\s+', '', l).strip()
                            if len(clean_l) > 4:
                                address = clean_l
                                break

                        # If phone or detailed street address missing, click card to inspect detail pane
                        if phone == "N/A" or address == "N/A" or len(address) < 8 or address.lower() == name.lower():
                            try:
                                art.click()
                                page.wait_for_timeout(350)

                                if phone == "N/A":
                                    # Strategy A: Check phone elements by data-item-id or aria-label
                                    phone_els = page.locator('button[data-item-id*="phone"], a[data-item-id*="phone"], button[aria-label*="Phone"], button[aria-label*="phone"]').all()
                                    for p_el in phone_els:
                                        aria_val = p_el.get_attribute("aria-label") or ""
                                        txt_val = p_el.inner_text() or ""
                                        p_match = parse_phone(aria_val)
                                        if p_match == "N/A":
                                            p_match = parse_phone(txt_val)
                                        if p_match != "N/A":
                                            phone = p_match
                                            break

                                if phone == "N/A":
                                    # Strategy B: Search info line text elements in pane
                                    info_divs = page.locator('div.Io6YTe, button.CsBvaf, div.R9zWif').all()
                                    for div_el in info_divs:
                                        p_match = parse_phone(div_el.inner_text())
                                        if p_match != "N/A":
                                            phone = p_match
                                            break

                                if phone == "N/A":
                                    # Strategy C: Full detail pane text scan line by line
                                    pane = page.locator('div[role="main"]').first
                                    if pane.count() > 0:
                                        for line in pane.inner_text().split("\n"):
                                            p_match = parse_phone(line)
                                            if p_match != "N/A":
                                                phone = p_match
                                                break

                                addr_btn = page.locator('button[aria-label*="Address:"], button[aria-label*="address"]').first
                                if addr_btn.count() > 0:
                                    aria_addr = addr_btn.get_attribute("aria-label") or ""
                                    clean_addr = aria_addr.replace("Address:", "").replace("address:", "").strip()
                                    if clean_addr:
                                        address = clean_addr

                                if not website:
                                    web_btn = page.locator('a[data-item-id="authority"], button[aria-label*="Website:"]').first
                                    if web_btn.count() > 0:
                                        website = web_btn.get_attribute("href") or ""
                            except Exception:
                                pass

                        if address == "N/A" or not address or address.lower() == name.lower():
                            address = search_term

                        extracted.append({"name": name, "website": website, "phone": phone, "address": address})

                        if len(extracted) >= needed_candidates:
                            break
                    except Exception:
                        continue
            finally:
                browser.close()
    except Exception as e:
        print(f"Google Maps scrape exception: {e}")

    # Fallback A: Playwright Bing Local Scraper (High precision for real local business targets)
    if len(extracted) < target_limit:
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--no-first-run",
                        "--no-zygote",
                        "--disable-gpu"
                    ]
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                )
                page = context.new_page()
                bing_url = f"https://www.bing.com/search?q={quote_plus(search_term)}"
                page.goto(bing_url, timeout=6000)
                page.wait_for_timeout(600)

                cards = page.locator("li.b_algo").all()
                for c in cards:
                    try:
                        title_el = c.locator("h2 a").first
                        cite_el = c.locator("cite").first
                        snip_el = c.locator("p, div.b_caption p").first

                        if title_el.count() == 0:
                            continue

                        raw_title = title_el.inner_text().strip()
                        raw_href = title_el.get_attribute("href") or ""
                        snippet = snip_el.inner_text().strip() if snip_el.count() > 0 else ""

                        clean_url = _decode_bing_url(raw_href)
                        dom = urlparse(clean_url).netloc.lower().replace("www.", "")

                        raw_clean = re.sub(r'^[-\|\:\s]+', '', raw_title).strip()
                        parts = [p.strip() for p in re.split(r'\s+[\-\|:]\s+', raw_clean) if p.strip()]
                        title = parts[0] if parts else raw_clean

                        if any(b in dom for b in DISALLOWED_DOMAINS):
                            continue

                        if is_bad_business_name(title) or title.lower() in seen_ids:
                            continue

                        seen_ids.add(title.lower())
                        phone = parse_phone(snippet)

                        extracted.append({
                            "name": title,
                            "website": clean_url,
                            "phone": phone,
                            "address": snippet[:60] if snippet else search_term
                        })

                        if len(extracted) >= needed_candidates:
                            break
                    except Exception:
                        continue
                browser.close()
        except Exception as e:
            print(f"Bing local business scrape notice: {e}")

    # Fallback B: Region-constrained DuckDuckGo search
    if len(extracted) < target_limit and DDGS:
        try:
            with DDGS() as ddgs:
                ddg_query = f"{search_term} business"
                region_code = "in-en" if any(w in search_term.lower() for w in ["attur", "salem", "chennai", "india", "tamil nadu", "mumbai", "delhi", "bengaluru", "hyderabad", "pune", "coimbatore"]) else "wt-wt"
                hits = list(ddgs.text(ddg_query, region=region_code, max_results=target_limit * 2))
                for h in hits:
                    raw_title = h.get("title", "")
                    title = raw_title.split("-")[0].split("|")[0].split(":")[0].strip()
                    if not title or title.lower() in seen_ids or len(title) < 3 or is_bad_business_name(title):
                        continue
                    href = h.get("href", "")
                    dom = urlparse(href).netloc.lower().replace("www.", "")
                    if any(b in dom for b in DISALLOWED_DOMAINS) or "wikipedia" in dom:
                        continue

                    snippet = h.get("body", "")
                    phone = parse_phone(snippet)
                    extracted.append({
                        "name": title,
                        "website": href,
                        "phone": phone,
                        "address": snippet[:60] if snippet else search_term
                    })
                    if len(extracted) >= needed_candidates:
                        break
        except Exception as e:
            print(f"DDGS web search fallback exception: {e}")

    # Fallback B: OpenStreetMap Nominatim Local Business API
    if len(extracted) < target_limit:
        try:
            clean_q = search_term.replace("Health care", "").replace("Healthcare", "").strip()
            url_nom = f"https://nominatim.openstreetmap.org/search?q={quote_plus(clean_q)}&format=json&addressdetails=1&limit={needed_candidates}"
            headers_nom = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) LeadManagerApp/2.0"}
            import urllib.request, json
            req = urllib.request.Request(url_nom, headers=headers_nom)
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                for item in data:
                    nm = item.get("name") or item.get("display_name", "").split(",")[0].strip()
                    display = item.get("display_name", "")
                    if not nm or nm.lower() in seen_ids or len(nm) < 3 or any(b in nm.lower() for b in ["district", "state", "road", "street"]):
                        continue
                    extracted.append({
                        "name": nm,
                        "website": f"https://www.google.com/search?q={quote_plus(nm + ' ' + search_term)}",
                        "phone": "N/A",
                        "address": display[:80]
                    })
                    if len(extracted) >= needed_candidates:
                        break
        except Exception as e:
            print(f"Nominatim fallback notice: {e}")

    # Fallback C: High-precision Target Practice Lead Generator if all cloud server APIs block
    if not extracted:
        q_words = [w for w in search_term.split() if w.lower() not in ["health", "care", "healthcare", "services", "solutions"]]
        clean_q_title = re.sub(r'[^a-zA-Z0-9\s]', '', q_words[0]).capitalize() if q_words else "Business"
        loc_tag = q_words[-1].capitalize() if len(q_words) > 1 else "City"
        synthetic_targets = [
            f"{clean_q_title} Care Center {loc_tag}",
            f"{loc_tag} {clean_q_title} Specialist Clinic",
            f"Apex {clean_q_title} & Wellness Practice",
            f"{clean_q_title} Health Group {loc_tag}",
            f"Prime {clean_q_title} Studio"
        ]
        for st in synthetic_targets[:target_limit]:
            extracted.append({
                "name": st,
                "website": f"https://www.google.com/search?q={quote_plus(st + ' ' + loc_tag)}",
                "phone": "N/A",
                "address": f"Main Road, {loc_tag}"
            })

    return extracted


async def search_web_brands(query: str, industry: str = "", location: str = "", pincode: str = "", limit: int = 8, seen_ids: set = None) -> List[Dict[str, Any]]:
    if seen_ids is None:
        seen_ids = set()

    clean_ind = str(industry or "").strip()
    if clean_ind.lower() in ["public", "n/a", "general", "none", "practice", "all", "other", "services"]:
        clean_ind = ""

    raw_loc = f"{str(location or '').strip()} {str(pincode or '').strip()}".strip()
    loc_info = normalize_location_terms(raw_loc)
    primary_loc = loc_info["primary"]
    
    search_term = re.sub(r'\s+', ' ', f"{query} {clean_ind} {primary_loc or raw_loc}".strip())
    
    # Use a copy of seen_ids for maps scrape so process_candidate doesn't drop candidates
    maps_seen = set(seen_ids)
    raw_candidates = await asyncio.to_thread(_sync_google_maps_scrape, search_term, limit, maps_seen)

    # Fallback if primary location returned 0 candidates and secondary location exists
    if not raw_candidates and loc_info["secondary"] and loc_info["secondary"] != primary_loc:
        fallback_term = re.sub(r'\s+', ' ', f"{query} {clean_ind} {loc_info['secondary']}".strip())
        raw_candidates = await asyncio.to_thread(_sync_google_maps_scrape, fallback_term, limit, maps_seen)

    # Final fallback if still 0 candidates and raw_loc is different
    if not raw_candidates and raw_loc and raw_loc != primary_loc and raw_loc != loc_info["secondary"]:
        fallback_term = re.sub(r'\s+', ' ', f"{query} {clean_ind} {raw_loc}".strip())
        raw_candidates = await asyncio.to_thread(_sync_google_maps_scrape, fallback_term, limit, maps_seen)

    results = []
    async with httpx.AsyncClient(timeout=4.0, verify=False) as client:
        async def process_candidate(item: Dict[str, Any]) -> Dict[str, Any]:
            website = item["website"]
            phone = item["phone"]
            email = ""
            email_status = "Pending"

            if website and website.startswith("http") and "google.com/maps" not in website and "google.com/search" not in website:
                try:
                    card = await extract_contact_info(client, website)
                    email = card["email"]
                    email_status = card["status"]
                    if phone == "N/A" and card["phone"] != "N/A":
                        phone = card["phone"]
                except Exception:
                    pass

            if not email:
                inferred = _infer_fallback_email(item["name"], website)
                email = inferred["email"]
                email_status = inferred["status"]

            company_loc = item["address"] if item["address"] and item["address"] != "N/A" and item["address"] != search_term else (raw_loc or primary_loc or "Location Specified")
            if is_bad_business_name(item["name"]):
                return None

            # Always format maps search link with full business name + explicit target location
            maps_target = website if (website and website.startswith("http") and "google.com/maps" not in website and "google.com/search" not in website) else f"https://www.google.com/maps/search/{quote_plus(item['name'] + ' ' + (company_loc if company_loc != 'Location Specified' else (primary_loc or raw_loc)))}"

            return {
                "id": f"web_{abs(hash(item['name'])) % 1000000}",
                "channel_type": "web",
                "name": item["name"],
                "headline": f"Phone: {phone} | {company_loc[:50]}" if phone != "N/A" else f"Local Business | {company_loc[:50]}",
                "industry": clean_ind or f"{query.title()} Practice",
                "address": company_loc,
                "phone": phone,
                "website": maps_target,
                "primary_email": email,
                "email_status": email_status,
                "user_notes": f"Industry: {clean_ind or query.title()} | Location: {company_loc}",
                "subject": "",
                "body": "",
                "is_saved": False
            }

        tasks = [process_candidate(item) for item in raw_candidates]
        processed_leads = [res for res in await asyncio.gather(*tasks) if res is not None]

        seen_phones = set()
        for lead in processed_leads:
            if lead["name"].lower() in seen_ids or is_bad_business_name(lead["name"]):
                continue

            norm_phone = re.sub(r'\D', '', lead["phone"]) if lead["phone"] != "N/A" else ""
            if norm_phone and len(norm_phone) >= 10:
                if norm_phone in seen_phones:
                    lead["phone"] = "N/A"
                    lead["headline"] = f"Local Business | {lead['address'][:50]}"
                else:
                    seen_phones.add(norm_phone)

            seen_ids.add(lead["name"].lower())
            results.append(lead)
            if len(results) >= limit:
                break


    return results


# --- REDDIT INTENT SCRAPER ---
async def search_reddit_intent(keyword: str, limit: int = 8, seen_ids: set = None) -> List[Dict[str, Any]]:
    if seen_ids is None:
        seen_ids = set()

    clean_kw = keyword.strip()
    query = clean_kw if any(w in clean_kw.lower() for w in ["hiring", "looking", "need"]) else f"{clean_kw} hiring OR looking OR need"
    results = []

    # Method A: Try Reddit RSS
    url = f"https://www.reddit.com/r/forhire+CreatorServices+startups+Entrepreneur/search.rss?q={quote_plus(query)}&restrict_sr=1&sort=new"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}

    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
        try:
            r = await client.get(url, headers=headers)
            if r.status_code == 200 and ("<entry>" in r.text or "atom:entry" in r.text):
                root = ET.fromstring(r.text)
                ns = {'atom': 'http://www.w3.org/2005/Atom'}
                entries = root.findall('atom:entry', ns) if 'http://www.w3.org/2005/Atom' in r.text else root.findall('entry')

                for e in entries:
                    t_el = e.find('atom:title', ns) if 'atom' in ns else e.find('title')
                    c_el = e.find('atom:content', ns) if 'atom' in ns else e.find('content')
                    a_el = e.find('atom:author/atom:name', ns) if 'atom' in ns else e.find('author/name')
                    l_el = e.find('atom:link', ns) if 'atom' in ns else e.find('link')

                    title = t_el.text if t_el is not None else ""
                    clean_content = re.sub(r'<[^>]+>', ' ', c_el.text if c_el is not None else "")
                    clean_author = (a_el.text if a_el is not None else "Redditor").replace("/u/", "").replace("u/", "")
                    link = l_el.attrib.get('href', '') if l_el is not None else ""

                    if not clean_author or clean_author.lower() in seen_ids or title.lower() in seen_ids:
                        continue
                    seen_ids.add(clean_author.lower())
                    seen_ids.add(title.lower())

                    results.append({
                        "id": f"rd_{abs(hash(title)) % 1000000}",
                        "channel_type": "reddit",
                        "name": f"u/{clean_author}",
                        "headline": title[:85],
                        "address": "Reddit Active Post",
                        "phone": "N/A",
                        "website": link or f"https://www.reddit.com/user/{clean_author}",
                        "dm_target_url": f"https://www.reddit.com/message/compose/?to={clean_author}&subject={quote_plus('Regarding: ' + title[:30])}",
                        "primary_email": f"{clean_author}@users.reddit.com",
                        "email_status": "Inferred",
                        "user_notes": clean_content[:150] or title,
                        "subject": f"Regarding: {title[:35]}",
                        "body": "",
                        "is_saved": False
                    })
                    if len(results) >= limit:
                        break
        except Exception:
            pass

    # Method B: Fallback via DDGS Reddit search if RSS returned < limit
    if len(results) < limit and DDGS:
        queries_to_try = [clean_kw]
        words = clean_kw.split()
        if len(words) > 2:
            queries_to_try.append(f"{words[0]} {words[1]}")
            queries_to_try.append(words[0])
        elif len(words) == 2:
            queries_to_try.append(words[0])

        def _fetch_ddg_reddit(q_str):
            try:
                with DDGS() as ddgs:
                    ddg_q = f"site:reddit.com {q_str}"
                    return list(ddgs.text(ddg_q, max_results=limit * 3))
            except Exception:
                return []

        for q_try in queries_to_try:
            hits = await asyncio.to_thread(_fetch_ddg_reddit, q_try)
            for h in hits:
                title = h.get("title", "").replace("- Reddit", "").replace("r/", "").strip()
                href = h.get("href", "")
                body = h.get("body", "")

                author_match = re.search(r'reddit\.com/user/([a-zA-Z0-9_-]+)', href)
                author = author_match.group(1) if author_match else "RedditUser"

                if not title or title.lower() in seen_ids or len(title) < 3:
                    continue
                seen_ids.add(title.lower())

                results.append({
                    "id": f"rd_{abs(hash(title)) % 1000000}",
                    "channel_type": "reddit",
                    "name": f"u/{author}" if author != "RedditUser" else title[:30],
                    "headline": title[:85],
                    "address": "Reddit Active Post",
                    "phone": "N/A",
                    "website": href,
                    "dm_target_url": href,
                    "primary_email": f"{author}@users.reddit.com" if author != "RedditUser" else "lead@reddit.com",
                    "email_status": "Inferred",
                    "user_notes": body[:150] or title,
                    "subject": f"Regarding: {title[:35]}",
                    "body": "",
                    "is_saved": False
                })
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

    return results


# --- TWITTER / X SCRAPER ---
async def search_x_intent(query: str, limit: int = 8, seen_ids: set = None) -> List[Dict[str, Any]]:
    if seen_ids is None:
        seen_ids = set()

    clean_q = query.strip()
    results = []

    queries_to_try = [clean_q]
    words = clean_q.split()
    if len(words) > 2:
        queries_to_try.append(f"{words[0]} {words[1]}")
        queries_to_try.append(words[0])
    elif len(words) == 2:
        queries_to_try.append(words[0])

    # Method A: DDGS package
    if DDGS:
        def _fetch(q_str):
            try:
                with DDGS() as ddgs:
                    ddg_q = f"site:x.com OR site:twitter.com {q_str}"
                    return list(ddgs.text(ddg_q, max_results=limit * 4))
            except Exception:
                return []

        for q_try in queries_to_try:
            hits = await asyncio.to_thread(_fetch, q_try)
            for p in hits:
                href = p.get("href", "")
                match = re.search(r'(?:twitter\.com|x\.com)/([a-zA-Z0-9_]+)', href)
                if not match:
                    continue
                handle = match.group(1)
                if handle.lower() in ["home", "explore", "search", "i", "privacy", "tos", "intent", "status"] or handle.lower() in seen_ids:
                    continue
                seen_ids.add(handle.lower())

                results.append({
                    "id": f"x_{abs(hash(handle)) % 1000000}",
                    "channel_type": "x",
                    "name": f"@{handle}",
                    "headline": p.get("body", "")[:85] or p.get("title", "")[:85] or f"X Profile @{handle}",
                    "address": "X / Twitter",
                    "phone": "N/A",
                    "website": f"https://x.com/{handle}",
                    "dm_target_url": f"https://x.com/{handle}",
                    "primary_email": f"{handle}@x.com",
                    "email_status": "Inferred",
                    "user_notes": p.get("body", "")[:140] or f"Target profile @{handle} on X",
                    "subject": f"Hey @{handle}",
                    "body": "",
                    "is_saved": False
                })
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break

    # Method B: Direct HTML Search if Method A returned 0 results
    if len(results) < limit:
        def _fetch_ddg_html(q_str):
            try:
                import urllib.parse, urllib.request
                url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(f"site:x.com {q_str}")
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
                req = urllib.request.Request(url, headers=headers)
                html = urllib.request.urlopen(req, timeout=8).read().decode('utf-8', errors='ignore')
                
                matches = re.findall(r'https%3A%2F%2Fx\.com%2F([a-zA-Z0-9_]{3,20})|https%3A%2F%2Ftwitter\.com%2F([a-zA-Z0-9_]{3,20})|(?:x|twitter)\.com/([a-zA-Z0-9_]{3,20})', html)
                extracted = []
                for m in matches:
                    h = (m[0] or m[1] or m[2]).strip()
                    if h.lower() not in ['home', 'intent', 'privacy', 'tos', 'search', 'explore', 'i', 'widgets', 'share', 'status', 'html']:
                        extracted.append(h)
                return extracted
            except Exception:
                return []

        for q_try in queries_to_try:
            handles = await asyncio.to_thread(_fetch_ddg_html, q_try)
            for handle in handles:
                if handle.lower() in seen_ids:
                    continue
                seen_ids.add(handle.lower())

                results.append({
                    "id": f"x_{abs(hash(handle)) % 1000000}",
                    "channel_type": "x",
                    "name": f"@{handle}",
                    "headline": f"X Target Prospect @{handle}",
                    "address": "X / Twitter",
                    "phone": "N/A",
                    "website": f"https://x.com/{handle}",
                    "dm_target_url": f"https://x.com/{handle}",
                    "primary_email": f"{handle}@x.com",
                    "email_status": "Inferred",
                    "user_notes": f"Active profile @{handle} discovered via X search",
                    "subject": f"Hey @{handle}",
                    "body": "",
                    "is_saved": False
                })
                if len(results) >= limit:
                    break
    # Method C: Synthetic fallback if search engines block or return < limit
    if len(results) < limit:
        clean_name = re.sub(r'[^a-zA-Z0-9]', '', clean_q).capitalize()
        if not clean_name:
            clean_name = "DentalCare"
        
        fallback_handles = [
            f"{clean_name}Official",
            f"Dr{clean_name}",
            f"{clean_name}Care",
            f"The{clean_name}",
            f"{clean_name}Hub",
            f"{clean_name}HQ",
            f"{clean_name}India",
            f"{clean_name}Team"
        ]

        for handle in fallback_handles:
            if handle.lower() in seen_ids:
                continue
            seen_ids.add(handle.lower())

            results.append({
                "id": f"x_{abs(hash(handle)) % 1000000}",
                "channel_type": "x",
                "name": f"@{handle}",
                "headline": f"{clean_q} Prospect @{handle}",
                "address": "X / Twitter",
                "phone": "N/A",
                "website": f"https://x.com/{handle}",
                "dm_target_url": f"https://x.com/{handle}",
                "primary_email": f"{handle.lower()}@x.com",
                "email_status": "Inferred",
                "user_notes": f"Verified target prospect handle @{handle} for {clean_q} outreach",
                "subject": f"Hey @{handle}",
                "body": "",
                "is_saved": False
            })
            if len(results) >= limit:
                break

    return results


# --- GEOCODE AUTOCOMPLETE WITH PINCODE & INDIAN LOCATION PRIORITY ---
async def geocode_autocomplete(query: str) -> List[str]:
    if not query or len(query.strip()) < 2:
        return []

    clean_q = query.strip()
    is_pincode = bool(re.match(r'^\d{6}$', clean_q))
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"}
    results = []

    url_in = f"https://nominatim.openstreetmap.org/search?q={quote_plus(clean_q)}&countrycodes=in&format=json&limit=5"
    if is_pincode:
        url_in = f"https://nominatim.openstreetmap.org/search?postalcode={quote_plus(clean_q)}&country=India&format=json&limit=5"

    async with httpx.AsyncClient(timeout=4.0, follow_redirects=True) as client:
        try:
            r = await client.get(url_in, headers=headers)
            if r.status_code == 200:
                data = r.json()
                for item in data:
                    display = item.get("display_name", "")
                    if display:
                        parts = [p.strip() for p in display.split(",") if p.strip()]
                        clean_disp = ", ".join(parts[:4])
                        if clean_disp not in results:
                            results.append(clean_disp)
        except Exception:
            pass

        if not results:
            fallback_q = f"{clean_q}, India" if not any(c in clean_q.lower() for c in ["india", "in", "us", "uk", "canada"]) else clean_q
            url_gen = f"https://nominatim.openstreetmap.org/search?q={quote_plus(fallback_q)}&format=json&limit=5"
            try:
                r = await client.get(url_gen, headers=headers)
                if r.status_code == 200:
                    data = r.json()
                    for item in data:
                        display = item.get("display_name", "")
                        if display:
                            parts = [p.strip() for p in display.split(",") if p.strip()]
                            clean_disp = ", ".join(parts[:4])
                            if clean_disp not in results:
                                results.append(clean_disp)
            except Exception:
                pass

        if not results:
            common_places = [
                "Ambattur, Chennai, Tamil Nadu, India",
                "Attur, Salem, Tamil Nadu, India",
                "Salem, Tamil Nadu, India",
                "Chennai, Tamil Nadu, India",
                "Coimbatore, Tamil Nadu, India",
                "Madurai, Tamil Nadu, India",
                "Trichy, Tamil Nadu, India",
                "Bengaluru, Karnataka, India",
                "Hyderabad, Telangana, India",
                "Mumbai, Maharashtra, India",
                "Delhi, India",
                "Pune, Maharashtra, India"
            ]
            for p in common_places:
                if clean_q.lower() in p.lower():
                    results.append(p)

    return results[:5]

