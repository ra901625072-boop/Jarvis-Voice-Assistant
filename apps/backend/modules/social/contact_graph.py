"""
contact_graph.py — Unified Cross-Platform Contact Graph & Address Book.

Consolidates identities across Gmail, WhatsApp, Instagram, and LinkedIn into a single
unified entity with VIP tracking, relationship context, and interaction history.
"""
import os
import re
import difflib
import sqlite3
import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger("JARVIS.ContactGraph")

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "contacts.db")


def normalize_phone_number(phone: Optional[str]) -> str:
    """Normalizes phone number to standard digits, extracting last 10 digits for indexing/matching."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", str(phone))
    return digits[-10:] if len(digits) >= 10 else digits


class ContactGraphManager:
    """
    Manages unified cross-platform contact identities and VIP classifications.
    """

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = os.path.abspath(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS contacts (
                        id TEXT PRIMARY KEY,
                        full_name TEXT NOT NULL,
                        nickname TEXT,
                        email TEXT,
                        whatsapp_phone TEXT,
                        instagram_handle TEXT,
                        linkedin_url TEXT,
                        is_vip INTEGER DEFAULT 0,
                        relationship TEXT DEFAULT 'contact',
                        notes TEXT,
                        last_contacted_platform TEXT,
                        last_contacted_at TEXT,
                        created_at TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_name ON contacts(full_name)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_email ON contacts(email)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_phone ON contacts(whatsapp_phone)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_contact_insta ON contacts(instagram_handle)")
        finally:
            conn.close()

    def add_or_update_contact(self, data: Dict[str, Any]) -> str:
        full_name = data.get("full_name") or data.get("name", "Unknown Contact")
        nickname = data.get("nickname")
        email = data.get("email")
        whatsapp_phone = data.get("whatsapp_phone") or data.get("phone")
        instagram_handle = data.get("instagram_handle")
        if instagram_handle and instagram_handle.startswith("@"):
            instagram_handle = instagram_handle[1:]
        linkedin_url = data.get("linkedin_url")
        is_vip = 1 if data.get("is_vip") else 0
        relationship = data.get("relationship", "contact")
        notes = data.get("notes", "")
        now_str = datetime.now().isoformat()

        contact_id = data.get("id")
        conn = self._get_connection()
        try:
            with conn:
                # If no explicit ID, check if contact already exists by full_name, phone, or email
                if not contact_id:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT id FROM contacts 
                        WHERE LOWER(full_name) = LOWER(?) 
                           OR (whatsapp_phone IS NOT NULL AND whatsapp_phone = ?)
                           OR (email IS NOT NULL AND LOWER(email) = LOWER(?))
                        LIMIT 1
                    """, (full_name, whatsapp_phone or "", email or ""))
                    existing = cursor.fetchone()
                    if existing:
                        contact_id = existing["id"]
                    else:
                        contact_id = str(uuid.uuid4())

                conn.execute("""
                    INSERT INTO contacts (
                        id, full_name, nickname, email, whatsapp_phone,
                        instagram_handle, linkedin_url, is_vip, relationship,
                        notes, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        full_name=excluded.full_name,
                        nickname=COALESCE(excluded.nickname, contacts.nickname),
                        email=COALESCE(excluded.email, contacts.email),
                        whatsapp_phone=COALESCE(excluded.whatsapp_phone, contacts.whatsapp_phone),
                        instagram_handle=COALESCE(excluded.instagram_handle, contacts.instagram_handle),
                        linkedin_url=COALESCE(excluded.linkedin_url, contacts.linkedin_url),
                        is_vip=excluded.is_vip,
                        relationship=excluded.relationship,
                        notes=excluded.notes
                """, (
                    contact_id, full_name, nickname, email, whatsapp_phone,
                    instagram_handle, linkedin_url, is_vip, relationship,
                    notes, now_str
                ))
        finally:
            conn.close()

        logger.info(f"Saved contact '{full_name}' (ID: {contact_id}) in ContactGraph.")
        return contact_id

    def save_contact(self, **kwargs) -> str:
        """Alias for add_or_update_contact accepting keyword arguments."""
        return self.add_or_update_contact(kwargs)

    def resolve_contact(self, query: str) -> Optional[Dict[str, Any]]:
        """
        High-precision multi-tier contact resolution:
        1. Exact matches on full_name, nickname, email, normalized phone, instagram_handle.
        2. Normalized phone matching on last 10 digits (E.164 standard).
        3. Substring & word boundary matching.
        4. Fuzzy phonetic & Levenshtein similarity matching (threshold >= 0.70).
        """
        if not query:
            return None

        clean_q = query.strip()
        clean_handle = clean_q[1:] if clean_q.startswith("@") else clean_q
        norm_phone = normalize_phone_number(clean_q)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # Tier 1: Exact matches
            cursor.execute("""
                SELECT * FROM contacts
                WHERE LOWER(full_name) = LOWER(?)
                   OR LOWER(nickname) = LOWER(?)
                   OR LOWER(email) = LOWER(?)
                   OR whatsapp_phone = ?
                   OR LOWER(instagram_handle) = LOWER(?)
                   OR LOWER(linkedin_url) LIKE LOWER(?)
                LIMIT 1
            """, (clean_q, clean_q, clean_q, clean_q, clean_handle, f"%{clean_q}%"))
            row = cursor.fetchone()
            if row:
                return dict(row)

            # Tier 2: Normalized Phone matching (last 10 digits)
            if norm_phone and len(norm_phone) >= 7:
                cursor.execute("""
                    SELECT * FROM contacts
                    WHERE whatsapp_phone LIKE ?
                    LIMIT 1
                """, (f"%{norm_phone}%",))
                row = cursor.fetchone()
                if row:
                    return dict(row)

            # Tier 3: Substring / LIKE matching
            cursor.execute("""
                SELECT * FROM contacts
                WHERE LOWER(full_name) LIKE LOWER(?)
                   OR LOWER(nickname) LIKE LOWER(?)
                   OR LOWER(email) LIKE LOWER(?)
                   OR LOWER(instagram_handle) LIKE LOWER(?)
                LIMIT 1
            """, (f"%{clean_q}%", f"%{clean_q}%", f"%{clean_q}%", f"%{clean_handle}%"))
            row = cursor.fetchone()
            if row:
                return dict(row)

            # Tier 4: Fuzzy Levenshtein / Sequence matching
            cursor.execute("SELECT * FROM contacts")
            all_contacts = cursor.fetchall()
            best_match = None
            best_score = 0.0

            q_lower = clean_q.lower()
            for r in all_contacts:
                name = (r["full_name"] or "").lower()
                nick = (r["nickname"] or "").lower()

                # Ratio against full name, first name, and nickname
                score_name = difflib.SequenceMatcher(None, q_lower, name).ratio()
                score_first = difflib.SequenceMatcher(None, q_lower, name.split()[0]).ratio() if name else 0.0
                score_nick = difflib.SequenceMatcher(None, q_lower, nick).ratio() if nick else 0.0

                highest = max(score_name, score_first, score_nick)
                if highest > best_score and highest >= 0.70:
                    best_score = highest
                    best_match = dict(r)

            return best_match
        finally:
            conn.close()

    def resolve_contact_with_disambiguation(self, query: str) -> Dict[str, Any]:
        """
        Resolves a contact with strict 'Never Guess' disambiguation.
        If multiple contacts match the query with high confidence, returns a disambiguation status
        instead of guessing.
        """
        if not query or not query.strip():
            return {"status": "not_found", "query": query, "contact": None}

        clean_q = query.strip()
        norm_phone = normalize_phone_number(clean_q)

        conn = self._get_connection()
        try:
            cursor = conn.cursor()

            # 1. Exact Phone Match -> Definite single match
            if norm_phone and len(norm_phone) >= 10:
                cursor.execute("SELECT * FROM contacts WHERE whatsapp_phone LIKE ?", (f"%{norm_phone}%",))
                phone_rows = cursor.fetchall()
                if phone_rows:
                    unique_by_name = {r["full_name"]: dict(r) for r in phone_rows}
                    if len(unique_by_name) == 1:
                        return {"status": "exact", "contact": list(unique_by_name.values())[0]}
                    else:
                        candidates = list(unique_by_name.values())
                        cand_names = [f"{c.get('full_name')} ({c.get('whatsapp_phone') or c.get('email')})" for c in candidates]
                        return {
                            "status": "disambiguation_required",
                            "query": query,
                            "candidates": candidates,
                            "message": f"Multiple contacts found with phone '{query}': {', '.join(cand_names)}."
                        }

            # 2. Exact Name / Email / Handle match
            cursor.execute("""
                SELECT * FROM contacts
                WHERE LOWER(full_name) = LOWER(?)
                   OR LOWER(nickname) = LOWER(?)
                   OR LOWER(email) = LOWER(?)
                   OR LOWER(instagram_handle) = LOWER(?)
            """, (clean_q, clean_q, clean_q, clean_q.lstrip("@")))
            exact_rows = cursor.fetchall()
            if len(exact_rows) == 1:
                return {"status": "exact", "contact": dict(exact_rows[0])}
            elif len(exact_rows) > 1:
                candidates = [dict(r) for r in exact_rows]
                cand_names = [f"{c.get('full_name')} ({c.get('whatsapp_phone') or c.get('email')})" for c in candidates]
                return {
                    "status": "disambiguation_required",
                    "query": query,
                    "candidates": candidates,
                    "message": f"Multiple exact matches found for '{query}': {', '.join(cand_names)}. Which one did you mean?"
                }

            # 3. Fuzzy & Substring Match across all contacts
            cursor.execute("SELECT * FROM contacts")
            all_contacts = [dict(r) for r in cursor.fetchall()]
            matched_candidates = []
            q_lower = clean_q.lower()

            for r in all_contacts:
                name = (r.get("full_name") or "").lower()
                nick = (r.get("nickname") or "").lower()
                first = name.split()[0] if name else ""

                score_name = difflib.SequenceMatcher(None, q_lower, name).ratio()
                score_first = difflib.SequenceMatcher(None, q_lower, first).ratio() if first else 0.0
                score_nick = difflib.SequenceMatcher(None, q_lower, nick).ratio() if nick else 0.0

                is_sub = q_lower in name or (nick and q_lower in nick)
                highest = max(score_name, score_first, score_nick)

                if is_sub or highest >= 0.70:
                    matched_candidates.append({
                        "contact": r,
                        "score": max(highest, 0.85 if is_sub else highest)
                    })

            if not matched_candidates:
                return {"status": "not_found", "query": query, "contact": None}

            # Sort by score descending
            matched_candidates.sort(key=lambda x: x["score"], reverse=True)

            # If there's a clear single winner (score difference > 0.15 or only 1 match)
            if len(matched_candidates) == 1:
                return {"status": "exact", "contact": matched_candidates[0]["contact"]}
            elif matched_candidates[0]["score"] - matched_candidates[1]["score"] >= 0.20:
                return {"status": "exact", "contact": matched_candidates[0]["contact"]}
            else:
                # Ambiguous matches! STOP and ask for clarification.
                top_cand = [m["contact"] for m in matched_candidates[:4]]
                cand_names = [f"{c.get('full_name')} ({c.get('whatsapp_phone') or c.get('nickname') or 'No phone'})" for c in top_cand]
                return {
                    "status": "disambiguation_required",
                    "query": query,
                    "candidates": top_cand,
                    "message": f"Found multiple matching contacts for '{query}': {', '.join(cand_names)}. Please specify which person you want to contact."
                }
        finally:
            conn.close()

    def link_identity(self, contact_id: str, platform: str, identifier: str) -> bool:
        """
        Links a platform account (e.g. 'whatsapp' -> phone, 'instagram' -> handle) to a contact.
        """
        p = platform.lower()
        field_map = {
            "gmail": "email",
            "email": "email",
            "whatsapp": "whatsapp_phone",
            "instagram": "instagram_handle",
            "linkedin": "linkedin_url"
        }
        field = field_map.get(p)
        if not field:
            logger.warning(f"Unknown platform '{platform}' for identity linking.")
            return False

        clean_val = identifier.strip()
        if field == "instagram_handle" and clean_val.startswith("@"):
            clean_val = clean_val[1:]

        conn = self._get_connection()
        try:
            with conn:
                conn.execute(f"UPDATE contacts SET {field} = ? WHERE id = ?", (clean_val, contact_id))
            return True
        finally:
            conn.close()

    def get_vip_contacts(self) -> List[Dict[str, Any]]:
        """Returns all VIP contacts."""
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM contacts WHERE is_vip = 1")
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def is_vip(self, identifier: str) -> bool:
        """Checks if a given email, phone, or handle belongs to a VIP."""
        contact = self.resolve_contact(identifier)
        return bool(contact and contact.get("is_vip") == 1)

    def record_interaction(self, contact_id: str, platform: str) -> bool:
        now_str = datetime.now().isoformat()
        conn = self._get_connection()
        try:
            with conn:
                conn.execute("""
                    UPDATE contacts
                    SET last_contacted_platform = ?, last_contacted_at = ?
                    WHERE id = ?
                """, (platform, now_str, contact_id))
            return True
        finally:
            conn.close()

    def list_contacts(self, limit: int = 50) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM contacts ORDER BY is_vip DESC, full_name ASC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()
