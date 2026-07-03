import pytest
from src.evaluator.json_parser import extract_json_from_text


def test_pure_json_passes_through():
    result = extract_json_from_text('{"items": [{"title": "test"}]}')
    assert result == {"items": [{"title": "test"}]}


def test_json_in_markdown_fence():
    text = '```json\n{"items": [{"title": "test"}]}\n```'
    result = extract_json_from_text(text)
    assert result == {"items": [{"title": "test"}]}


def test_json_in_plain_fence():
    text = '```\n{"items": [{"title": "test"}]}\n```'
    result = extract_json_from_text(text)
    assert result == {"items": [{"title": "test"}]}


def test_json_with_trailing_comma_in_array():
    text = '{"items": [{"title": "test"},]}'
    result = extract_json_from_text(text)
    assert result == {"items": [{"title": "test"}]}


def test_json_with_trailing_comma_in_object():
    text = '{"items": [{"title": "test",}]}'
    result = extract_json_from_text(text)
    assert result == {"items": [{"title": "test"}]}


def test_json_embedded_in_explanatory_text():
    text = 'Here is the result:\n\n{"items": [{"title": "test"}]}\n\nMore text.'
    result = extract_json_from_text(text)
    assert result == {"items": [{"title": "test"}]}


def test_list_at_top_level():
    text = '[{"title": "a"}, {"title": "b"}]'
    result = extract_json_from_text(text)
    assert result == [{"title": "a"}, {"title": "b"}]


def test_completely_invalid_text_raises():
    with pytest.raises(ValueError):
        extract_json_from_text("This is not JSON at all, just random text.")


def test_empty_string_raises():
    with pytest.raises(ValueError):
        extract_json_from_text("")


def test_nested_objects():
    text = '{"outer": {"inner": [1, 2, 3]}, "flag": true}'
    result = extract_json_from_text(text)
    assert result == {"outer": {"inner": [1, 2, 3]}, "flag": True}
