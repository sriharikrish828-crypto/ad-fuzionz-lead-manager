import os
import asyncio
import random
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any

campaign_state = {
    "is_running": False,
    "total": 0,
    "sent": 0,
    "failed": 0,
    "current_lead": "",
    "logs": []
}

SAFETY_PROFILES = {
    "conservative": (180, 300),
    "standard": (120, 240),
    "aggressive": (45, 90)
}


def calculate_schedule(count: int, safety_level: str = "standard") -> Dict[str, Any]:
    min_d, max_d = SAFETY_PROFILES.get(safety_level, SAFETY_PROFILES["standard"])
    avg_d = (min_d + max_d) / 2
    total_minutes = round((count * avg_d) / 60, 1)
    return {"lead_count": count, "average_delay_sec": int(avg_d), "estimated_duration_minutes": total_minutes}


async def send_smtp_email(to_email: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")

    if not user or not password:
        # Development simulation mode if SMTP credentials are omitted
        await asyncio.sleep(0.8)
        campaign_state["logs"].append(f"[SIMULATION] Dispatched to {to_email}")
        return True

    def _sync_send():
        msg = MIMEMultipart()
        msg["From"] = user
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            server.login(user, password)
            server.send_message(msg)

    try:
        await asyncio.to_thread(_sync_send)
        campaign_state["logs"].append(f"SENT -> {to_email}")
        return True
    except Exception as e:
        campaign_state["logs"].append(f"FAILED -> {to_email}: {str(e)}")
        return False


async def campaign_dispatcher(leads: List[dict], safety_level: str = "standard"):
    min_d, max_d = SAFETY_PROFILES.get(safety_level, SAFETY_PROFILES["standard"])
    campaign_state.update({"is_running": True, "total": len(leads), "sent": 0, "failed": 0, "logs": []})

    for lead in leads:
        email = lead.get("primary_email") or lead.get("email")
        if not email:
            continue
        campaign_state["current_lead"] = email
        ok = await send_smtp_email(email, lead.get("subject", "Quick growth thought"), lead.get("body", ""))
        if ok:
            campaign_state["sent"] += 1
        else:
            campaign_state["failed"] += 1
            
        if campaign_state["sent"] + campaign_state["failed"] < campaign_state["total"]:
            await asyncio.sleep(random.uniform(min_d, max_d))

    campaign_state["is_running"] = False
