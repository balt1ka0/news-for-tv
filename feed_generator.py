#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор RSS-ленты для корпоративного ТВ.
Собирает новости из RSS-источников, фильтрует по темам,
исключает политику/военную тематику и формирует чистую RSS 2.0 ленту.
"""

import html
import logging
import re
import sys
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from xml.etree.ElementTree import Element, SubElement, ElementTree, indent

import feedparser

import config

# === ЛОГИРОВАНИЕ ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("feed")


def clean_text(raw: str) -> str:
    """Убирает HTML-теги и лишние пробелы из текста."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def matches_keywords(text: str) -> bool:
    """Проверяет, содержит ли текст хотя бы одно ключевое слово."""
    low = text.lower()
    return any(kw.lower() in low for kw in config.KEYWORDS)


def matches_blacklist(text: str) -> bool:
    """Проверяет, содержит ли текст стоп-слово."""
    low = text.lower()
    return any(bad.lower() in low for bad in config.BLACKLIST)


def parse_entry_date(entry) -> datetime:
    """Извлекает дату публикации из записи feedparser."""
    for field in ("published_parsed", "updated_parsed"):
        value = entry.get(field)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return datetime.now(timezone.utc)


def fetch_news() -> list[dict]:
    """Обходит все источники и возвращает отфильтрованные новости."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.MAX_AGE_DAYS)
    collected: list[dict] = []
    seen_links: set[str] = set()

    for url in config.SOURCES:
        log.info("Загружаю: %s", url)
        try:
            feed = feedparser.parse(url)
        except Exception as exc:  # noqa: BLE001
            log.warning("  ⚠ ошибка загрузки: %s", exc)
            continue

        if feed.bozo:
            log.warning("  ⚠ источник вернул некорректный XML")

        entries = feed.entries or []
        log.info("  найдено записей: %d", len(entries))

        for entry in entries:
            title = clean_text(entry.get("title", ""))
            summary = clean_text(entry.get("summary", "") or entry.get("description", ""))
            link = entry.get("link", "").strip()

            if not title or not link:
                continue
            if link in seen_links:
                continue

            # Фильтр по дате
            pub_date = parse_entry_date(entry)
            if pub_date < cutoff:
                continue

            combined = f"{title} {summary}"

            # Чёрный список — отсекаем сразу
            if matches_blacklist(combined):
                continue

            # Белый список — должно быть хотя бы одно ключевое слово
            if not matches_keywords(combined):
                continue

            seen_links.add(link)
            collected.append({
                "title": title,
                "link": link,
                "summary": summary[:500],  # ограничим длину для ТВ-титров
                "pub_date": pub_date,
                "source": feed.feed.get("title", url),
            })

    # Сортируем по дате: свежие сверху
    collected.sort(key=lambda x: x["pub_date"], reverse=True)
    log.info("Итого после фильтрации: %d новостей", len(collected))
    return collected[: config.MAX_ITEMS]


def build_rss(items: list[dict]) -> Element:
    """Формирует XML-дерево RSS 2.0."""
    rss = Element("rss", {
        "version": "2.0",
        "xmlns:atom": "http://www.w3.org/2005/Atom",
    })
    channel = SubElement(rss, "channel")

    SubElement(channel, "title").text = config.CHANNEL_TITLE
    SubElement(channel, "link").text = config.CHANNEL_LINK
    SubElement(channel, "description").text = config.CHANNEL_DESCRIPTION
    SubElement(channel, "language").text = config.CHANNEL_LANGUAGE
    SubElement(channel, "lastBuildDate").text = format_datetime(
        datetime.now(timezone.utc)
    )
    SubElement(channel, "generator").text = "corp-tv-feed-generator"

    atom_link = SubElement(channel, "atom:link")
    atom_link.set("href", f"{config.CHANNEL_LINK}/rss.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    for item in items:
        node = SubElement(channel, "item")
        SubElement(node, "title").text = item["title"]
        SubElement(node, "link").text = item["link"]
        SubElement(node, "description").text = item["summary"]
        SubElement(node, "pubDate").text = format_datetime(item["pub_date"])
        SubElement(node, "guid").text = item["link"]
        SubElement(node, "category").text = item["source"]

    return rss


def save_rss(rss: Element, path: str) -> None:
    """Сохраняет XML в файл с красивыми отступами."""
    indent(rss, space="  ")
    tree = ElementTree(rss)
    tree.write(path, encoding="utf-8", xml_declaration=True)
    log.info("Лента сохранена: %s", path)


def main() -> int:
    log.info("=== Старт генерации ленты ===")
    items = fetch_news()

    if not items:
        log.warning("Новости не найдены — лента будет пустой")

    rss = build_rss(items)
    save_rss(rss, config.OUTPUT_FILE)
    log.info("=== Готово ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())