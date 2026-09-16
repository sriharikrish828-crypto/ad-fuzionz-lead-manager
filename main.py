import os
print(">>> MAIN.PY LOADED FROM PATH:", __file__)
import io
import csv
import re
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, BackgroundTasks, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from pydantic import BaseModel

from core.brand import BrandProfile, get_brand_profile, update_brand_profile, ingest_document_profile, ensure_config_exists
from core.scraper import search_linkedin_intent, search_reddit_intent, search_x_intent, search_web_brands, geocode_autocomplete
from core.ai import generate_cold_pitch
from core.mailer import calculate_schedule, campaign_dispatcher, campaign_state
from core.db import init_db, save_or_update_lead, save_batch_leads, delete_saved_lead, delete_batch_leads, get_saved_leads_by_channel, get_all_saved_leads, get_all_saved_metrics, get_existing_identifiers

BASE_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_config_exists()
    await init_db()
    yield

app = FastAPI(title="Ad Fuzionz Lead Manager & Mail Dispatcher", lifespan=lifespan)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


class LeadGenerateRequest(BaseModel):
    channel: str = "web"
    query: str
    industry: Optional[str] = ""
    location: Optional[str] = ""
    limit: int = 8


class PitchSingleRequest(BaseModel):
    name: str
    channel_type: str = "web"
    headline: Optional[str] = ""
    user_notes: Optional[str] = ""
    pitch_type: Optional[str] = "both"
    pitch_genre: Optional[str] = "Competitor Case Study & Authority"


class BatchPitchRequest(BaseModel):
    leads: List[Dict[str, Any]]


class SaveLeadRequest(BaseModel):
    lead: Dict[str, Any]


class BatchSaveRequest(BaseModel):
    leads: List[Dict[str, Any]]


class BatchDeleteRequest(BaseModel):
    lead_ids: List[str]


class CampaignRunRequest(BaseModel):

    leads: List[dict]
    safety_level: str = "standard"


class PhoneNormalizeRequest(BaseModel):
    phone: str
    default_country_code: Optional[str] = "91"


def normalize_phone(raw_phone: str, default_country_code: str = "91") -> Optional[str]:
    """
    Normalizes a phone number for wa.me click-to-chat links.
    """
    if not raw_phone or raw_phone.strip().upper() == "N/A":
        return None

    digits = re.sub(r"[^0-9]", "", raw_phone)
    if not digits:
        return None

    if digits.startswith(default_country_code) and len(digits) == len(default_country_code) + 10:
        return digits

    if digits.startswith("0") and len(digits) == 11:
        digits = digits[1:]

    if len(digits) == 10:
        return f"{default_country_code}{digits}"

    if 11 <= len(digits) <= 15:
        return digits

    return None


@app.get("/", response_class=HTMLResponse)
async def serve_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={"profile": get_brand_profile()})


@app.get("/api/profile")
async def api_get_profile():
    return get_brand_profile()


@app.post("/api/profile")
async def api_update_profile(profile: BrandProfile):
    return update_brand_profile(profile)


@app.post("/api/profile/upload")
async def api_upload_profile(file: UploadFile = File(...)):
    content = await file.read()
    return {"profile": ingest_document_profile(content, file.filename)}


@app.get("/api/geo/autocomplete")
@app.get("/api/geocode")
async def api_geo_autocomplete(q: str):
    return await geocode_autocomplete(q)


@app.post("/api/leads/discover")
async def api_discover_leads(req: LeadGenerateRequest):
    print(">>> EXECUTING DISCOVER LEADS V2 HARDENED PHONE PARSER <<<")
    try:
        known = await get_existing_identifiers()
        ch = req.channel.lower()
        if ch == "linkedin":
            leads = await search_linkedin_intent(req.query, industry=req.industry or "", location=req.location or "", limit=req.limit, seen_ids=known)
        elif ch == "reddit":
            leads = await search_reddit_intent(req.query, limit=req.limit, seen_ids=known)
        elif ch == "x":
            leads = await search_x_intent(req.query, limit=req.limit, seen_ids=known)
        else:
            leads = await search_web_brands(req.query, industry=req.industry or "", location=req.location or "", limit=req.limit, seen_ids=known)
        return {"v2": True, "count": len(leads), "leads": leads}
    except Exception as e:
        print(f"Discover API Exception: {e}")
        return {"v2": True, "count": 0, "leads": [], "error": str(e)}


