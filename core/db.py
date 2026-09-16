import aiosqlite
from pathlib import Path
from typing import Dict, Any, List, Set

DB_PATH = Path("leads.db")


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id TEXT PRIMARY KEY,
                channel_type TEXT,
                name TEXT,
                headline TEXT,
                industry TEXT DEFAULT '',
                address TEXT,
                phone TEXT,
                website TEXT,
                primary_email TEXT,
                email_status TEXT DEFAULT 'Inferred',
                user_notes TEXT,
                subject TEXT,
                body TEXT,
                is_saved INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        # Ensure columns exist for migrations
        try:
            await db.execute("ALTER TABLE leads ADD COLUMN email_status TEXT DEFAULT 'Inferred'")
        except Exception:
            pass
        try:
            await db.execute("ALTER TABLE leads ADD COLUMN industry TEXT DEFAULT ''")
        except Exception:
            pass
        await db.commit()


async def get_existing_identifiers() -> Set[str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT LOWER(name) FROM leads") as cursor:
            rows = await cursor.fetchall()
            return {row[0] for row in rows}


async def save_or_update_lead(lead: Dict[str, Any]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO leads (id, channel_type, name, headline, industry, address, phone, website, primary_email, email_status, user_notes, subject, body, is_saved)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(id) DO UPDATE SET
                headline=excluded.headline,
                industry=excluded.industry,
                address=excluded.address,
                phone=excluded.phone,
                website=excluded.website,
                primary_email=excluded.primary_email,
                subject=excluded.subject,
                body=excluded.body,
                user_notes=excluded.user_notes,
                email_status=excluded.email_status,
                is_saved=1
        """, (
            lead.get("id"),
            lead.get("channel_type"),
            lead.get("name"),
            lead.get("headline", ""),
            lead.get("industry", ""),
            lead.get("address", ""),
            lead.get("phone", "N/A"),
            lead.get("website", ""),
            lead.get("primary_email", ""),
            lead.get("email_status", "Inferred"),
            lead.get("user_notes", ""),
            lead.get("subject", ""),
            lead.get("body", "")
        ))
        await db.commit()


async def save_batch_leads(leads: List[Dict[str, Any]]):
    if not leads:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        for lead in leads:
            await db.execute("""
                INSERT INTO leads (id, channel_type, name, headline, industry, address, phone, website, primary_email, email_status, user_notes, subject, body, is_saved)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                    headline=excluded.headline,
                    industry=excluded.industry,
                    address=excluded.address,
                    phone=excluded.phone,
                    website=excluded.website,
                    primary_email=excluded.primary_email,
                    subject=excluded.subject,
                    body=excluded.body,
                    user_notes=excluded.user_notes,
                    email_status=excluded.email_status,
                    is_saved=1
            """, (
                lead.get("id"),
                lead.get("channel_type"),
                lead.get("name"),
                lead.get("headline", ""),
                lead.get("industry", ""),
                lead.get("address", ""),
                lead.get("phone", "N/A"),
                lead.get("website", ""),
                lead.get("primary_email", ""),
                lead.get("email_status", "Inferred"),
                lead.get("user_notes", ""),
                lead.get("subject", ""),
                lead.get("body", "")
            ))
        await db.commit()


async def delete_saved_lead(lead_id: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        await db.commit()


async def delete_batch_leads(lead_ids: List[str]):
    if not lead_ids:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        query = f"DELETE FROM leads WHERE id IN ({','.join(['?']*len(lead_ids))})"
        await db.execute(query, lead_ids)
        await db.commit()



async def get_saved_leads_by_channel(channel: str) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM leads WHERE channel_type = ? AND is_saved = 1 ORDER BY created_at DESC",
            (channel,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_all_saved_leads() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM leads WHERE is_saved = 1 ORDER BY created_at DESC"
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


async def get_all_saved_metrics() -> Dict[str, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT channel_type, COUNT(*) FROM leads WHERE is_saved = 1 GROUP BY channel_type"
        ) as cursor:
            counts = dict(await cursor.fetchall())
        async with db.execute(
            "SELECT COUNT(*) FROM leads WHERE is_saved = 1 AND primary_email != '' AND primary_email IS NOT NULL"
        ) as cursor:
            emails_ready = (await cursor.fetchone())[0]
        async with db.execute(
            "SELECT COUNT(*) FROM leads WHERE is_saved = 1 AND email_status = 'Verified'"
        ) as cursor:
            verified_count = (await cursor.fetchone())[0]
        return {
            "total": sum(counts.values()),
            "linkedin": counts.get("linkedin", 0),
            "web": counts.get("web", 0),
            "reddit": counts.get("reddit", 0),
            "x": counts.get("x", 0),
            "whatsapp": counts.get("whatsapp", 0),
            "emails_ready": emails_ready,
            "verified_count": verified_count
        }
