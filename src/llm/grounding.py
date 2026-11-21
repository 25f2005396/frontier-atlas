import re

VALID_PRICING = {"FREE", "FREEMIUM", "PAID", "ENTERPRISE"}


def _norm(s: str) -> str:
    s = s.replace("\u2019", "'").replace("\u201c", '"').replace("\u201d", '"')
    return re.sub(r"\s+", " ", s).strip().lower()


def is_grounded(value, source_text: str) -> bool:
    """True only if the value appears verbatim (ignoring case/whitespace) in the source."""
    return isinstance(value, str) and bool(value.strip()) and _norm(value) in _norm(source_text)


def validate_product(data: dict, source_text: str):
    """Return (clean_dict, None) or (None, reject_reason).
    The product name must be in the source. Pricing is kept only with verbatim evidence."""
    name = data.get("product_name")
    if not is_grounded(name, source_text):
        return None, "product_name_not_in_source"

    pricing = data.get("pricing_model")
    evidence = data.get("pricing_evidence")
    if isinstance(pricing, str):
        pricing = pricing.strip().upper()
    if pricing not in VALID_PRICING or not is_grounded(evidence, source_text):
        pricing, evidence = None, None

    return {"product_name": name.strip(), "pricing_model": pricing, "pricing_evidence": evidence}, None