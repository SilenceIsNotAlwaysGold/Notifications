import re
from datetime import datetime


_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_CHECK_CODES = "10X98765432"


def is_valid_china_identity_number(value: str) -> bool:
    normalized = value.strip().upper()
    if not re.fullmatch(r"(?:\d{15}|\d{17}[0-9X])", normalized):
        return False
    if normalized[:6] == "000000":
        return False

    if len(normalized) == 18:
        birth_date = normalized[6:14]
        sequence = normalized[14:17]
        checksum = sum(
            int(digit) * weight
            for digit, weight in zip(normalized[:17], _WEIGHTS, strict=True)
        )
        if normalized[-1] != _CHECK_CODES[checksum % 11]:
            return False
    else:
        birth_date = f"19{normalized[6:12]}"
        sequence = normalized[12:15]

    if sequence == "000":
        return False
    try:
        datetime.strptime(birth_date, "%Y%m%d")
    except ValueError:
        return False
    return True
