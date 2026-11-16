"""Reference-range helpers shared by the web pages and the PDF report."""
import re


def _num(s):
    if s is None:
        return None
    s = str(s).strip().replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def limits_for(param, gender):
    """Return (low, high) for this patient, using female overrides when present."""
    low, high = param["ref_low"], param["ref_high"]
    if (gender or "").lower().startswith("f"):
        if param["ref_low_f"] is not None or param["ref_high_f"] is not None:
            low, high = param["ref_low_f"], param["ref_high_f"]
    return low, high


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def compute_flag(value, low, high, normal_value):
    """'' = within range, 'L' = low, 'H' = high, 'A' = abnormal qualitative result."""
    if value is None or str(value).strip() == "":
        return ""
    v = _num(value)
    if v is not None and (low is not None or high is not None):
        if low is not None and v < low:
            return "L"
        if high is not None and v > high:
            return "H"
        return ""
    if normal_value and _norm(value) != _norm(normal_value):
        return "A"
    return ""


def fmt_num(x):
    if x is None:
        return ""
    return f"{x:g}"


def range_text(low, high, ref_text="", normal_value=""):
    if low is not None and high is not None:
        txt = f"{fmt_num(low)} - {fmt_num(high)}"
    elif high is not None:
        txt = f"< {fmt_num(high)}"
    elif low is not None:
        txt = f"> {fmt_num(low)}"
    else:
        txt = normal_value or ""
    if ref_text:
        txt = f"{txt}\n{ref_text}" if txt else ref_text
    return txt


FLAG_LABEL = {"": "Normal", "L": "Low", "H": "High", "A": "Abnormal"}
