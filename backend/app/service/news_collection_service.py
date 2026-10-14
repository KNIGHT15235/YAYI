
"""
行业资讯和招投标信息采集服务
- 使用 Bocha API 搜索行业资讯
- 使用 81API 搜索招投标信息
- 支持多行业配置
"""
import os
import asyncio
import json
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Dict, Any, List, Optional
import httpx
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, urljoin
import xml.etree.ElementTree as ET
from sqlalchemy.orm import Session
from sqlalchemy import or_

from models.news import IndustryNews, BiddingInfo, NewsCollectionTask
from service.bidding_service import get_bidding_service
from config.industry_config import get_industry_config, get_all_industries, INDUSTRY_CONFIGS

logger = logging.getLogger(__name__)

# Use the same portable expression in Python and PostgreSQL. Explicit word
# boundaries avoid excluding unrelated words such as "tenderness".
SCIENCE_PROCUREMENT_PATTERN = r"(^|[^a-z])(procurement|tenders?)([^a-z]|$)|招标|采购公告"


class NewsSearchError(ValueError):
    """A safe, user-visible search diagnostic without credentials or headers."""


class NewsCollectionService:
    """资讯采集服务"""

    def __init__(self, db: Session):
        self.db = db
        self.bocha_api_key = os.getenv("BOCHA_API_KEY", "")
        self.bidding_service = get_bidding_service()

        if not self.bocha_api_key:
            logger.warning("BOCHA_API_KEY 环境变量未设置")

    async def _bocha_search(self, query: str, count: int = 10, *, strict: bool = False) -> List[Dict]:
        """
        使用 Bocha API 进行搜索

        Args:
            query: 搜索关键词
            count: 返回数量

        Returns:
            搜索结果列表
        """
        logger.info(f"[_bocha_search] 搜索: query='{query}', count={count}")

        if not self.bocha_api_key:
            logger.error("[_bocha_search] Bocha API key not configured")
            if strict:
                raise NewsSearchError("未配置 BOCHA_API_KEY，无法检索资讯")
            return []

        url = "https://api.bochaai.com/v1/web-search"
        payload = {
            "query": query,
            "summary": True,
            "count": count,
            "page": 1
        }
        headers = {
            'Authorization': f"Bearer {self.bocha_api_key}",
            'Content-Type': 'application/json'
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                logger.info(f"[_bocha_search] 发送请求到 {url}")
                response = await client.post(url, headers=headers, json=payload)
                logger.info(f"[_bocha_search] 响应状态码: {response.status_code}")
                response.raise_for_status()
                data = response.json()
                logger.info(f"[_bocha_search] 响应数据键: {data.keys() if isinstance(data, dict) else type(data)}")
                if strict and isinstance(data, dict) and data.get('code') not in (None, 0, 200, '200', '0'):
                    code = str(data.get('code'))
                    code = code if re.fullmatch(r'\d{3,5}', code) else 'unknown'
                    raise NewsSearchError(f"搜索服务返回业务错误（code {code}）")

                webpages_data = data.get('data', {}).get('webPages', {})
                value_list = webpages_data.get('value', [])
                logger.info(f"[_bocha_search] 获取到 {len(value_list) if isinstance(value_list, list) else 0} 条结果")

                if not isinstance(value_list, list):
                    logger.warning(f"[_bocha_search] value_list 不是列表: {type(value_list)}")
                    if strict:
                        raise NewsSearchError("搜索服务未返回有效资讯列表")
                    return []

                results = []
                for item in value_list:
                    if item.get('url') and (item.get('snippet') or item.get('summary')):
                        results.append({
                            'url': item.get('url', ''),
                            'title': item.get('name', ''),
                            'summary': item.get('summary', '') or item.get('snippet', ''),
                            'snippet': item.get('snippet', ''),
                            'siteName': item.get('siteName', ''),
                            'datePublished': item.get('datePublished', ''),
                        })

                logger.info(f"[_bocha_search] 返回 {len(results)} 条有效结果")
                return results

        except Exception as e:
            logger.error(f"[_bocha_search] Bocha search error for '{query}': {e}", exc_info=True)
            if strict:
                if isinstance(e, NewsSearchError):
                    raise
                status = getattr(getattr(e, "response", None), "status_code", None)
                raise NewsSearchError(f"资讯搜索失败（HTTP {status}）" if status else "资讯搜索失败，请检查搜索服务与网络") from e
            return []

    @staticmethod
    def _official_news_url(value: str, domains: List[str]) -> Optional[str]:
        """Filter actual result hosts; a site: term alone is not a trust check."""
        try:
            url = urlsplit(str(value or "").strip())
            host = (url.hostname or "").lower().rstrip(".")
            if (url.scheme.lower() not in {"http", "https"} or url.username or url.password
                    or not any(host == d or host.endswith("." + d) for d in domains)):
                return None
            if url.port not in (None, 80, 443):
                return None
            # Drop fragments/known campaign tracking only, preserving meaningful
            # query parameters that may identify an article or dataset.
            params = [(key, val) for key, val in parse_qsl(url.query, keep_blank_values=True)
                      if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}]
            netloc = host + (":" + str(url.port) if url.port else "")
            return urlunsplit((url.scheme.lower(), netloc, url.path or "/", urlencode(params), ""))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _news_text(value: str, limit: int) -> str:
        value = re.sub(r"<[^>]*>", " ", str(value or ""))
        return re.sub(r"\s+", " ", html.unescape(value)).strip()[:limit]

    @staticmethod
    def _is_science_procurement(title: str) -> bool:
        return bool(re.search(SCIENCE_PROCUREMENT_PATTERN, str(title or ""), re.I))

    @staticmethod
    def _visible_news_query(query):
        """Hide legacy-imported procurement entries only in scientific topics.

        Preserve stored records and the original behavior of industry topics;
        applying this predicate to lists and aggregates keeps visible totals true.
        """
        scientific_ids = [key for key, config in INDUSTRY_CONFIGS.items() if config.source_domains]
        return query.filter(or_(IndustryNews.industry_id.is_(None),
                                ~IndustryNews.industry_id.in_(scientific_ids),
                                ~IndustryNews.title.op("~*")(SCIENCE_PROCUREMENT_PATTERN)))

    @staticmethod
    def _feed_datetime(value: str) -> Optional[str]:
        if not value:
            return None
        try:
            try:
                result = parsedate_to_datetime(value)
            except (TypeError, ValueError):
                result = datetime.fromisoformat(value.replace('Z', '+00:00'))
            if result.tzinfo:
                result = result.astimezone(timezone.utc).replace(tzinfo=None)
            return result.isoformat()
        except (TypeError, ValueError, OverflowError):
            return None

    async def _official_feed(self, feed: Dict[str, str], domains: List[str]) -> List[Dict]:
        """Read official RSS/Atom metadata only; never fetch article full texts."""
        url = self._official_news_url(feed['url'], domains)
        if not url:
            raise NewsSearchError("订阅地址不在配置的官方来源中")
        async with httpx.AsyncClient(timeout=18, follow_redirects=False,
                                    headers={'User-Agent': 'YAYI-Research/1.0 RSS reader'}) as client:
            for _ in range(4):
                response = await client.get(url)
                if response.status_code in (301, 302, 303, 307, 308):
                    url = self._official_news_url(urljoin(url, response.headers.get('location', '')), domains)
                    if not url:
                        raise NewsSearchError("订阅源重定向超出官方域名范围")
                    continue
                response.raise_for_status()
                break
            else:
                raise NewsSearchError("订阅源重定向次数过多")
        if len(response.content) > 2_000_000 or re.search(br'<!\s*(?:DOCTYPE|ENTITY)', response.content, re.I):
            raise NewsSearchError("订阅内容超过限制或包含不支持的 XML 声明")
        try:
            root = ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise NewsSearchError("官方订阅源未返回有效 RSS/Atom") from exc
        atom = '{http://www.w3.org/2005/Atom}'
        entries = root.findall('./channel/item') or root.findall(atom + 'entry')
        rows = []
        for entry in entries[:100]:
            title = entry.findtext('title') or entry.findtext(atom + 'title') or ''
            link = entry.findtext('link')
            if not link:
                alternate = next((node for node in entry.findall(atom + 'link')
                                  if node.get('rel', 'alternate') == 'alternate'), None)
                link = alternate.get('href', '') if alternate is not None else ''
            # RSS description / Atom summary only, never content:encoded/body.
            summary = entry.findtext('description') or entry.findtext(atom + 'summary') or ''
            published = entry.findtext('pubDate') or entry.findtext(atom + 'published') or ''
            rows.append({'title': title, 'url': link, 'snippet': summary, 'summary': '',
                         'siteName': feed['name'], 'datePublished': self._feed_datetime(published) or ''})
        return rows

    async def _collect_science_news(self, config, max_items: int) -> Dict[str, Any]:
        """Store short public search snippets from the configured official hosts.

        No article body or generated paper is fetched, and an absent publication
        date stays unknown. Collection timestamps are recorded separately.
        """
        task = NewsCollectionTask(task_type="news", status="running", started_at=datetime.utcnow())
        self.db.add(task)
        self.db.commit()
        errors, collected = [], []
        duplicates = skipped = inspected = successful_queries = 0
        seen = set()
        provider_mode = "bocha"
        try:
            batches = []
            if config.news_feeds:
                replies = await asyncio.gather(*(self._official_feed(feed, config.source_domains)
                                                  for feed in config.news_feeds), return_exceptions=True)
                for feed, reply in zip(config.news_feeds, replies):
                    if isinstance(reply, BaseException):
                        errors.append(f"{feed['name']} 订阅获取失败（{type(reply).__name__}）")
                    elif reply:
                        batches.append(("官方订阅源：" + feed['name'], reply))
                    else:
                        errors.append(f"{feed['name']} 订阅暂未提供资讯")
                if batches:
                    provider_mode = "official_feeds"
            if not batches and not self.bocha_api_key:
                errors.append("未配置 BOCHA_API_KEY，无法采集科研资讯。")
            elif not batches:
                keywords = config.news_keywords
                per_keyword = max(2, max_items // max(1, len(keywords)))
                for keyword in keywords:
                    try:
                        rows = await self._bocha_search(keyword, count=min(50, per_keyword + 4), strict=True)
                        if not rows:
                            errors.append(f"检索无结果：{keyword}")
                        batches.append((keyword, rows))
                    except Exception as exc:
                        errors.append(f"{keyword}：{str(exc)[:160]}")
                    await asyncio.sleep(.3)
            for keyword, rows in batches:
                    if len(collected) >= max_items:
                        break
                    successful_queries += 1
                    try:
                        for item in rows:
                            if len(collected) >= max_items:
                                break
                            inspected += 1
                            url = self._official_news_url(item.get("url", ""), config.source_domains)
                            title = self._news_text(item.get("title"), 500)
                            summary = self._news_text(item.get("snippet") or item.get("summary"), 500)
                            if re.search(r"[\u4e00-\u9fff]", summary):
                                summary = summary[:280]
                            if not url or not title or not summary or self._is_science_procurement(title):
                                skipped += 1
                                continue
                            if url in seen:
                                continue
                            seen.add(url)
                            existing = self.db.query(IndustryNews).filter(
                                IndustryNews.industry_id == config.id, IndustryNews.source_url == url).first()
                            if existing:
                                duplicates += 1
                                continue
                            published = self._parse_datetime(item.get("datePublished", ""))
                            if published and published.date() > datetime.utcnow().date():
                                published = None
                            news = IndustryNews(industry_id=config.id, title=title, content=summary,
                                source=self._news_text(item.get("siteName"), 200) or urlsplit(url).hostname,
                                source_url=url, category=self._categorize_news(title, summary),
                                department=None, publish_time=published, keywords=keyword[:500],
                                collected_at=datetime.utcnow())
                            self.db.add(news)
                            collected.append(news)
                    except Exception as exc:
                        # Errors contain no API key or request headers.
                        errors.append(f"{keyword}：{str(exc)[:160]}")
            if inspected and not seen:
                errors.append("获取的结果未通过官方来源、标题与摘要检查，没有入库。")
            self.db.commit()
            available = self._visible_news_query(self.db.query(IndustryNews)).filter(IndustryNews.industry_id == config.id).count()
            success = bool(collected) or bool(successful_queries and duplicates)
            if collected:
                message = f"科研资讯采集完成，新增 {len(collected)} 条。"
            elif success:
                message = f"本次未发现新增科研资讯，现有 {available} 条已保留。"
            else:
                message = "未采集到有效科研资讯，请查看原因后重试。"
            if provider_mode == "official_feeds":
                message += " 本次通过官方 RSS 订阅更新，无需搜索 API 密钥。"
            elif config.news_feeds and success:
                message += " 官方订阅暂不可用，本次使用关键词搜索补充。"
            task.status = "completed" if success else "failed"
            task.total_collected = len(collected)
            task.completed_at = datetime.utcnow()
            task.error_message = "; ".join(errors[:5]) if errors else None
            self.db.commit()
            return {"success": success, "collected": len(collected), "errors": errors, "message": message,
                    "available_count": available, "duplicates": duplicates, "skipped_sources": skipped}
        except Exception as exc:
            self.db.rollback()
            task.status, task.total_collected = "failed", 0
            task.completed_at = datetime.utcnow()
            task.error_message = "科研资讯存储失败：" + type(exc).__name__
            self.db.commit()
            return {"success": False, "collected": 0, "errors": [task.error_message],
                    "message": "科研资讯采集失败，未确认成功入库。"}

    async def collect_news(self, max_items: int = 20, industry_id: Optional[str] = None) -> Dict[str, Any]:
        """
        采集行业资讯

        Args:
            max_items: 最大采集数量
            industry_id: 行业ID，用于获取对应的搜索关键词

        Returns:
            采集结果
        """
        # 获取行业配置
        industry_config = get_industry_config(industry_id)
        if industry_config.source_domains:
            return await self._collect_science_news(industry_config, max_items)
        news_keywords = industry_config.news_keywords
        logger.info(f"[collect_news] 使用行业: {industry_config.name}, 关键词数量: {len(news_keywords)}")

        task = NewsCollectionTask(
            task_type="news",
            status="running",
            started_at=datetime.utcnow()
        )
        self.db.add(task)
        self.db.commit()

        collected = []
        errors = []

        try:
            items_per_keyword = max(2, max_items // len(news_keywords))

            for keyword in news_keywords:
                if len(collected) >= max_items:
                    break

                try:
                    # 使用Bocha搜索
                    results = await self._bocha_search(keyword, count=items_per_keyword + 2)

                    if not results:
                        errors.append(f"搜索 '{keyword}' 无结果")
                        continue

                    count = 0
                    for item in results:
                        if count >= items_per_keyword:
                            break
                        if len(collected) >= max_items:
                            break

                        source_url = item.get('url', '')
                        if not source_url:
                            continue

                        # 检查是否已存在
                        existing = self.db.query(IndustryNews).filter(
                            IndustryNews.source_url == source_url
                        ).first()

                        if existing:
                            continue

                        # 解析发布时间
                        publish_time = self._parse_datetime(item.get('datePublished', ''))
                        if not publish_time:
                            publish_time = self._extract_date_from_snippet(item.get('snippet', ''))

                        # 判断分类
                        title = item.get('title', '')
                        content = item.get('summary', '') or item.get('snippet', '')
                        category = self._categorize_news(title, content)

                        news = IndustryNews(
                            industry_id=industry_id or "smart_transportation",
                            title=title[:500] if title else '无标题',
                            content=content,
                            source=item.get('siteName', '') or self._extract_source_from_link(source_url),
                            source_url=source_url,
                            category=category,
                            department=self._extract_department(title, content),
                            publish_time=publish_time,
                            keywords=keyword,
                            collected_at=datetime.utcnow()
                        )

                        self.db.add(news)
                        collected.append(news)
                        count += 1

                    # 避免请求过于频繁
                    await asyncio.sleep(0.3)

                except Exception as e:
                    errors.append(f"处理关键词 '{keyword}' 时出错: {str(e)}")
                    logger.error(f"Error processing keyword '{keyword}': {e}")

            self.db.commit()

            task.status = "completed"
            task.total_collected = len(collected)
            task.completed_at = datetime.utcnow()
            if errors:
                task.error_message = "; ".join(errors[:5])
            self.db.commit()

            return {
                "success": True,
                "collected": len(collected),
                "errors": errors
            }

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.completed_at = datetime.utcnow()
            self.db.commit()
            logger.error(f"News collection failed: {e}")

            return {
                "success": False,
                "error": str(e),
                "collected": len(collected)
            }

    async def collect_bidding(self, max_items: int = 20, industry_id: Optional[str] = None) -> Dict[str, Any]:
        """
        采集招投标信息

        Args:
            max_items: 最大采集数量
            industry_id: 行业ID，用于获取对应的搜索关键词

        Returns:
            采集结果
        """
        # 获取行业配置
        industry_config = get_industry_config(industry_id)
        bidding_keywords = industry_config.bidding_keywords
        logger.info(f"[collect_bidding] 使用行业: {industry_config.name}, 关键词数量: {len(bidding_keywords)}")

        task = NewsCollectionTask(
            task_type="bidding",
            status="running",
            started_at=datetime.utcnow()
        )
        self.db.add(task)
        self.db.commit()

        collected = []
        errors = []
        quota_exhausted = False

        try:
            items_per_keyword = max(3, max_items // len(bidding_keywords))

            for keyword in bidding_keywords:
                if len(collected) >= max_items or quota_exhausted:
                    break

                try:
                    # 查询招标信息
                    bid_result = await self.bidding_service.search_bid_notices(
                        keyword=keyword,
                        page=1
                    )

                    # 检查是否配额用尽
                    if bid_result.get("quota_exhausted"):
                        logger.warning(f"[collect_bidding] API 配额已用尽，停止采集")
                        errors.append("招投标 API 配额已用尽，请续费或等待配额重置")
                        quota_exhausted = True
                        break

                    if bid_result.get("success"):
                        for item in bid_result.get("results", [])[:items_per_keyword]:
                            if len(collected) >= max_items:
                                break

                            bid_id = item.get("id")
                            if not bid_id:
                                continue

                            # 检查是否已存在
                            existing = self.db.query(BiddingInfo).filter(
                                BiddingInfo.bid_id == bid_id
                            ).first()

                            if existing:
                                continue

                            # 解析发布时间
                            publish_time = self._parse_datetime(item.get("publish_time"))

                            bidding = BiddingInfo(
                                industry_id=industry_id or "smart_transportation",
                                bid_id=bid_id,
                                title=item.get("title", "")[:500],
                                notice_type=item.get("notice_type", "招标"),
                                province=item.get("province"),
                                city=item.get("city"),
                                publish_time=publish_time,
                                source=item.get("source", "81api"),
                                collected_at=datetime.utcnow()
                            )

                            self.db.add(bidding)
                            collected.append(bidding)
                    else:
                        errors.append(f"查询招标 '{keyword}' 失败: {bid_result.get('error', '未知错误')}")

                    if quota_exhausted:
                        break

                    # 查询中标信息
                    win_result = await self.bidding_service.search_win_bids(
                        keyword=keyword,
                        page=1
                    )

                    # 检查是否配额用尽
                    if win_result.get("quota_exhausted"):
                        logger.warning(f"[collect_bidding] API 配额已用尽，停止采集")
                        errors.append("招投标 API 配额已用尽，请续费或等待配额重置")
                        quota_exhausted = True
                        break

                    if win_result.get("success"):
                        for item in win_result.get("results", [])[:items_per_keyword]:
                            if len(collected) >= max_items:
                                break

                            bid_id = item.get("id")
                            if not bid_id:
                                continue

                            # 检查是否已存在
                            existing = self.db.query(BiddingInfo).filter(
                                BiddingInfo.bid_id == bid_id
                            ).first()

                            if existing:
                                continue

                            publish_time = self._parse_datetime(item.get("publish_time"))

                            bidding = BiddingInfo(
                                industry_id=industry_id or "smart_transportation",
                                bid_id=bid_id,
                                title=item.get("title", "")[:500],
                                notice_type=item.get("notice_type", "中标"),
                                province=item.get("province"),
                                city=item.get("city"),
                                publish_time=publish_time,
                                source=item.get("source", "81api"),
                                collected_at=datetime.utcnow()
                            )

                            self.db.add(bidding)
                            collected.append(bidding)

                    if not quota_exhausted:
                        await asyncio.sleep(0.3)

                except Exception as e:
                    errors.append(f"处理关键词 '{keyword}' 时出错: {str(e)}")
                    logger.error(f"Error processing bidding keyword '{keyword}': {e}")

            self.db.commit()

            task.status = "completed"
            task.total_collected = len(collected)
            task.completed_at = datetime.utcnow()
            if errors:
                task.error_message = "; ".join(errors[:5])
            self.db.commit()

            return {
                "success": True,
                "collected": len(collected),
                "errors": errors
            }

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            task.completed_at = datetime.utcnow()
            self.db.commit()
            logger.error(f"Bidding collection failed: {e}")

            return {
                "success": False,
                "error": str(e),
                "collected": len(collected)
            }

    async def collect_all(
        self,
        max_news: int = 20,
        max_bidding: int = 20,
        industry_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        采集所有资讯（行业资讯+招投标）

        Args:
            max_news: 最大资讯采集数量
            max_bidding: 最大招投标采集数量
            industry_id: 行业ID
        """
        industry_config = get_industry_config(industry_id)
        logger.info(f"[NewsCollectionService] collect_all 开始: industry={industry_config.name}, max_news={max_news}, max_bidding={max_bidding}")
        logger.info(f"[NewsCollectionService] BOCHA_API_KEY 已配置: {bool(self.bocha_api_key)}")

        news_result = await self.collect_news(max_news, industry_id)
        logger.info(f"[NewsCollectionService] collect_news 结果: {news_result}")

        # 检查招投标 API 是否可用
        if industry_config.skip_bidding:
            bidding_result = {"success": True, "collected": 0, "errors": [], "skipped": "科研主题不采集招投标信息"}
        elif not self.bidding_service.app_code:
            logger.warning("[NewsCollectionService] 招投标 API 未配置，跳过招投标采集")
            bidding_result = {
                "success": True,
                "collected": 0,
                "errors": [],
                "skipped": "BID_APP_CODE 未配置"
            }
        else:
            bidding_result = await self.collect_bidding(max_bidding, industry_id)
            logger.info(f"[NewsCollectionService] collect_bidding 结果: {bidding_result}")

        result = {
            "success": bool(news_result.get("success")) if industry_config.skip_bidding else news_result.get("success") or bidding_result.get("success"),
            "news": news_result,
            "bidding": bidding_result,
            "industry": industry_config.name
        }
        logger.info(f"[NewsCollectionService] collect_all 返回: {result}")
        return result

    def get_news_list(
        self,
        category: Optional[str] = None,
        industry_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[List[Dict], int]:
        """获取资讯列表，返回 (items, filtered_total)"""
        query = self._visible_news_query(self.db.query(IndustryNews))
        if industry_id in INDUSTRY_CONFIGS and INDUSTRY_CONFIGS[industry_id].source_domains:
            query = query.order_by(IndustryNews.publish_time.desc().nullslast(), IndustryNews.collected_at.desc())
        else:
            query = query.order_by(IndustryNews.collected_at.desc())

        # 按行业筛选
        if industry_id:
            query = query.filter(IndustryNews.industry_id == industry_id)

        if category:
            query = query.filter(IndustryNews.category == category)

        # 先获取筛选后的总数
        filtered_total = query.count()

        items = query.offset(offset).limit(limit).all()
        return [item.to_dict() for item in items], filtered_total

    def get_bidding_list(
        self,
        notice_type: Optional[str] = None,
        province: Optional[str] = None,
        industry_id: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> tuple[List[Dict], int]:
        """获取招投标列表，返回 (items, filtered_total)"""
        from sqlalchemy import or_

        query = self.db.query(BiddingInfo).order_by(BiddingInfo.collected_at.desc())

        # 按行业筛选
        if industry_id:
            query = query.filter(BiddingInfo.industry_id == industry_id)

        if notice_type:
            # 支持模糊匹配：如 "招标" 匹配 "招标公告"、"采购公告" 等
            if notice_type == "招标":
                query = query.filter(
                    or_(
                        BiddingInfo.notice_type.like("%招标%"),
                        BiddingInfo.notice_type.like("%采购%"),
                        BiddingInfo.notice_type.like("%询价%")
                    )
                )
            elif notice_type == "中标":
                query = query.filter(
                    or_(
                        BiddingInfo.notice_type.like("%中标%"),
                        BiddingInfo.notice_type.like("%结果%")
                    )
                )
            else:
                query = query.filter(BiddingInfo.notice_type == notice_type)
        if province:
            query = query.filter(BiddingInfo.province == province)

        # 先获取筛选后的总数
        filtered_total = query.count()

        items = query.offset(offset).limit(limit).all()
        return [item.to_dict() for item in items], filtered_total

    def get_news_stats(self, industry_id: Optional[str] = None) -> Dict[str, Any]:
        """获取资讯统计"""
        from sqlalchemy import func

        query = self._visible_news_query(self.db.query(IndustryNews))
        if industry_id:
            query = query.filter(IndustryNews.industry_id == industry_id)

        total = query.count()

        # 按分类统计
        cat_query = self._visible_news_query(self.db.query(
            IndustryNews.category,
            func.count(IndustryNews.id).label("count")
        ))
        if industry_id:
            cat_query = cat_query.filter(IndustryNews.industry_id == industry_id)
        category_stats = cat_query.group_by(IndustryNews.category).all()

        # 获取最近24小时更新数
        yesterday = datetime.utcnow() - timedelta(hours=24)
        recent_query = self._visible_news_query(self.db.query(IndustryNews)).filter(
            IndustryNews.collected_at >= yesterday
        )
        if industry_id:
            recent_query = recent_query.filter(IndustryNews.industry_id == industry_id)
        recent_count = recent_query.count()

        return {
            "total": total,
            "recent_24h": recent_count,
            "by_category": {cat: cnt for cat, cnt in category_stats if cat}
        }

    def get_bidding_stats(self, industry_id: Optional[str] = None) -> Dict[str, Any]:
        """获取招投标统计"""
        from sqlalchemy import func

        query = self.db.query(BiddingInfo)
        if industry_id:
            query = query.filter(BiddingInfo.industry_id == industry_id)

        total = query.count()

        # 按类型统计（原始类型）
        type_query = self.db.query(
            BiddingInfo.notice_type,
            func.count(BiddingInfo.id).label("count")
        )
        if industry_id:
            type_query = type_query.filter(BiddingInfo.industry_id == industry_id)
        type_stats = type_query.group_by(BiddingInfo.notice_type).all()

        # 归类统计：中标类 vs 招标类
        bid_count = 0  # 招标
        win_count = 0  # 中标
        raw_by_type = {}
        for notice_type, count in type_stats:
            if notice_type:
                raw_by_type[notice_type] = count
                # 归类
                if "中标" in notice_type or "结果" in notice_type:
                    win_count += count
                elif "招标" in notice_type or "采购" in notice_type or "询价" in notice_type:
                    bid_count += count

        # 按省份统计（前10）
        province_query = self.db.query(
            BiddingInfo.province,
            func.count(BiddingInfo.id).label("count")
        )
        if industry_id:
            province_query = province_query.filter(BiddingInfo.industry_id == industry_id)
        province_stats = province_query.group_by(BiddingInfo.province).order_by(
            func.count(BiddingInfo.id).desc()
        ).limit(10).all()

        return {
            "total": total,
            "by_type": {
                "招标": bid_count,
                "中标": win_count,
                **raw_by_type  # 保留原始类型以便调试
            },
            "by_province": {p: c for p, c in province_stats if p}
        }

    def has_data(self) -> bool:
        """检查是否有数据"""
        news_count = self._visible_news_query(self.db.query(IndustryNews)).count()
        bidding_count = self.db.query(BiddingInfo).count()
        return news_count > 0 or bidding_count > 0

    def _extract_date_from_snippet(self, snippet: str) -> Optional[datetime]:
        """从snippet中提取日期"""
        import re

        if not snippet:
            return None

        patterns = [
            r'(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})[日号]?',
            r'(\d{4})\.(\d{1,2})\.(\d{1,2})',
        ]

        for pattern in patterns:
            match = re.search(pattern, snippet)
            if match:
                try:
                    year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
                    if 2020 <= year <= 2030 and 1 <= month <= 12 and 1 <= day <= 31:
                        return datetime(year, month, day)
                except:
                    pass

        return None

    def _parse_datetime(self, date_str: str) -> Optional[datetime]:
        """解析日期时间字符串"""
        if not date_str:
            return None

        formats = [
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
            "%Y年%m月%d日",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str.split('.')[0].split('+')[0], fmt)
            except:
                pass

        return None

    def _categorize_news(self, title: str, content: str) -> str:
        """判断资讯分类"""
        text = f"{title} {content}".lower()

        if any(kw in text for kw in ["政策", "通知", "意见", "办法", "规定", "条例", "规划", "法规"]):
            return "政策"
        if any(kw in text for kw in ["纪要", "会议", "座谈", "研讨"]):
            return "纪要"
        if any(kw in text for kw in ["研报", "研究报告", "分析报告", "白皮书", "行业报告"]):
            return "研报"

        return "新闻"

    def _extract_source_from_link(self, link: str) -> str:
        """从链接提取来源"""
        if not link:
            return "未知来源"

        try:
            from urllib.parse import urlparse
            parsed = urlparse(link)
            domain = parsed.netloc

            source_map = {
                "gov.cn": "政府网站",
                "xinhuanet.com": "新华网",
                "people.com.cn": "人民网",
                "mot.gov.cn": "交通运输部",
                "ndrc.gov.cn": "国家发改委",
                "miit.gov.cn": "工信部",
                "163.com": "网易",
                "sohu.com": "搜狐",
                "sina.com": "新浪",
                "qq.com": "腾讯",
                "baidu.com": "百度",
            }

            for key, name in source_map.items():
                if key in domain:
                    return name

            # 返回主域名
            parts = domain.split('.')
            if len(parts) >= 2:
                return '.'.join(parts[-2:])
            return domain
        except:
            return "未知来源"

    def _extract_department(self, title: str, content: str) -> Optional[str]:
        """提取发布部门"""
        text = f"{title} {content}"

        departments = [
            "国务院", "交通运输部", "工信部", "发改委", "科技部",
            "住建部", "公安部", "财政部", "自然资源部", "工业和信息化部",
            "国家发展改革委", "交通运输厅",
        ]

        for dept in departments:
            if dept in text:
                return dept

        return None


def get_news_collection_service(db: Session) -> NewsCollectionService:
    """获取服务实例"""
    return NewsCollectionService(db)
