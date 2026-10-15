"""Locale layer: the three blocks forms/orders/letters can't raise themselves (they have no locale or
language concept; letters hard-codes LOCALE = "au"). All three are raised when the episode opens, before any
question is shown (ruling), and never fall back to English or to the au term:
  BK-NO-LANGUAGE     when wording would be shown to a patient whose language has no signed wording
  BK-NO-LEGAL-TERM   when an on_behalf answer is recorded under a pack with no signed decision-maker term
  BK-NO-PACK  when a letter is asked for under a pack letters doesn't have  (PENDING WORDING)"""
import os, re

from stack.paths import SIBLINGS as WORKSPACE
SIGNED = os.path.join(WORKSPACE, "wording", "forms_orders_lines_SIGNED.md")
PENDING_IDS = set()      # ids used by the stack but not yet in SIGNED; any id missing from SIGNED is PENDING WORDING
PENDING_WORDING = "PENDING WORDING"
# Signed decision-maker term per pack. Only au is backed by a signed source: forms RELATIONSHIP (signed).
LEGAL_TERM_SOURCE = {"au": "forms/messages.py RELATIONSHIP['sdm']"}


def pack_exists(pack):
    return os.path.isdir(os.path.join(WORKSPACE, "letters", "locale", pack))


LANG_CODES = {"english": "en", "german": "de", "french": "fr"}


def lang_code(language):
    """Answer files name languages ("English"); the locale layer uses codes ("en")."""
    return LANG_CODES.get(str(language).strip().lower(), str(language).strip().lower())


def signed_languages():
    """Every signed patient line in forms, orders and letters is English today."""
    return {"en"}


def _round6():
    """Signed lines, from the signed table only (no draft file is ever read)."""
    out = {}
    for p in (SIGNED,):
        try:
            # the line is the last cell of the row, whatever its column count (CL rows carry a status token first)
            for lid, rest in re.findall(r"^\|\s*([A-Z]{2,}-[A-Z0-9-]+)\s*\|(.*)$", open(p, encoding="utf-8").read(), re.M):
                cells = rest.rstrip().rstrip("|").split("|")
                out[lid] = cells[-1].strip()
        except OSError:
            pass
    return out


def line(block_id, **f):
    """Signed text for a block, filled from fields; PENDING WORDING if no line exists yet."""
    t = None if block_id in PENDING_IDS else _round6().get(block_id)
    if t is None:
        return f"{PENDING_WORDING}: {block_id}"
    f = dict(f)
    if "locale pack" in f:
        f.setdefault("locale", f["locale pack"])
    if "event_id" in f:
        f.setdefault("event id", f["event_id"])
    if "agent_name" in f and INTERNAL_ID.search(str(f["agent_name"])):
        raise ValueError("refused: [agent_name] is filled only from the display name stored at grant time, never an id")
    for k, v in f.items():
        t = t.replace(f"[{k}]", str(v))
    return t


INTERNAL_ID = re.compile(r"\bSYNTH-[\w-]+|\b[0-9a-f]{8,}\b|\bagent[-_]\w+", re.I)


def signed(line_id):
    return line_id in _round6()


def open_blocks(pack, language, needs=()):
    """Every locale block that applies when an episode opens, in a fixed order."""
    out = []
    if "pack" in needs and letter_pack_block(pack):
        out.append("BK-NO-PACK")
    if patient_wording_block(language):
        out.append("BK-NO-LANGUAGE")
    if "legal_term" in needs and legal_term_block(pack):
        out.append("BK-NO-LEGAL-TERM")
    return out


def patient_wording_block(language):
    return None if language in signed_languages() else "BK-NO-LANGUAGE"


def legal_term_block(pack):
    return None if pack in LEGAL_TERM_SOURCE else "BK-NO-LEGAL-TERM"


def letter_pack_block(pack):
    return None if pack_exists(pack) else "BK-NO-PACK"
