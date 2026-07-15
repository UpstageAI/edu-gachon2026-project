import re

# CKG_MTRL_CN 형식 예: "[재료] 소고기100g| 불린미역50g| 참기름조금 [양념] 고추장2스푼| ..."
_SECTION_PATTERN = re.compile(r"\[([^\]]+)\]([^\[]*)")
_QUANTITY_START_PATTERN = re.compile(r"(\d|약간|조금|적당량|적당히|넉넉히|많이|조금씩)")
_QUANTITY_SPLIT_PATTERN = re.compile(r"^([\d/.+]+)\s*(.*)$")
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x1f]+")
_TRAILING_NOTE_PATTERN = re.compile(r"\(.*$")
# "?"는 원본 CSV 자체에 깨진 기호(원래 다른 특수문자였던 것)로 남아있는 경우이고,
# "大/中/小"는 크기 표시용 한자라 표준 재료명에는 불필요하다.
_NOISE_CHAR_PATTERN = re.compile(r"[?？大中小]")
_WHITESPACE_PATTERN = re.compile(r"\s+")


def _clean_name(name: str) -> str:
    # "당근 (볶은것)", "통후추 (" 처럼 붙는 괄호 설명은 표준 재료명에 필요 없고,
    # "|" 분리 중 괄호가 끊기는 경우도 있어 짝이 안 맞을 수 있으므로 여는 괄호부터 통째로 제거한다.
    name = _TRAILING_NOTE_PATTERN.sub("", name)
    name = _NOISE_CHAR_PATTERN.sub("", name)
    name = _WHITESPACE_PATTERN.sub(" ", name)
    return name.strip(" ,")


def _fraction_to_float(token: str) -> float | None:
    total = 0.0
    for part in token.split("+"):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            nums = [p for p in part.split("/") if p]
            if len(nums) != 2:
                return None
            try:
                total += float(nums[0]) / float(nums[1])
            except ValueError:
                return None
        else:
            try:
                total += float(part)
            except ValueError:
                return None
    return total


def parse_ingredient_item(item: str) -> dict:
    match = _QUANTITY_START_PATTERN.search(item)
    if not match:
        return {"name": _clean_name(item), "amount": None, "unit": None}

    name = _clean_name(item[: match.start()])
    quantity = item[match.start() :].strip()

    if not name:
        return {"name": _clean_name(item), "amount": None, "unit": None}

    qty_match = _QUANTITY_SPLIT_PATTERN.match(quantity)
    if qty_match and qty_match.group(1):
        amount = _fraction_to_float(qty_match.group(1))
        if amount is not None:
            unit = qty_match.group(2).strip() or None
            return {"name": name, "amount": amount, "unit": unit}

    return {"name": name, "amount": None, "unit": quantity or None}


def parse_ingredient_text(raw) -> list[dict]:
    if not isinstance(raw, str) or not raw.strip():
        return []

    raw = _CONTROL_CHAR_PATTERN.sub(" ", raw)

    items = []
    for _section_label, content in _SECTION_PATTERN.findall(raw):
        for part in content.split("|"):
            part = part.strip()
            if part:
                items.append(parse_ingredient_item(part))
    return items
