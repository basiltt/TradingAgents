"""Tests for cli.announcements — Phase 1 unit tests."""

from unittest.mock import patch, MagicMock


class TestFetchAnnouncements:
    def test_success(self):
        from cli.announcements import fetch_announcements
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "announcements": ["Hello world"],
            "require_attention": True,
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("cli.announcements.requests.get", return_value=mock_resp) as m:
            result = fetch_announcements("http://test.com", timeout=5)
        assert result["announcements"] == ["Hello world"]
        assert result["require_attention"] is True
        m.assert_called_once_with("http://test.com", timeout=5)

    def test_network_error_returns_fallback(self):
        from cli.announcements import fetch_announcements
        with patch("cli.announcements.requests.get", side_effect=Exception("fail")):
            result = fetch_announcements("http://test.com", timeout=1)
        assert result["require_attention"] is False
        assert len(result["announcements"]) == 1

    def test_missing_fields_uses_defaults(self):
        from cli.announcements import fetch_announcements
        mock_resp = MagicMock()
        mock_resp.json.return_value = {}
        mock_resp.raise_for_status = MagicMock()
        with patch("cli.announcements.requests.get", return_value=mock_resp):
            result = fetch_announcements("http://test.com", timeout=1)
        assert result["require_attention"] is False
        assert len(result["announcements"]) == 1  # fallback


class TestDisplayAnnouncements:
    def test_empty_announcements_does_nothing(self):
        from cli.announcements import display_announcements
        console = MagicMock()
        display_announcements(console, {"announcements": [], "require_attention": False})
        console.print.assert_not_called()

    def test_prints_panel(self):
        from cli.announcements import display_announcements
        console = MagicMock()
        display_announcements(console, {"announcements": ["msg"], "require_attention": False})
        assert console.print.call_count == 2  # panel + empty line

    @patch("cli.announcements.getpass.getpass")
    def test_require_attention_prompts(self, mock_getpass):
        from cli.announcements import display_announcements
        console = MagicMock()
        display_announcements(console, {"announcements": ["msg"], "require_attention": True})
        mock_getpass.assert_called_once()
