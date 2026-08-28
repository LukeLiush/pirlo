from pirlo.core.utils.text_sanitizer import clean_llm_response


def test_clean_plain_text():
    assert (
        clean_llm_response("The capital of England is London.")
        == "The capital of England is London."
    )


def test_clean_markdown_json_block():
    raw = """```json
{
  "action": "done",
  "args": {
    "response": "The capital of England is London. It also serves as the capital of the United Kingdom."
  }
}
```"""
    expected = "The capital of England is London. It also serves as the capital of the United Kingdom."
    assert clean_llm_response(raw) == expected


def test_clean_raw_json_dict():
    raw = '{"action": "done", "args": {"response": "Tokyo"}}'
    assert clean_llm_response(raw) == "Tokyo"


def test_clean_direct_response_json():
    raw = '{"response": "Paris"}'
    assert clean_llm_response(raw) == "Paris"


def test_clean_markdown_text_block():
    raw = """```text
Berlin is the capital of Germany.
```"""
    assert clean_llm_response(raw) == "Berlin is the capital of Germany."


def test_clean_malformed_json():
    raw = "```json\n{invalid json content}\n```"
    assert clean_llm_response(raw) == "{invalid json content}"


def test_done_action_pydantic_validator():
    from pirlo.core.models.actions import DoneAction

    raw = """```json
{
  "action": "done",
  "args": {
    "response": "Rome"
  }
}
```"""
    # Test instantiation validation
    action = DoneAction(text=raw)
    assert action.text == "Rome"

    # Test assignment mutation validation (enabled by validate_assignment=True)
    action.text = """```json
{
  "action": "done",
  "args": {
    "response": "Madrid"
  }
}
```"""
    assert action.text == "Madrid"
