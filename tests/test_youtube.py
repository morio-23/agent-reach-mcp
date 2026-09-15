from agent_reach_mcp.youtube import _vtt_to_text


def test_vtt_to_text_removes_timestamps_and_duplicate_lines() -> None:
    source = """WEBVTT

00:00:00.000 --> 00:00:02.000
<c>Hello &amp; welcome</c>

00:00:02.000 --> 00:00:04.000
<c>Hello &amp; welcome</c>

00:00:04.000 --> 00:00:06.000
Next line
"""
    assert _vtt_to_text(source) == "Hello & welcome\nNext line"
