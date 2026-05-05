"""Tests for tradingagents.dataflows.yfinance_news — Phase 1 unit tests."""

from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest


class TestExtractArticleData:
    def test_nested_content_structure(self):
        from tradingagents.dataflows.yfinance_news import _extract_article_data
        article = {
            "content": {
                "title": "Market Rally",
                "summary": "Stocks surged today",
                "provider": {"displayName": "Reuters"},
                "canonicalUrl": {"url": "https://example.com/article"},
                "pubDate": "2025-01-10T14:30:00Z",
            }
        }
        data = _extract_article_data(article)
        assert data["title"] == "Market Rally"
        assert data["summary"] == "Stocks surged today"
        assert data["publisher"] == "Reuters"
        assert data["link"] == "https://example.com/article"
        assert data["pub_date"] is not None

    def test_nested_with_click_through_url(self):
        from tradingagents.dataflows.yfinance_news import _extract_article_data
        article = {
            "content": {
                "title": "Test",
                "clickThroughUrl": {"url": "https://click.example.com"},
            }
        }
        data = _extract_article_data(article)
        assert data["link"] == "https://click.example.com"

    def test_nested_invalid_pubdate(self):
        from tradingagents.dataflows.yfinance_news import _extract_article_data
        article = {"content": {"title": "T", "pubDate": "not-a-date"}}
        data = _extract_article_data(article)
        assert data["pub_date"] is None

    def test_nested_missing_fields(self):
        from tradingagents.dataflows.yfinance_news import _extract_article_data
        article = {"content": {}}
        data = _extract_article_data(article)
        assert data["title"] == "No title"
        assert data["publisher"] == "Unknown"

    def test_flat_structure(self):
        from tradingagents.dataflows.yfinance_news import _extract_article_data
        article = {
            "title": "Flat Article",
            "summary": "Summary here",
            "publisher": "Bloomberg",
            "link": "https://example.com",
        }
        data = _extract_article_data(article)
        assert data["title"] == "Flat Article"
        assert data["publisher"] == "Bloomberg"
        assert data["pub_date"] is None

    def test_flat_missing_fields(self):
        from tradingagents.dataflows.yfinance_news import _extract_article_data
        data = _extract_article_data({})
        assert data["title"] == "No title"
        assert data["publisher"] == "Unknown"


class TestGetNewsYfinance:
    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    @patch("tradingagents.dataflows.yfinance_news.yf.Ticker")
    def test_no_news(self, mock_cls, mock_retry):
        from tradingagents.dataflows.yfinance_news import get_news_yfinance
        mock_retry.return_value = []
        result = get_news_yfinance("AAPL", "2025-01-01", "2025-01-05")
        assert "No news found" in result

    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    @patch("tradingagents.dataflows.yfinance_news.yf.Ticker")
    def test_happy_path(self, mock_cls, mock_retry):
        from tradingagents.dataflows.yfinance_news import get_news_yfinance
        mock_retry.return_value = [
            {"content": {"title": "Apple Earnings", "summary": "Beat expectations",
                         "provider": {"displayName": "Reuters"},
                         "pubDate": "2025-01-03T10:00:00Z"}}
        ]
        result = get_news_yfinance("AAPL", "2025-01-01", "2025-01-05")
        assert "Apple Earnings" in result
        assert "AAPL News" in result

    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    @patch("tradingagents.dataflows.yfinance_news.yf.Ticker")
    def test_date_filtering_excludes_out_of_range(self, mock_cls, mock_retry):
        from tradingagents.dataflows.yfinance_news import get_news_yfinance
        mock_retry.return_value = [
            {"content": {"title": "Old News", "pubDate": "2024-06-01T10:00:00Z"}}
        ]
        result = get_news_yfinance("AAPL", "2025-01-01", "2025-01-05")
        assert "No news found for AAPL between" in result

    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    @patch("tradingagents.dataflows.yfinance_news.yf.Ticker")
    def test_articles_without_pubdate_pass_through(self, mock_cls, mock_retry):
        from tradingagents.dataflows.yfinance_news import get_news_yfinance
        mock_retry.return_value = [{"title": "No Date Article", "publisher": "AP"}]
        result = get_news_yfinance("AAPL", "2025-01-01", "2025-01-05")
        assert "No Date Article" in result

    @patch("tradingagents.dataflows.yfinance_news.yf.Ticker", side_effect=RuntimeError("network"))
    def test_exception_returns_error(self, mock_cls):
        from tradingagents.dataflows.yfinance_news import get_news_yfinance
        result = get_news_yfinance("AAPL", "2025-01-01", "2025-01-05")
        assert "Error fetching news" in result


