"""Locale layer: the three blocks forms/orders/letters can't raise themselves (they have no locale or
language concept; letters hard-codes LOCALE = "au"). All three are raised when the episode opens, before any
question is shown (ruling), and never fall back to English or to the au term:
  BK-NO-LANGUAGE     when wording would be shown to a patient whose language has no signed wording
  BK-NO-LEGAL-TERM   when an on_behalf answer is recorded under a pack with no signed decision-maker term
  BK-NO-PACK  when a letter is asked for under a pack letters doesn't have  (PENDING WORDING)"""
import os, re

WORKSPACE = os.environ.get("STACK_WORKSPACE", "/workspace")
SIGNED = os.path.join(WORKSPACE, "wording", "forms_orders_lines_SIGNED.md")
ROUND6 = os.path.join(WORKSPACE, "wording", "forms_orders_lines_round6_DRAFT.md")
PENDING_IDS = set()      # ids used by the stack but not yet in SIGNED; any id missing from SIGNED is PENDING WORDING
PENDING_WORDING = "PENDING WORDING"
# Signed decision-maker term per pack. Only au is backed by a signed source: forms RELATIONSHIP (signed).
LEGAL_TERM_SOURCE = {"au": "forms/messages.py RELATIONSHIP['sdm']"}


def pack_exists(pack):
    return os.path.isdir(os.path.join(WORKSPACE, "letters", "locale", pack))


def signed_languages():
    """Every signed patient line in forms, orders and letters is English today."""
    return {"en"}


def _round6():
    """Signed lines: the SIGNED table first, then the round 6 file (signed in the room)."""
    out = {}
    for p in (ROUND6, SIGNED):
        try:
            out.update(re.findall(r"^\|\s*([A-Z]{2}-[A-Z0-9-]+)\s*\|\s*(.+?)\s*\|", open(p, encoding="utf-8").read(), re.M))
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
    for k, v in f.items():
        t = t.replace(f"[{k}]", str(v))
    return t


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
