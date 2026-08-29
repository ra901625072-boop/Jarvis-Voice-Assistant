import logging

logger = logging.getLogger("JARVIS.LanguageDetector")

class LanguageResult:
    def __init__(self, code: str, script: str, confidence: float):
        self.code = code
        self.script = script
        self.confidence = confidence

    def to_dict(self):
        return {
            "code": self.code,
            "script": self.script,
            "confidence": self.confidence
        }

    def __repr__(self):
        return f"LanguageResult(code='{self.code}', script='{self.script}', confidence={self.confidence:.2f})"

def detect_language(text: str) -> LanguageResult:
    """
    Detects the language of a text string.
    Supports script-range detection for Hindi (Devanagari) and Gujarati (Gujarati script).
    Also supports keyword-based detection for Hinglish and Gujlish in Latin script.
    """
    if not text or not isinstance(text, str):
        return LanguageResult(code="en", script="Latin", confidence=1.0)

    # Unicode ranges
    # Devanagari: U+0900 to U+097F
    # Gujarati: U+0A80 to U+0AFF
    devanagari_count = 0
    gujarati_count = 0
    latin_count = 0
    total_eligible = 0

    for char in text:
        val = ord(char)
        if 0x0900 <= val <= 0x097F:
            devanagari_count += 1
            total_eligible += 1
        elif 0x0A80 <= val <= 0x0AFF:
            gujarati_count += 1
            total_eligible += 1
        elif (0x0041 <= val <= 0x005A) or (0x0061 <= val <= 0x007A) or (0x00C0 <= val <= 0x024F):
            latin_count += 1
            total_eligible += 1

    if total_eligible == 0:
        return LanguageResult(code="en", script="Latin", confidence=1.0)

    # Check native script dominance
    if devanagari_count > 0 and devanagari_count >= gujarati_count:
        confidence = devanagari_count / total_eligible
        return LanguageResult(code="hi", script="Devanagari", confidence=confidence)
    elif gujarati_count > 0 and gujarati_count > devanagari_count:
        confidence = gujarati_count / total_eligible
        return LanguageResult(code="gu", script="Gujarati", confidence=confidence)

    # Latin dominates (English or Hinglish/Gujlish)
    # Check Hinglish / Gujlish vocabulary
    hinglish_keywords = {
        "hai", "kya", "kar", "main", "ko", "se", "aur", "ho", "gaya", "sakte",
        "aap", "tum", "mera", "mujhe", "bhi", "toh", "haan", "na", "ka", "ki", "ke",
        "taiyar", "hoon", "achha", "theek", "kuch", "naam", "kaam", "batao", "karo", "raha", "rahi"
    }
    gujlish_keywords = {
        "che", "chhe", "nathi", "tame", "kem", "cho", "pan", "ane", "shu", "karu", "kai",
        "hu", "maru", "tamaru", "aavu", "ke", "chho", "hatha", "nava", "badhu", "saru", "motu"
    }

    words = [w.strip(".,;:!?()\"'-").lower() for w in text.split()]
    hi_word_count = sum(1 for w in words if w in hinglish_keywords)
    gu_word_count = sum(1 for w in words if w in gujlish_keywords)

    total_words = len(words)
    if total_words > 0:
        if hi_word_count > 0 and hi_word_count >= gu_word_count:
            confidence = max(0.5, min(1.0, 0.4 + (hi_word_count / total_words)))
            return LanguageResult(code="hi", script="Latin", confidence=confidence)
        elif gu_word_count > 0:
            confidence = max(0.5, min(1.0, 0.4 + (gu_word_count / total_words)))
            return LanguageResult(code="gu", script="Latin", confidence=confidence)

    return LanguageResult(code="en", script="Latin", confidence=1.0)
