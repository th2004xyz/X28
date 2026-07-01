"""数据抓取层: X API v2 优先，自动降级到 twiiit.com (Nitter 智能网关) RSS。

可靠性改进:
  - TTL 内存缓存 (默认 60s)，减少重复刷新的资源消耗
  - @retry 装饰器对 RSS 抓取做指数退避重试
  - 返回标准化 Tweet dataclass
"""

import time
import logging
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Optional

import requests

from ..utils.helpers import (
    clean_html, extract_stats, format_pubdate, retry,
)
from .models import Tweet

log = logging.getLogger("x28.scraper")


class TwitterScraper:
    """优先使用官方 X API v2；失败或未配置时使用 twiiit.com RSS。

    twiiit.com 会自动重定向到当前存活的 Nitter 实例，无需维护实例列表。
    """

    HEADERS = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }

    def __init__(self, bearer_token: str = "", cache_ttl: float = 60.0):
        self.bearer_token = (bearer_token or "").strip()
        self._cache_ttl = cache_ttl
        # key -> (timestamp, tweets)
        self._cache: dict = {}

    # ---------- 缓存 ----------
    def _cache_get(self, key: str) -> Optional[List[Tweet]]:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, tweets = entry
        if time.time() - ts < self._cache_ttl:
            log.debug("缓存命中: %s", key)
            return tweets
        del self._cache[key]
        return None

    def _cache_set(self, key: str, tweets: List[Tweet]) -> None:
        self._cache[key] = (time.time(), tweets)

    # ---------- 公开接口 ----------
    def get_tweets_by_account(self, username: str,
                              force_refresh: bool = False) -> List[Tweet]:
        clean = username.lstrip("@")
        cache_key = f"acct:{clean.lower()}"
        if not force_refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached

        if self.bearer_token:
            try:
                tweets = self._x_api_user(clean)
                self._cache_set(cache_key, tweets)
                return tweets
            except Exception as e:
                log.warning("X API 失败: %s，降级到 Nitter…", e)
        tweets = self._nitter_user(clean)
        self._cache_set(cache_key, tweets)
        return tweets

    def get_tweets_by_keyword(self, query: str,
                               force_refresh: bool = False) -> List[Tweet]:
        cache_key = f"kw:{query.lower()}"
        if not force_refresh:
            cached = self._cache_get(cache_key)
            if cached is not None:
                return cached
        tweets = self._nitter_search(query)
        self._cache_set(cache_key, tweets)
        return tweets

    # ---------- X API v2 ----------
    def _x_api_user(self, username: str) -> List[Tweet]:
        h = {"Authorization": f"Bearer {self.bearer_token}"}
        r = requests.get(
            f"https://api.twitter.com/2/users/by/username/{username}",
            headers=h, timeout=10)
        r.raise_for_status()
        uid = r.json()["data"]["id"]

        r2 = requests.get(
            f"https://api.twitter.com/2/users/{uid}/tweets",
            headers=h, timeout=10,
            params={
                "max_results": 20,
                "tweet.fields": "created_at,public_metrics",
                "expansions": "author_id",
                "user.fields": "profile_image_url,username,name",
            })
        r2.raise_for_status()
        data = r2.json()
        users_map = {u["id"]: u for u in data.get("includes", {}).get("users", [])}

        tweets: List[Tweet] = []
        for t in data.get("data", []):
            m = t.get("public_metrics", {})
            uid2 = t.get("author_id", "")
            uinfo = users_map.get(uid2, {})
            dt_str = t.get("created_at", "")
            try:
                dt_str = datetime.strptime(
                    dt_str[:19], "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass
            tweets.append(Tweet(
                username=f"@{username}",
                display_name=uinfo.get("name", username),
                text=t.get("text", ""),
                time=dt_str,
                likes=int(m.get("like_count", 0) or 0),
                retweets=int(m.get("retweet_count", 0) or 0),
                avatar_url=uinfo.get("profile_image_url", ""),
            ))
        return tweets

    # ---------- Nitter / twiiit.com ----------
    def _nitter_user(self, username: str) -> List[Tweet]:
        url = f"https://twiiit.com/{username}/rss"
        return self._fetch_and_parse_rss(url, default_username=username)

    def _nitter_search(self, query: str) -> List[Tweet]:
        q = urllib.parse.quote(query)
        url = f"https://twiiit.com/search/rss?f=tweets&q={q}"
        return self._fetch_and_parse_rss(url, default_username=query)

    @retry(times=3, delay=1.5, backoff=2.0,
           exceptions=(requests.exceptions.ConnectionError,
                       requests.exceptions.Timeout))
    def _fetch_and_parse_rss(self, url: str, default_username: str = "") -> List[Tweet]:
        try:
            resp = requests.get(url, headers=self.HEADERS,
                                timeout=12, allow_redirects=True)
            if resp.status_code != 200:
                raise Exception(f"HTTP {resp.status_code}")
            return self._parse_rss(resp.text, default_username)
        except requests.exceptions.ProxyError as e:
            raise Exception(f"代理连接失败，请检查代理设置或关闭代理后重试。({e})")
        except requests.exceptions.ConnectionError as e:
            raise Exception(f"网络连接错误，请检查网络是否畅通。({e})")
        except requests.exceptions.Timeout:
            raise Exception("请求超时，请确认网络可访问 twiiit.com，可能需要科学上网。")
        except Exception as e:
            raise Exception(str(e))

    def _parse_rss(self, xml_text: str, default_username: str) -> List[Tweet]:
        tweets: List[Tweet] = []
        try:
            root = ET.fromstring(xml_text.encode("utf-8"))
            channel = root.find("channel")
            if channel is None:
                return []
            ns = {"dc": "http://purl.org/dc/elements/1.1/"}
            for item in channel.findall("item")[:20]:
                desc_el = item.find("description")
                date_el = item.find("pubDate")
                creator_el = item.find("dc:creator", ns)

                raw_html = desc_el.text if desc_el is not None else ""
                text = clean_html(raw_html)
                likes, retweets = extract_stats(raw_html)
                time_str = format_pubdate(
                    date_el.text if date_el is not None else "")

                display_name = ((creator_el.text or default_username)
                                if creator_el is not None else default_username)
                disp_clean = display_name.lstrip("@")
                username_tag = (f"@{disp_clean}"
                                if not display_name.startswith("@")
                                else display_name)

                tweets.append(Tweet(
                    username=username_tag,
                    display_name=disp_clean,
                    text=text,
                    time=time_str,
                    likes=likes,
                    retweets=retweets,
                    avatar_url="",  # twiiit.com 不提供头像 URL
                ))
        except ET.ParseError as e:
            raise Exception(f"RSS 解析失败 (XML 格式错误): {e}")
        return tweets
