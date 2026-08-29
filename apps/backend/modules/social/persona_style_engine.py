"""
persona_style_engine.py — Personalized Writing Voice & Style Adaptation Engine.

Adapts generated social media messages and email drafts to match Akshay's personal
communication style across different platforms and relationship contexts.
"""
import logging
from typing import Dict, Any, Optional, List

logger = logging.getLogger("JARVIS.PersonaStyleEngine")


class PersonaStyleEngine:
    """
    Manages channel-specific voice characteristics, formatting conventions,
    and tone adaptation for social media interactions.
    """

    DEFAULT_PROFILES: Dict[str, Dict[str, Any]] = {
        "gmail": {
            "tone": "professional, clear, polite, structured",
            "brevity": "moderate",
            "emoji_usage": "none",
            "sign_offs": ["Thanks,\nAkshay", "Best regards,\nAkshay", "Regards,\nAkshay"],
            "greeting_style": "Hi {name},"
        },
        "whatsapp": {
            "tone": "direct, friendly, casual, responsive",
            "brevity": "high",
            "emoji_usage": "contextual (e.g. 👍, 🙌, ✅)",
            "sign_offs": ["", "- Akshay"],
            "greeting_style": "Hey {name}"
        },
        "linkedin": {
            "tone": "insightful, visionary, professional thought-leadership",
            "brevity": "structured with clear takeaways",
            "emoji_usage": "strategic bullet points (e.g. 🚀, 💡, 📌)",
            "sign_offs": ["\nWhat are your thoughts on this?\n#AI #Tech #Innovation"],
            "greeting_style": ""
        },
        "instagram": {
            "tone": "casual, warm, concise, engaging",
            "brevity": "high",
            "emoji_usage": "natural (e.g. 🔥, 🙌, 💯)",
            "sign_offs": [""],
            "greeting_style": "Hey {name}!"
        }
    }

    def __init__(self, custom_profiles: Optional[Dict[str, Dict[str, Any]]] = None):
        self.profiles = dict(self.DEFAULT_PROFILES)
        if custom_profiles:
            self.profiles.update(custom_profiles)

    def get_style_profile(self, platform: str) -> Dict[str, Any]:
        return self.profiles.get(platform.lower(), self.profiles["gmail"])

    def update_style_profile(self, platform: str, updates: Dict[str, Any]) -> None:
        p = platform.lower()
        if p not in self.profiles:
            self.profiles[p] = dict(self.profiles["gmail"])
        self.profiles[p].update(updates)
        logger.info(f"Updated persona style profile for '{platform}'.")

    def build_system_prompt_guidelines(
        self,
        platform: str,
        recipient_name: Optional[str] = None,
        relationship: Optional[str] = None,
        context: Optional[str] = None
    ) -> str:
        """
        Builds a comprehensive LLM instruction prompt to match Akshay's writing style.
        """
        profile = self.get_style_profile(platform)
        p_name = platform.capitalize()

        guidelines = [
            f"You are drafting a message on behalf of Akshay for {p_name}.",
            f"- Tone: {profile.get('tone')}.",
            f"- Brevity: {profile.get('brevity')}.",
            f"- Emoji usage: {profile.get('emoji_usage')}."
        ]

        if recipient_name:
            guidelines.append(f"- Recipient Name: {recipient_name}")
        if relationship:
            guidelines.append(f"- Relationship context: {relationship} (adjust formality accordingly)")
        if context:
            guidelines.append(f"- Interaction Context: {context}")

        guidelines.append(
            "- Always sound natural and authentic. Never use overly robotic or generic corporate jargon unless formal email."
        )
        return "\n".join(guidelines)

    def format_draft(
        self,
        platform: str,
        content: str,
        recipient_name: Optional[str] = None,
        include_sign_off: bool = True
    ) -> str:
        """
        Applies greeting and sign-off conventions to a generated draft.
        """
        profile = self.get_style_profile(platform)
        p = platform.lower()
        formatted = content.strip()

        # Apply sign-off for Gmail if missing
        if p == "gmail" and include_sign_off:
            sign_offs = profile.get("sign_offs", [])
            default_sign_off = sign_offs[0] if sign_offs else "Best regards,\nAkshay"
            if not any(so.split("\n")[-1].lower() in formatted.lower() for so in sign_offs):
                formatted = f"{formatted}\n\n{default_sign_off}"

        return formatted
