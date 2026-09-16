import os
import re
import httpx
from openai import AsyncOpenAI
from core.brand import BrandProfile

client = AsyncOpenAI(
    base_url=os.getenv("FREE_LLM_API_BASE_URL", "http://localhost:3001/v1"),
    api_key=os.getenv("FREE_LLM_API_KEY", "freellmapi-key"),
    timeout=2.0
)


def extract_tag(text: str, tag: str) -> str:
    match = re.search(rf"<{tag}>([\s\S]*?)</{tag}>", text, re.IGNORECASE)
    return match.group(1).strip().strip(' \"\'') if match else ""


def clean_reasoning_lead(text: str) -> str:
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE)
    tag_match = re.search(r"(<subject>|<body>|<dm>|<whatsapp>)", cleaned, re.IGNORECASE)
    return cleaned[tag_match.start():] if tag_match else cleaned.strip()


def clean_and_infer_industry(lead_name: str, context_info: str, brand_offer: str = "") -> dict:
    """
    Strips raw physical street addresses, phone numbers, and raw labels.
    Extracts city/area name and infers industry-specific pitch details aligned with brand.primary_offer.
    """
    raw_text = (context_info or "").strip()

    # Extract potential city name before stripping
    city = "your area"
    city_match = re.search(r"\b(Attur|Salem|Chennai|Coimbatore|Madurai|Bangalore|Hyderabad|Mumbai|Delhi|Trichy|Erode|Tirupur|Vellore)\b", lead_name + " " + raw_text, re.IGNORECASE)
    if city_match:
        city = city_match.group(1).title()

    combined_text = (lead_name + " " + raw_text).lower()

    if any(k in combined_text for k in ["jewel", "gold", "silver", "diamond"]):
        niche_label = "jewellery brands & stores"
        competitor_ref = "leading jewellery brands"
        niche_product = "jewellery & festive collections"
    elif any(k in combined_text for k in ["dental", "dentist", "teeth", "ortho"]):
        niche_label = "dental practices & clinics"
        competitor_ref = "leading dental practices"
        niche_product = "clinic treatments"
    elif any(k in combined_text for k in ["hospital", "clinic", "health", "doctor", "ent", "eye", "skin", "care"]):
        niche_label = "healthcare & medical clinics"
        competitor_ref = "top regional healthcare & specialty clinics"
        niche_product = "clinic services"
    elif any(k in combined_text for k in ["cake", "bakery", "restaurant", "food", "cafe", "hotel", "bakes", "dining"]):
        niche_label = "food & bakery brands"
        competitor_ref = "top bakery & food chains"
        niche_product = "menu items & treats"
    elif any(k in combined_text for k in ["real estate", "property", "realty", "builder", "homes"]):
        niche_label = "real estate & property firms"
        competitor_ref = "top regional real estate developers & agencies"
        niche_product = "properties & projects"
    elif any(k in combined_text for k in ["gym", "fitness", "workout", "crossfit", "yoga"]):
        niche_label = "fitness & wellness studios"
        competitor_ref = "top fitness & workout chains"
        niche_product = "membership offers"
    elif any(k in combined_text for k in ["salon", "beauty", "spa", "parlour", "hair"]):
        niche_label = "beauty & wellness salons"
        competitor_ref = "top regional salon & beauty chains"
        niche_product = "salon services"
    else:
        niche_label = "growing local businesses"
        competitor_ref = "industry-leading brands"
        niche_product = "products & services"

    # Tailor bullet points specifically to brand_offer if provided
    offer_low = (brand_offer or "").lower()
    if "web" in offer_low or "site" in offer_low or "landing page" in offer_low:
        service_desc = "building high-converting websites & digital storefronts"
        bullets = [
            f"High-converting modern website & digital storefront for {niche_label}",
            f"Mobile-first design optimized for instant customer enquiries in {city}",
            "Fast load speed & local Google Maps SEO optimization",
            "WhatsApp & online customer booking integration to convert local visitors"
        ]
    elif "video" in offer_low or "ad" in offer_low or "media" in offer_low or "smm" in offer_low:
        service_desc = "creating high-converting video ads & social media campaigns"
        bullets = [
            f"High-converting video ads showcasing premium {niche_product}",
            f"Targeted local Meta/Instagram campaigns around {city}",
            f"Dedicated landing pages built for instant lead capture",
            "Social media marketing (SMM) boosting daily store foot traffic"
        ]
    elif brand_offer and brand_offer.strip():
        service_desc = brand_offer.strip()
        bullets = [
            f"Customized {brand_offer.strip()} tailored for {niche_label}",
            f"Targeted local strategy for customer growth around {city}",
            f"High-converting customer acquisition system",
            f"Dedicated digital optimization for {lead_name}"
        ]
    else:
        service_desc = "building high-converting websites & online presence"
        bullets = [
            f"High-converting modern website & digital catalog for {niche_label}",
            f"Mobile-first design optimized for instant customer enquiries in {city}",
            "Fast load speed & Google Maps SEO optimization",
            "WhatsApp & instant booking integration to convert local visitors"
        ]

    return {
        "niche_label": niche_label,
        "competitor_ref": competitor_ref,
        "niche_product": niche_product,
        "city": city,
        "service_desc": service_desc,
        "bullets": bullets
    }


