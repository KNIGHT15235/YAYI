"""Offline regressions for the official-source research news collection path."""
import asyncio
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend/app"))
from config.industry_config import get_industry_config
from models.news import IndustryNews, NewsCollectionTask
from service.news_collection_service import NewsCollectionService, NewsSearchError
from router.news_router import trigger_collection


class Query:
    def __init__(self, db, model):
        self.db, self.model, self.filters = db, model, []

    def filter(self, *filters):
        self.filters.extend(filters)
        return self

    def all(self):
        return [row for row in self.db.rows + self.db.pending if isinstance(row, self.model)
                and all(self.matches(term, row) for term in self.filters)]

    @classmethod
    def matches(cls, term, row):
        name = getattr(getattr(term, 'operator', None), '__name__', '')
        if hasattr(term, 'clauses'):
            values = [cls.matches(child, row) for child in term.clauses]
            return any(values) if name == 'or_' else all(values)
        if hasattr(term, 'element') and not hasattr(term, 'left'):
            value = cls.matches(term.element, row)
            return not value if name == 'inv' else value
        left = getattr(row, term.left.name)
        right = getattr(term.right, 'value', None)
        if name == 'eq': return left == right
        if name == 'is_': return left is right
        if name == 'in_op': return left in right
        if name == 'not_in_op': return left not in right
        if getattr(term.operator, 'opstring', '') == '~*':
            return bool(re.search(right, str(left or ''), re.I))
        raise AssertionError('Unexpected test query predicate: ' + str(term))

    def order_by(self, *terms):
        self.db.ordering = [str(term) for term in terms]
        return self

    def offset(self, value): return self

    def limit(self, value): return self

    def first(self):
        rows = self.all()
        return rows[0] if rows else None

    def count(self):
        return len(self.all())


class MemoryDB:
    def __init__(self):
        self.rows, self.pending = [], []

    def query(self, model):
        return Query(self, model)

    def add(self, row):
        self.pending.append(row)

    def commit(self):
        self.rows.extend(self.pending)
        self.pending.clear()

    def rollback(self):
        self.pending.clear()


def service():
    result = NewsCollectionService(MemoryDB())
    result.bocha_api_key = "offline-test-placeholder"
    result.bidding_service = Mock(app_code="offline-test-placeholder")
    result._official_feed = AsyncMock(return_value=[])
    return result


def item(**extra):
    return {"url": "https://www.esa.int/Applications/Observing_the_Earth/research?utm_source=sample#top",
            "title": "Earth observation research update", "snippet": "Public search snippet.",
            "summary": "An unrelated longer search summary.", "siteName": "ESA", "datePublished": "", **extra}


