from __future__ import annotations

import re

import pandas as pd


EMAIL_PATTERN = re.compile(
    r"^(?=.{1,254}$)[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"(?=.{1,253}$)(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,63}$"
)


def is_valid_email(value: object) -> bool:
    if value is None or pd.isna(value):
        return True
    text = str(value).strip()
    if not text:
        return True
    return bool(EMAIL_PATTERN.fullmatch(text))


def invalid_email_mask(series: pd.Series) -> pd.Series:
    return ~series.map(is_valid_email)


def parse_date_value(value: object) -> pd.Timestamp | None:
    if value is None or pd.isna(value) or not str(value).strip():
        return None
    try:
        parsed = pd.to_datetime(value, errors="raise", dayfirst=True)
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(parsed, pd.DatetimeIndex):
        return None
    return pd.Timestamp(parsed)