def format_pitch_by_genre(lead_name: str, brand: BrandProfile, meta: dict, genre: str, user_notes: str = "", pitch_type: str = "both") -> dict:
    city = meta["city"]
    bullets = meta["bullets"]
    niche_label = meta["niche_label"]
    competitor_ref = meta["competitor_ref"]
    service_desc = meta.get("service_desc") or (brand.primary_offer or "building high-converting websites")
    booking_url = brand.booking_url or brand.website_url

    # Clean raw notes
    raw_notes = (user_notes or "").strip()
    if any(k in raw_notes for k in ["Industry: Public", "LinkedIn profile", "Google profile", "Search Query:"]):
        raw_notes = ""
    raw_notes = re.sub(r"^Specifically regarding:\s*", "", raw_notes, flags=re.IGNORECASE).strip()
    notes_clause = f"\n\nSpecifically regarding: {raw_notes}" if raw_notes and len(raw_notes) < 60 and not raw_notes.startswith("Industry:") else ""

    genre_lower = (genre or "Competitor Case Study & Authority").lower()

    if pitch_type == "linkedin":
        li_pitch = (
            f"Hi {lead_name} 👋\n\n"
            f"Came across your brand in {city} and was really impressed by your local reputation.\n\n"
            f"I'm {brand.founder_name} from {brand.company_name}. We specialize in {service_desc}, helping {niche_label} scale online enquiries and turn local traffic into loyal customers.\n\n"
            f"Would love to connect and share a quick case study breakdown for {lead_name} if you're open to exploring options ({booking_url})!\n\n"
            f"Best regards,\n"
            f"{brand.founder_name} | {brand.company_name}"
        )
        return {
            "subject": f"Connecting with {lead_name}",
            "body": li_pitch,
            "whatsapp_pitch": li_pitch,
            "linkedin_pitch": li_pitch,
            "social_pitch": li_pitch
        }

    if pitch_type == "social":
        soc_pitch = (
            f"Hi {lead_name} 👋\n\n"
            f"Came across your brand in {city} and love what you've built!\n\n"
            f"At {brand.company_name}, we help {niche_label} scale revenue by {service_desc}.{notes_clause}\n\n"
            f"Would love to drop a quick 2-min breakdown for {lead_name}. Open to a quick chat?\n\n"
            f"👉 {booking_url}\n\n"
            f"Best regards,\n"
            f"{brand.founder_name} | {brand.company_name}"
        )
        return {
            "subject": f"Hey {lead_name}",
            "body": soc_pitch,
            "whatsapp_pitch": soc_pitch,
            "linkedin_pitch": soc_pitch,
            "social_pitch": soc_pitch
        }

    if "competitor" in genre_lower or "case study" in genre_lower or "authority" in genre_lower:
        wa_pitch = (
            f"Hi {lead_name} team 👋\n\n"
            f"I came across your profile recently — the reviews and local reputation you've built in {city} are really impressive!\n\n"
            f"I'm {brand.founder_name} from {brand.company_name}. We specialize in {service_desc} for {niche_label}, helping scale customer enquiries and revenue.{notes_clause}\n\n"
            f"Seeing your strong local trust, taking your digital presence to the next level can capture even more local buyers. If you're open to it, I can share our work details and case studies here for your reference.\n\n"
            f"Would you be open to a quick 10-minute call this week? I can share the work details & live samples first — no obligation! 😉\n\n"
            f"👉 {booking_url}\n\n"
            f"Best regards,\n"
            f"{brand.founder_name} | {brand.company_name}"
        )
        email_subj = f"Digital growth strategy idea for {lead_name}"
        email_body = (
            f"Hi {lead_name} team,\n\n"
            f"I came across your business profile recently and was really impressed by your reputation in {city}.\n\n"
            f"At {brand.company_name}, we specialize in {service_desc} for {niche_label}, helping transform local reputation into consistent online customer enquiries.{notes_clause}\n\n"
            f"Seeing your strong brand reputation, I'd love to share our case study details and website breakdown for your reference.\n\n"
            f"You can pick 10 minutes on my calendar to review our work samples whenever convenient: {booking_url}\n\n"
            f"Best regards,\n"
            f"{brand.founder_name}\n"
            f"{brand.company_name}"
        )
    elif "conversational" in genre_lower:
        wa_pitch = (
            f"Hi {lead_name} team 👋\n\n"
            f"Hope you're having a great week! I was checking out top businesses in {city} and was really impressed by your brand.\n\n"
            f"I'm {brand.founder_name} from {brand.company_name}. We help {niche_label} scale customer inquiries and online sales through {service_desc}.{notes_clause}\n\n"
            f"With your strong local trust, upgrading your digital presence can help you capture even more shoppers online.\n\n"
            f"Would you be open to a quick, no-pressure chat this week to see how we can boost your digital conversions?\n\n"
            f"You can pick a convenient time here:\n"
            f"👉 {booking_url}\n\n"
            f"Best regards,\n"
            f"{brand.founder_name} | {brand.company_name}"
        )
        email_subj = f"Quick question regarding digital growth for {lead_name}"
        email_body = (
            f"Hi {lead_name} team,\n\n"
            f"Hope you're having a productive week! I came across {lead_name} while exploring top brands in {city} and wanted to reach out.\n\n"
            f"At {brand.company_name}, we help {niche_label} scale customer inquiries through {service_desc}.{notes_clause}\n\n"
            f"We put together a custom strategy breakdown for your team. Pick 10 minutes on my calendar to review it whenever convenient: {booking_url}\n\n"
            f"Best regards,\n"
            f"{brand.founder_name}\n"
            f"{brand.company_name}"
        )
    elif "pain point" in genre_lower:
        wa_pitch = (
            f"Hi {lead_name} team 👋\n\n"
            f"Quick question — are you currently capturing all the digital enquiries and local demand around {city}?\n\n"
            f"Many top {niche_label} lose potential buyers because they lack a modern, high-converting digital experience.{notes_clause}\n\n"
            f"I'm {brand.founder_name} from {brand.company_name}. We solve this by {service_desc} specifically for {niche_label}.\n\n"
            f"💡 Here is what we would deploy for {lead_name}:\n"
            f"• {bullets[0]}\n"
            f"• {bullets[1]}\n"
            f"• {bullets[2]}\n\n"
            f"Open to a brief 10-min strategy breakdown to plug these gaps?\n\n"
            f"👉 {booking_url}\n\n"
            f"Best regards,\n"
            f"{brand.founder_name} | {brand.company_name}"
        )
        email_subj = f"Fixing missed customer enquiries for {lead_name}"
        email_body = (
            f"Hi {lead_name} team,\n\n"
            f"Are you currently capturing all the high-intent customer enquiries in {city}?\n\n"
            f"At {brand.company_name}, we help {niche_label} plug conversion gaps by {service_desc}.{notes_clause}\n\n"
            f"Here is what we would build for {lead_name}:\n"
            f"- {bullets[0]}\n"
            f"- {bullets[1]}\n"
            f"- {bullets[2]}\n\n"
            f"You can pick 10 minutes on my calendar to review our custom breakdown: {booking_url}\n\n"
            f"Best regards,\n"
            f"{brand.founder_name}\n"
            f"{brand.company_name}"
        )
    elif "punchy" in genre_lower or "short" in genre_lower:
        wa_pitch = (
            f"Hi {lead_name} team 👋\n\n"
            f"Impressed by your reputation in {city}! 🔥\n\n"
            f"I'm {brand.founder_name} from {brand.company_name}. We help {niche_label} scale local enquiries & sales by {service_desc}.{notes_clause}\n\n"
            f"Would love to share a quick 2-min custom strategy breakdown for {lead_name}! Open to a quick chat?\n\n"
            f"👉 {booking_url}\n\n"
            f"Best regards,\n"
            f"{brand.founder_name} | {brand.company_name}"
        )
        email_subj = f"Quick digital strategy idea for {lead_name}"
        email_body = (
            f"Hi {lead_name} team,\n\n"
            f"Impressed by your business reputation in {city}!\n\n"
            f"At {brand.company_name}, we help {niche_label} scale local customer enquiries by {service_desc}.{notes_clause}\n\n"
            f"Pick 10 minutes on my calendar to review a brief strategy breakdown: {booking_url}\n\n"
            f"Best regards,\n"
            f"{brand.founder_name}\n"
            f"{brand.company_name}"
        )
    else:
        # Default: Engaging & Direct
        wa_pitch = (
            f"Hi {lead_name} team 👋\n\n"
            f"I came across your business profile and noticed you've built a really strong local presence in {city}. 🔥\n\n"
            f"But there's an opportunity I noticed 👀\n\n"
            f"Your existing reputation can be turned into even more enquiries & customers by {service_desc} targeting buyers around {city}.{notes_clause}\n\n"
            f"I'm {brand.founder_name} from {brand.company_name}. We help {niche_label} build high-converting digital presence designed to turn attention into enquiries.\n\n"
            f"💡 For {lead_name}, I'd specifically look at:\n"
            f"• {bullets[0]}\n"
            f"• {bullets[1]}\n"
            f"• {bullets[2]}\n"
            f"• {bullets[3]}\n\n"
            f"I have a few ideas specifically for {lead_name} that I can show you.\n\n"
            f"Would you be open to a quick 10-minute call this week? I can share the ideas & work samples first — no obligation. 😉\n\n"
            f"👉 {booking_url}\n\n"
            f"Best regards,\n"
            f"{brand.founder_name} | {brand.company_name}"
        )
        email_subj = f"High-converting digital strategy for {lead_name}"
        email_body = (
            f"Hi {lead_name} team,\n\n"
            f"I came across your profile while reviewing top businesses in {city} and was impressed by your strong local presence.\n\n"
            f"At {brand.company_name}, we help {niche_label} turn local reputation into consistent customer enquiries by {service_desc}.{notes_clause}\n\n"
            f"💡 For {lead_name}, our strategy includes:\n"
            f"- {bullets[0]}\n"
            f"- {bullets[1]}\n"
            f"- {bullets[2]}\n"
            f"- {bullets[3]}\n\n"
            f"We put together a custom strategy breakdown for your team. You can pick 10 minutes on my calendar to review it here: {booking_url}\n\n"
            f"Best regards,\n"
            f"{brand.founder_name}\n"
            f"{brand.company_name}"
        )

    return {
        "subject": email_subj,
        "body": email_body,
        "whatsapp_pitch": wa_pitch,
        "linkedin_pitch": wa_pitch,
        "social_pitch": wa_pitch
    }