class URLTests(unittest.TestCase):
    def test_real_procurement_titles_are_excluded_without_broad_false_matches(self):
        for title in ('Invitation to Tender: “URBAN DEVELOPMENT, LIVEABILITY AND ADAPTATION”',
                      'Invitation to Tender: “ADAPTIVE FOREST MANAGEMENT: RESILIENCE AND REGROWTH”',
                      'Earth observation Procurement announcement', '遥感系统招标公告', '卫星影像采购公告'):
            self.assertTrue(NewsCollectionService._is_science_procurement(title))
        self.assertFalse(NewsCollectionService._is_science_procurement('Monitoring land degradation from space'))
        self.assertFalse(NewsCollectionService._is_science_procurement('Tenderness in medical imaging research'))

    def test_existing_science_tenders_hidden_from_list_but_industry_unchanged(self):
        s = service()
        for topic, title in [('remote_sensing', 'Invitation to Tender: Existing procurement'),
                             ('remote_sensing', 'Sentinel land monitoring research'),
                             ('finance', 'Bank procurement announcement')]:
            s.db.add(IndustryNews(industry_id=topic, title=title))
        s.db.commit()
        visible, count = s.get_news_list(industry_id='remote_sensing')
        self.assertEqual(count, 1)
        self.assertEqual(visible[0]['title'], 'Sentinel land monitoring research')
        self.assertEqual(s.db.ordering, ['industry_news.publish_time DESC NULLS LAST', 'industry_news.collected_at DESC'])
        all_rows, all_count = s.get_news_list()
        self.assertEqual(all_count, 2)
        industry, industry_count = s.get_news_list(industry_id='finance')
        self.assertEqual(industry_count, 1)
        self.assertEqual(s.db.ordering, ['industry_news.collected_at DESC'])
        self.assertEqual(len(s.db.rows), 3)
    def test_actual_host_allowlist_rejects_spoofed_and_non_public_schemes(self):
        domains = get_industry_config("remote_sensing").source_domains
        allowed = NewsCollectionService._official_news_url("https://science.nasa.gov/a?utm_source=x&q=earth#top", domains)
        self.assertEqual(allowed, "https://science.nasa.gov/a?q=earth")
        for url in ("https://nasa.gov.evil.example/a", "https://evilnasa.gov/a", "file:///nasa.gov/a",
                    "javascript:alert(1)", "https://nasa.gov@evil.example/a", "https://nasa.gov:8123/a"):
            with self.subTest(url=url):
                self.assertIsNone(NewsCollectionService._official_news_url(url, domains))


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_procurement_is_filtered_before_insertion_and_visible_count(self):
        s = service()
        s._official_feed = AsyncMock(return_value=[item(title='Invitation to Tender: New procurement'),
                          item(url='https://www.esa.int/earth/science', title='New Earth monitoring science')])
        result = await s.collect_news(30, 'remote_sensing')
        self.assertTrue(result['success'])
        self.assertEqual(result['collected'], 1)
        self.assertEqual(result['available_count'], 1)
        self.assertEqual(s.db.query(IndustryNews).count(), 1)
    async def test_official_feeds_work_without_api_key_and_refresh_without_duplicates(self):
        s = service()
        s.bocha_api_key = ""
        s._official_feed = AsyncMock(return_value=[item(datePublished="2026-09-25T12:20:00")])
        s._bocha_search = AsyncMock(side_effect=NewsSearchError("HTTP 403"))
        first = await s.collect_all(30, 1, "remote_sensing")
        second = await s.collect_all(30, 1, "remote_sensing")
        self.assertTrue(first["success"])
        self.assertEqual(first["news"]["collected"], 1)
        self.assertTrue(second["success"])
        self.assertEqual(second["news"]["collected"], 0)
        self.assertIn("官方 RSS", first["news"]["message"])
        self.assertIn("未发现新增", second["news"]["message"])
        self.assertIsNotNone(s.db.query(IndustryNews).first().publish_time)
        s._bocha_search.assert_not_awaited()

    async def test_one_unavailable_feed_does_not_mask_successful_official_source(self):
        s = service()
        s._official_feed = AsyncMock(side_effect=[TimeoutError(), [item()]])
        s._bocha_search = AsyncMock()
        result = await s.collect_all(30, 1, "remote_sensing")
        self.assertTrue(result["success"])
        self.assertEqual(result["news"]["collected"], 1)
        self.assertTrue(result["news"]["errors"])
        s._bocha_search.assert_not_awaited()

    async def test_rss_parser_preserves_real_date_and_ignores_full_article_content(self):
        s = service()
        client = AsyncMock()
        client.__aenter__.return_value = client
        response = Mock(status_code=200, content=b'''<rss xmlns:content="http://purl.org/rss/1.0/modules/content/">
        <channel><item><title>Actual Earth observation update</title><link>https://www.esa.int/earth/a</link>
        <pubDate>Fri, 25 Sep 2026 14:20:00 +0200</pubDate><description>Official brief excerpt.</description>
        <content:encoded>FULL ARTICLE SHOULD NOT BE STORED</content:encoded></item></channel></rss>''')
        client.get.return_value = response
        config = get_industry_config("remote_sensing")
        with patch("service.news_collection_service.httpx.AsyncClient", return_value=client):
            rows = await NewsCollectionService._official_feed(s, config.news_feeds[0], config.source_domains)
        self.assertEqual(rows[0]["datePublished"], "2026-09-25T12:20:00")
        self.assertEqual(rows[0]["snippet"], "Official brief excerpt.")
        self.assertNotIn("FULL ARTICLE", str(rows))

    async def test_atom_updated_time_is_not_invented_publication_date(self):
        s = service()
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = Mock(status_code=200, content=b'''<feed xmlns="http://www.w3.org/2005/Atom">
        <entry><title>Actual article</title><link rel="alternate" href="https://www.esa.int/earth/a"/>
        <updated>2026-09-25T12:20:00Z</updated><summary>Official summary.</summary></entry></feed>''')
        config = get_industry_config("remote_sensing")
        with patch("service.news_collection_service.httpx.AsyncClient", return_value=client):
            rows = await NewsCollectionService._official_feed(s, config.news_feeds[0], config.source_domains)
        self.assertEqual(rows[0]["datePublished"], "")
        self.assertEqual(rows[0]["url"], "https://www.esa.int/earth/a")

    async def test_feed_redirect_cannot_leave_official_host_allowlist(self):
        s = service()
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.get.return_value = Mock(status_code=302, headers={"location": "http://127.0.0.1/private"})
        config = get_industry_config("remote_sensing")
        with patch("service.news_collection_service.httpx.AsyncClient", return_value=client):
            with self.assertRaisesRegex(NewsSearchError, "域名范围"):
                await NewsCollectionService._official_feed(s, config.news_feeds[0], config.source_domains)
        self.assertEqual(client.get.await_count, 1)

    async def test_provider_business_error_is_reported_even_with_http_200(self):
        s = service()
        client = AsyncMock()
        client.__aenter__.return_value = client
        response = Mock(status_code=200)
        response.json.return_value = {"code": 403, "message": "quota exceeded"}
        client.post.return_value = response
        with patch("service.news_collection_service.httpx.AsyncClient", return_value=client):
            with self.assertRaisesRegex(NewsSearchError, "code 403"):
                await s._bocha_search("public scientific topic", strict=True)

    async def test_science_skips_bidding_and_preserves_unknown_date_and_short_snippet(self):
        s = service()
        s._bocha_search = AsyncMock(return_value=[item(snippet="<b>Public</b> " * 200)])
        s.collect_bidding = AsyncMock()
        with patch("service.news_collection_service.asyncio.sleep", new=AsyncMock()):
            result = await s.collect_all(5, 50, "remote_sensing")
        self.assertTrue(result["success"])
        self.assertEqual(result["news"]["collected"], 1)
        self.assertEqual(result["bidding"]["collected"], 0)
        s.collect_bidding.assert_not_awaited()
        row = s.db.query(IndustryNews).first()
        self.assertIsNone(row.publish_time)
        self.assertLessEqual(len(row.content), 500)
        self.assertNotIn("<b>", row.content)
        self.assertNotIn("utm_source", row.source_url)
        self.assertEqual(row.industry_id, "remote_sensing")

    async def test_known_publication_date_not_inferred_from_snippet(self):
        s = service()
        s._bocha_search = AsyncMock(return_value=[item(snippet="Study started 2020-01-02.")])
        with patch("service.news_collection_service.asyncio.sleep", new=AsyncMock()):
            await s.collect_news(1, "remote_sensing")
        self.assertIsNone(s.db.query(IndustryNews).first().publish_time)

    async def test_chinese_excerpt_is_limited_to_280_characters(self):
        s = service()
        s._bocha_search = AsyncMock(return_value=[item(snippet="遥感公开研究摘要。" * 100)])
        with patch("service.news_collection_service.asyncio.sleep", new=AsyncMock()):
            await s.collect_news(1, "remote_sensing")
        self.assertLessEqual(len(s.db.query(IndustryNews).first().content), 280)

    async def test_no_key_fails_instead_of_skipped_bidding_masking_failure(self):
        s = service()
        s.bocha_api_key = ""
        s._bocha_search = AsyncMock()
        result = await s.collect_all(5, 50, "remote_sensing")
        self.assertFalse(result["success"])
        self.assertIn("BOCHA_API_KEY", " ".join(result["news"]["errors"]))
        s._bocha_search.assert_not_awaited()
        self.assertEqual(s.db.query(NewsCollectionTask).first().status, "failed")

    async def test_non_official_search_results_do_not_enter_database(self):
        s = service()
        s._bocha_search = AsyncMock(return_value=[item(url="https://example.org/claims-to-be-nasa")])
        with patch("service.news_collection_service.asyncio.sleep", new=AsyncMock()):
            result = await s.collect_news(5, "remote_sensing")
        self.assertFalse(result["success"])
        self.assertEqual(s.db.query(IndustryNews).count(), 0)
        self.assertEqual(result["skipped_sources"], 5)

    async def test_zero_new_duplicates_are_reported_without_false_failure(self):
        s = service()
        s._bocha_search = AsyncMock(return_value=[item()])
        with patch("service.news_collection_service.asyncio.sleep", new=AsyncMock()):
            first = await s.collect_news(5, "remote_sensing")
            second = await s.collect_news(5, "remote_sensing")
        self.assertEqual(first["collected"], 1)
        self.assertTrue(second["success"])
        self.assertEqual(second["collected"], 0)
        self.assertEqual(second["duplicates"], 1)
        self.assertEqual(second["available_count"], 1)
        self.assertIn("未发现新增", second["message"])

    async def test_empty_or_failed_provider_does_not_claim_collection_success(self):
        for response in ([], NewsSearchError("资讯搜索失败（HTTP 401）")):
            with self.subTest(response=response):
                s = service()
                s._bocha_search = AsyncMock(side_effect=response) if isinstance(response, Exception) else AsyncMock(return_value=response)
                with patch("service.news_collection_service.asyncio.sleep", new=AsyncMock()):
                    result = await s.collect_all(5, 50, "remote_sensing")
                self.assertFalse(result["success"])
                self.assertEqual(result["news"]["collected"], 0)
                self.assertTrue(result["news"]["errors"])

    async def test_legacy_industry_still_runs_bidding_path(self):
        s = service()
        s.collect_news = AsyncMock(return_value={"success": True, "collected": 2})
        s.collect_bidding = AsyncMock(return_value={"success": True, "collected": 1})
        result = await s.collect_all(4, 3, "finance")
        s.collect_news.assert_awaited_once_with(4, "finance")
        s.collect_bidding.assert_awaited_once_with(3, "finance")
        self.assertTrue(result["success"])

    async def test_endpoint_keeps_explicit_failure_message(self):
        s = service()
        s.collect_all = AsyncMock(return_value={"success": False,
            "news": {"success": False, "collected": 0, "message": "没有有效来源", "errors": ["no results"], "available_count": 0},
            "bidding": {"success": True, "collected": 0, "errors": [], "skipped": "science"}})
        with patch("router.news_router.get_news_collection_service", return_value=s), patch("router.news_router.get_scheduler_service"):
            response = await trigger_collection(Mock(), 5, 50, "remote_sensing", s.db)
        self.assertFalse(response.success)
        self.assertEqual(response.message, "没有有效来源")
        self.assertEqual(response.news_collected, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
