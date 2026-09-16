import os
import json
import csv
from io import StringIO
from pathlib import Path
from pydantic import BaseModel, Field

CONFIG_PATH = Path("config/brand_profile.json")


class BrandProfile(BaseModel):
    company_name: str = Field(default="Ad Fuzionz")
    founder_name: str = Field(default="Ad Fuzionz Team")
    website_url: str = Field(default="https://adfuzionz.com")
    booking_url: str = Field(default="https://adfuzionz.com/book-call")
    primary_offer: str = Field(default="High-converting video editing, performance ad campaigns, and brand growth scaling")
    tone: str = Field(default="Direct, sharp, value-focused, result-oriented founder-to-founder")
    pitch_genre: str = Field(default="Engaging & Direct")
    cta: str = Field(default="Let's hop on a brief 10-min strategy call")
    niche: str = Field(default="Creators, E-commerce, B2B SaaS, Local Businesses, Agencies")


def ensure_config_exists():
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        default_profile = BrandProfile()
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(default_profile.model_dump(), f, indent=2)


def get_brand_profile() -> BrandProfile:
    ensure_config_exists()
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return BrandProfile(**json.load(f))
    except Exception:
        return BrandProfile()


def update_brand_profile(profile: BrandProfile) -> BrandProfile:
    ensure_config_exists()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(profile.model_dump(), f, indent=2)
    return profile


def ingest_document_profile(content: bytes, filename: str) -> BrandProfile:
    ensure_config_exists()
    current = get_brand_profile().model_dump()
    fname = filename.lower()
    if fname.endswith(".json"):
        try:
            data = json.loads(content.decode("utf-8"))
            for k, v in data.items():
                if k in current:
                    current[k] = v
        except Exception:
            pass
    elif fname.endswith(".csv"):
        try:
            reader = csv.reader(StringIO(content.decode("utf-8")))
            for row in reader:
                if len(row) >= 2:
                    k = row[0].strip().lower().replace(" ", "_")
                    if k in current:
                        current[k] = row[1].strip()
        except Exception:
            pass
    return update_brand_profile(BrandProfile(**current))