@app.post("/api/leads/save")
async def api_save_lead(req: SaveLeadRequest):
    await save_or_update_lead(req.lead)
    return {"status": "success"}


@app.post("/api/leads/save-batch")
async def api_save_batch(req: BatchSaveRequest):
    await save_batch_leads(req.leads)
    return {"status": "success", "count": len(req.leads)}


@app.delete("/api/leads/delete/{lead_id}")
async def api_delete_lead(lead_id: str):
    await delete_saved_lead(lead_id)
    return {"status": "deleted"}


@app.post("/api/leads/delete-batch")
async def api_delete_batch(req: BatchDeleteRequest):
    await delete_batch_leads(req.lead_ids)
    return {"status": "deleted", "count": len(req.lead_ids)}



@app.get("/api/leads/saved/{channel}")
async def api_get_saved_leads(channel: str):
    if channel.lower() == "all":
        return {"channel": "all", "leads": await get_all_saved_leads()}
    return {"channel": channel, "leads": await get_saved_leads_by_channel(channel.lower())}


@app.get("/api/leads/metrics")
async def api_get_metrics():
    return await get_all_saved_metrics()


@app.post("/api/pitch/single")
async def api_pitch_single(req: PitchSingleRequest):
    return await generate_cold_pitch(
        lead_name=req.name,
        brand=get_brand_profile(),
        channel_type=req.channel_type,
        context_info=req.headline or "",
        user_notes=req.user_notes or "",
        pitch_type=req.pitch_type or "both",
        pitch_genre=req.pitch_genre or "Competitor Case Study & Authority"
    )


@app.post("/api/pitch/batch")
async def api_pitch_batch(req: BatchPitchRequest):
    brand = get_brand_profile()
    updated = []
    for l in req.leads:
        pitch = await generate_cold_pitch(
            lead_name=l.get("name", "Prospect"),
            brand=brand,
            channel_type=l.get("channel_type", "web"),
            context_info=l.get("headline", ""),
            user_notes=l.get("user_notes", ""),
            pitch_genre=l.get("pitch_genre") or brand.pitch_genre or "Competitor Case Study & Authority"
        )
        l["subject"] = pitch["subject"]
        l["body"] = pitch["body"]
        l["whatsapp_pitch"] = pitch.get("whatsapp_pitch", "")
        updated.append(l)
    return {"leads": updated}


@app.post("/api/whatsapp/normalize")
async def api_normalize_phone(req: PhoneNormalizeRequest):
    normalized = normalize_phone(req.phone, req.default_country_code or os.getenv("DEFAULT_COUNTRY_CODE", "91"))
    if not normalized:
        raise HTTPException(status_code=400, detail="Could not resolve a valid phone number.")
    return {
        "original": req.phone,
        "normalized": normalized,
        "wa_link": f"https://wa.me/{normalized}"
    }


@app.post("/api/campaign/calculate")
async def api_calc_campaign(count: int, safety_level: str = "standard"):
    return calculate_schedule(count, safety_level)


@app.post("/api/campaign/dispatch")
async def api_dispatch_campaign(req: CampaignRunRequest, bg: BackgroundTasks):
    if campaign_state["is_running"]:
        raise HTTPException(status_code=400, detail="Campaign currently running.")
    valid = [l for l in req.leads if l.get("primary_email")]
    if not valid:
        raise HTTPException(status_code=400, detail="No deliverable email targets found.")
    bg.add_task(campaign_dispatcher, valid, req.safety_level)
    return {"message": f"Queued {len(valid)} targets for dispatch."}


@app.get("/api/campaign/status")
async def api_campaign_status():
    return campaign_state


@app.post("/api/leads/export")
async def api_export_leads(leads: List[dict]):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Channel", "Name", "Email", "Email Status", "Phone", "Website", "Industry", "Location/Address", "Headline", "Subject", "Body", "WhatsApp Script"])
    for l in leads:
        writer.writerow([
            l.get("channel_type", "web"),
            l.get("name", ""),
            l.get("primary_email", ""),
            l.get("email_status", "Inferred"),
            l.get("phone", "N/A"),
            l.get("website", ""),
            l.get("industry", ""),
            l.get("address", l.get("headline", "")),
            l.get("headline", ""),
            l.get("subject", ""),
            l.get("body", ""),
            l.get("whatsapp_pitch", "")
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=adfuzionz_leads_export.csv"}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
