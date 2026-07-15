from app.agent.text_utils import strip_markdown


def test_strip_markdown_removes_bold():
    assert strip_markdown("**두부**를 추천해요.") == "두부를 추천해요."


def test_strip_markdown_removes_inline_code_and_headers():
    assert strip_markdown("# 대체재\n`두부`를 쓰세요.") == "대체재\n두부를 쓰세요."


def test_strip_markdown_removes_blockquote_and_bullets_after_sentence():
    text = "설명입니다. > 인용문처럼 보이는 문장. - 목록처럼 보이는 문장."
    assert strip_markdown(text) == "설명입니다. 인용문처럼 보이는 문장. 목록처럼 보이는 문장."


def test_strip_markdown_leaves_plain_text_unchanged():
    assert strip_markdown("계란 대신 두부를 쓰면 돼요.") == "계란 대신 두부를 쓰면 돼요."


def test_strip_markdown_handles_empty_string():
    assert strip_markdown("") == ""


def test_strip_markdown_removes_bullet_after_paragraph_break():
    text = "두부나 유부를 추천해요!\n\n- 두부는 부드럽고 유부는 바삭해요."
    assert strip_markdown(text) == "두부나 유부를 추천해요!\n\n두부는 부드럽고 유부는 바삭해요."