async def generate_cold_pitch(
    lead_name: str,
    brand: BrandProfile,
    channel_type: str = "web",
    context_info: str = "",
    user_notes: str = "",
    pitch_type: str = "both",
    pitch_genre: str = "Competitor Case Study & Authority"
) -> dict:
    clean_target = lead_name.strip()
    meta = clean_and_infer_industry(clean_target, context_info, brand.primary_offer)
    genre = pitch_genre or getattr(brand, "pitch_genre", "Competitor Case Study & Authority")

    # Try LLM if available
    try:
        booking_url = brand.booking_url or brand.website_url
        system_msg = f"You are {brand.founder_name} at {brand.company_name}. Primary Offer: {brand.primary_offer}. Style: {genre}. Strictly pitch the Primary Offer ({brand.primary_offer}). Never mention video ads, SMM, or unrelated services unless explicitly part of Primary Offer. Never include physical street addresses, phone numbers, or raw metadata labels."
        
        if pitch_type == "whatsapp":
            user_prompt = f"""Write an engaging human WhatsApp message for {clean_target} ({meta['niche_label']}) in {meta['city']}.
Primary Offer: {brand.primary_offer}
Style/Genre: {genre}
Competitor/Case Study Reference: {meta['competitor_ref']}
Booking URL: {booking_url}

Format:
<whatsapp>
[Human WhatsApp message with competitor case study proof, local reviews praise, and low-pressure CTA]
</whatsapp>"""
            max_tokens = 320
        elif pitch_type == "linkedin":
            user_prompt = f"""Write a LinkedIn connection note / message for {clean_target} ({meta['niche_label']}) in {meta['city']}.
Primary Offer: {brand.primary_offer}
Style/Genre: {genre}
Competitor/Case Study Reference: {meta['competitor_ref']}
Booking URL: {booking_url}

Format:
<body>
[LinkedIn connection note]
</body>"""
            max_tokens = 250
        elif pitch_type == "social":
            user_prompt = f"""Write a Social DM message for {clean_target} ({meta['niche_label']}) in {meta['city']}.
Primary Offer: {brand.primary_offer}
Style/Genre: {genre}
Competitor/Case Study Reference: {meta['competitor_ref']}
Booking URL: {booking_url}

Format:
<body>
[Social DM message]
</body>"""
            max_tokens = 250
        elif pitch_type == "email":
            user_prompt = f"""Write a cold email for {clean_target} ({meta['niche_label']}) in {meta['city']}.
Primary Offer: {brand.primary_offer}
Style/Genre: {genre}
Competitor/Case Study Reference: {meta['competitor_ref']}
Booking URL: {booking_url}

Format:
<subject>Subject line</subject>
<body>
Email body text
</body>"""
            max_tokens = 350
        else:
            user_prompt = f"""Write an email and a WhatsApp message for {clean_target} ({meta['niche_label']}) in {meta['city']}.
Primary Offer: {brand.primary_offer}
Style/Genre: {genre}
Competitor/Case Study Reference: {meta['competitor_ref']}
Booking URL: {booking_url}

Format:
<subject>Subject line</subject>
<body>Email body text</body>
<whatsapp>WhatsApp message</whatsapp>"""
            max_tokens = 600

        resp = await client.chat.completions.create(
            model="gpt-oss-120b",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            max_tokens=max_tokens
        )
        raw = clean_reasoning_lead(resp.choices[0].message.content or "")

        subject = extract_tag(raw, "subject")
        body = extract_tag(raw, "body")
        wa_tag = extract_tag(raw, "whatsapp") or extract_tag(raw, "dm")

        fallback_dict = format_pitch_by_genre(clean_target, brand, meta, genre, user_notes, pitch_type)

        if pitch_type == "whatsapp" and wa_tag:
            return {"subject": "", "body": "", "whatsapp_pitch": wa_tag, "linkedin_pitch": "", "social_pitch": ""}
        elif pitch_type == "linkedin" and body:
            return {"subject": f"Connecting with {clean_target}", "body": body, "whatsapp_pitch": "", "linkedin_pitch": body, "social_pitch": ""}
        elif pitch_type == "social" and body:
            return {"subject": f"Hey {clean_target}", "body": body, "whatsapp_pitch": "", "linkedin_pitch": "", "social_pitch": body}
        elif pitch_type == "email" and body:
            return {"subject": subject or fallback_dict["subject"], "body": body, "whatsapp_pitch": "", "linkedin_pitch": "", "social_pitch": ""}
        elif body or wa_tag:
            return {
                "subject": subject or fallback_dict["subject"],
                "body": body or fallback_dict["body"],
                "whatsapp_pitch": wa_tag or fallback_dict["whatsapp_pitch"],
                "linkedin_pitch": body or fallback_dict["linkedin_pitch"],
                "social_pitch": body or wa_tag or fallback_dict["social_pitch"]
            }
    except Exception:
        pass

    # Instant high-converting local fallback formatted by selected genre
    return get_local_fallback(clean_target, brand, channel_type, context_info, user_notes, pitch_type, genre)