class TestGetGlobalNewsYfinance:
    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    def test_no_news_found(self, mock_retry):
        from tradingagents.dataflows.yfinance_news import get_global_news_yfinance
        mock_search = MagicMock()
        mock_search.news = []
        mock_retry.return_value = mock_search
        result = get_global_news_yfinance("2025-01-10")
        assert "No global news found" in result

    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    def test_happy_path_with_nested(self, mock_retry):
        from tradingagents.dataflows.yfinance_news import get_global_news_yfinance
        mock_search = MagicMock()
        mock_search.news = [
            {"content": {"title": "Fed Rates", "summary": "Rates held",
                         "provider": {"displayName": "Reuters"},
                         "pubDate": "2025-01-09T10:00:00Z"}},
        ]
        mock_retry.return_value = mock_search
        result = get_global_news_yfinance("2025-01-10", look_back_days=7)
        assert "Fed Rates" in result
        assert "Global Market News" in result

    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    def test_deduplication(self, mock_retry):
        from tradingagents.dataflows.yfinance_news import get_global_news_yfinance
        mock_search = MagicMock()
        mock_search.news = [
            {"content": {"title": "Same Title", "provider": {"displayName": "A"}}},
            {"content": {"title": "Same Title", "provider": {"displayName": "B"}}},
        ]
        mock_retry.return_value = mock_search
        result = get_global_news_yfinance("2025-01-10")
        assert result.count("Same Title") == 1

    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    def test_lookahead_guard_skips_future(self, mock_retry):
        from tradingagents.dataflows.yfinance_news import get_global_news_yfinance
        mock_search = MagicMock()
        mock_search.news = [
            {"content": {"title": "Future Article",
                         "pubDate": "2026-06-01T10:00:00Z",
                         "provider": {"displayName": "AP"}}},
        ]
        mock_retry.return_value = mock_search
        result = get_global_news_yfinance("2025-01-10")
        assert "Future Article" not in result or "No global news" in result

    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    def test_flat_articles(self, mock_retry):
        from tradingagents.dataflows.yfinance_news import get_global_news_yfinance
        mock_search = MagicMock()
        mock_search.news = [
            {"title": "Flat News", "publisher": "Bloomberg", "link": "https://x.com"},
        ]
        mock_retry.return_value = mock_search
        result = get_global_news_yfinance("2025-01-10")
        assert "Flat News" in result

    @patch("tradingagents.dataflows.yfinance_news.yf_retry", side_effect=RuntimeError("fail"))
    def test_exception(self, mock_retry):
        from tradingagents.dataflows.yfinance_news import get_global_news_yfinance
        result = get_global_news_yfinance("2025-01-10")
        assert "Error fetching global news" in result

    @patch("tradingagents.dataflows.yfinance_news.yf_retry")
    def test_limit_respected(self, mock_retry):
        from tradingagents.dataflows.yfinance_news import get_global_news_yfinance
        mock_search = MagicMock()
        mock_search.news = [
            {"title": f"Article {i}", "publisher": "AP"} for i in range(20)
        ]
        mock_retry.return_value = mock_search
        result = get_global_news_yfinance("2025-01-10", limit=3)
        assert result.count("###") <= 3