def get_local_fallback(lead_name: str, brand: BrandProfile, channel_type: str, context: str, notes: str, pitch_type: str = "both", pitch_genre: str = "Competitor Case Study & Authority") -> dict:
    meta = clean_and_infer_industry(lead_name, context, brand.primary_offer)
    genre = pitch_genre or getattr(brand, "pitch_genre", "Competitor Case Study & Authority")
    res = format_pitch_by_genre(lead_name, brand, meta, genre, notes, pitch_type)

    if pitch_type == "whatsapp":
        return {"subject": "", "body": "", "whatsapp_pitch": res["whatsapp_pitch"], "linkedin_pitch": "", "social_pitch": ""}
    elif pitch_type == "linkedin":
        return {"subject": f"Connecting with {lead_name}", "body": res["body"], "whatsapp_pitch": "", "linkedin_pitch": res.get("linkedin_pitch", res["body"]), "social_pitch": ""}
    elif pitch_type == "social":
        return {"subject": f"Hey {lead_name}", "body": res["body"], "whatsapp_pitch": "", "linkedin_pitch": "", "social_pitch": res.get("social_pitch", res["body"])}
    elif pitch_type == "email":
        return {"subject": res["subject"], "body": res["body"], "whatsapp_pitch": "", "linkedin_pitch": "", "social_pitch": ""}
    else:
        return res

