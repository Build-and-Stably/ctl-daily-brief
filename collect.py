"""CTL 데일리 브리프 수집기.

config.json의 RSS·검색어로 기사를 모아 중복을 정리하고 docs/items.json에 누적 저장한다.
외부 패키지 없이 파이썬 표준 라이브러리만 사용한다.
"""
import difflib
import hashlib
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "docs", "items.json")
UA = "Mozilla/5.0 (CTL-daily-brief; +https://github.com)"

# 대학명처럼 보이지만 특정 대학이 아닌 말
UNIV_STOP = {
    "전문대", "국립대", "사립대", "지방대", "지역대", "거점대", "명문대", "일반대", "수도권대", "비수도권대",
    "글로컬대", "연합대", "해외대", "외국대", "신설대", "주요대", "전국대", "의과대", "간호대", "사범대",
    "공과대", "교육대", "경영대", "미래대", "우리대", "해당대", "협력대", "참여대", "선정대", "우수대",
    "부실대", "특성화대", "원격대", "사이버대", "국립의과대", "각대", "타대", "본대", "상위대", "혁신대",
    "지역전문대", "지방전문대", "서울전문대", "국내대", "세계대", "한국대",
    "지역의대", "법과대", "국공립대", "중심대", "AI중심대", "연구중심대", "교육중심대",
}
UNIV_RE = re.compile(r"([가-힣]{2,12}(?:대학교|대학|대))(?:에서|으로|와|과|은|는|이|가|의|에|도|를|을|로)?(?![가-힣])")


def now_kst():
    return datetime.now(KST)


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def clean_text(s, limit=None):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    s = re.sub(r"\s+", " ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def parse_date(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError):
        d = None
    if d is None:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=KST)  # 국내 언론사 RSS는 시간대 없이 KST로 내보낸다
    return d.astimezone(KST)


def norm_key(title):
    return re.sub(r"[^0-9A-Za-z가-힣]", "", title).lower()


def find_univs(title):
    found = []
    for m in UNIV_RE.finditer(title):
        name = m.group(1)
        name = re.sub(r"대학교$|대학$", "대", name)
        if name in UNIV_STOP or name in found:
            continue
        found.append(name)
    return found


def word_hit(word, text):
    if re.fullmatch(r"[A-Za-z]+", word):  # AI·RISE 같은 영문 약어는 단어 경계로 찾는다 (said, main, enterprise 등 오인 방지)
        return re.search(rf"(?<![A-Za-z]){word}(?![A-Za-z])", text, re.I) is not None
    return word.lower() in text.lower()


def find_tags(text, source, tag_rules):
    tags = [t for t, words in tag_rules.items() if any(word_hit(w, text) for w in words)]
    if source == "대한민국 정책브리핑" and "정부·기관" not in tags:
        tags.append("정부·기관")
    return tags


def parse_rss(raw):
    root = ET.fromstring(raw)
    dc = "{http://purl.org/dc/elements/1.1/}date"
    for it in root.iter("item"):
        src = it.find("source")
        yield {
            "title": clean_text(it.findtext("title")),
            "link": (it.findtext("link") or "").strip(),
            "desc": it.findtext("description") or "",
            "date": it.findtext("pubDate") or it.findtext(dc),
            "source": src.text.strip() if src is not None and src.text else None,
        }


def query_list(queries):
    """설정의 검색어는 문자열 또는 {"q": 검색어, "require": [제목에 꼭 있어야 할 말]} 형태다."""
    return [q if isinstance(q, dict) else {"q": q} for q in queries]


def collect_google(queries, status):
    out = []
    for qd in query_list(queries):
        q, require = qd["q"], qd.get("require")
        url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {"q": q + " when:7d", "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        try:
            items = list(parse_rss(fetch(url)))
            status.append({"name": f"구글 뉴스: {q}", "ok": True, "count": len(items)})
        except Exception as e:  # 한 피드가 실패해도 나머지는 계속 수집
            status.append({"name": f"구글 뉴스: {q}", "ok": False, "error": str(e)[:200]})
            continue
        for it in items:
            source = it["source"] or "구글 뉴스"
            title = re.sub(r"\s+-\s+" + re.escape(source) + r"$", "", it["title"])
            if require and not any(w in title for w in require):
                continue
            # 구글 뉴스 설명은 제목 링크 반복이라 요약으로 쓰지 않는다
            out.append({**it, "title": title, "source": source, "summary": "", "via": f"구글 뉴스 · {q}", "direct": False})
    return out


def collect_feeds(feeds, keywords, status):
    out = []
    for f in feeds:
        try:
            items = list(parse_rss(fetch(f["url"])))
        except Exception as e:
            status.append({"name": f["name"] + " RSS", "ok": False, "error": str(e)[:200]})
            continue
        kept = 0
        for it in items:
            text = it["title"] + " " + clean_text(it["desc"])
            if not any(word_hit(k, text) for k in keywords):
                continue
            kept += 1
            out.append({**it, "source": f["name"], "summary": clean_text(it["desc"], 160),
                        "via": f["name"] + " RSS", "direct": True})
        status.append({"name": f["name"] + " RSS", "ok": True, "count": kept, "total": len(items)})
    return out


def collect_naver(queries, status):
    cid, secret = os.environ.get("NAVER_CLIENT_ID"), os.environ.get("NAVER_CLIENT_SECRET")
    if not (cid and secret):
        return []
    out = []
    headers = {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret}
    for qd in query_list(queries):
        if "require" in qd:  # 사이트 한정 검색은 네이버에서 의미가 없다
            continue
        q = qd["q"].replace('"', "").strip()
        url = "https://openapi.naver.com/v1/search/news.json?" + urllib.parse.urlencode(
            {"query": q, "display": 30, "sort": "date"})
        try:
            data = json.loads(fetch(url, headers))
            status.append({"name": f"네이버 뉴스: {q}", "ok": True, "count": len(data.get("items", []))})
        except Exception as e:
            status.append({"name": f"네이버 뉴스: {q}", "ok": False, "error": str(e)[:200]})
            continue
        for it in data.get("items", []):
            link = it.get("originallink") or it.get("link")
            out.append({"title": clean_text(it["title"]), "link": link, "date": it.get("pubDate"),
                        "source": urllib.parse.urlparse(link).netloc.removeprefix("www."),
                        "summary": clean_text(it.get("description"), 160),
                        "via": f"네이버 뉴스 · {q}", "direct": False})
    return out


def excluded(title, rules):
    """제외어는 문자열 또는 {"word": [...], "unless": [제목에 있으면 남길 말]} 형태다."""
    for r in rules:
        if isinstance(r, str):
            r = {"word": [r]}
        if any(w in title for w in r["word"]) and not any(w in title for w in r.get("unless", [])):
            return True
    return False


PARTICLE_RE = re.compile(r"(에서|으로|와|과|은|는|이|가|의|를|을|에|로|도)$")


def title_tokens(title):
    return {PARTICLE_RE.sub("", w) for w in re.findall(r"[0-9A-Za-z가-힣]{3,}", title)} - {""}


def assign_groups(items):
    """여러 매체가 같은 보도자료를 옮긴 기사들을 한 묶음(group)으로 표시한다. 가장 이른 기사가 대표가 된다."""
    parent = {i["id"]: i["id"] for i in items}

    def root(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    ordered = sorted(items, key=lambda i: i["published"])
    toks = {i["id"]: title_tokens(i["title"]) for i in items}
    for n, a in enumerate(ordered):
        ta = parse_date(a["published"])
        for b in ordered[n + 1:]:
            if (parse_date(b["published"]) - ta) > timedelta(days=2):
                break
            shared = toks[a["id"]] & toks[b["id"]]
            if len(shared) >= 2 and (set(a["univs"]) & set(b["univs"]) or len(shared) >= 3):
                parent[root(b["id"])] = root(a["id"])
    for i in items:
        i["group"] = root(i["id"])


def merge(existing, fresh, tag_rules, keep_days, exclude_sources=(), exclude_words=()):
    now = now_kst()
    cutoff = now - timedelta(days=keep_days)
    by_key = {norm_key(i["title"]): i for i in existing}
    items = list(existing)

    for it in fresh:
        if not it["title"] or not it["link"] or it["source"] in exclude_sources or                 excluded(it["title"], exclude_words):
            continue
        pub = parse_date(it["date"]) or now
        if pub < cutoff or pub > now + timedelta(days=1):
            continue
        key = norm_key(it["title"])
        dup = by_key.get(key)
        if dup is None:  # 제목이 조금 다른 같은 기사(매체별 재전송 등)
            for cand in items:
                if abs((parse_date(cand["published"]) - pub).days) <= 3 and \
                        difflib.SequenceMatcher(None, norm_key(cand["title"]), key).ratio() >= 0.8:
                    dup = cand
                    break
        if dup:
            if it["via"] not in dup["via"]:
                dup["via"].append(it["via"])
            if it["direct"] and not dup.get("direct"):  # 언론사 원문 링크를 우선한다
                dup.update(link=it["link"], source=it["source"], direct=True,
                           summary=it["summary"] or dup["summary"])
            continue
        new = {
            "id": hashlib.md5(key.encode()).hexdigest()[:12],
            "title": it["title"],
            "link": it["link"],
            "source": it["source"],
            "published": pub.isoformat(timespec="minutes"),
            "first_seen": now.isoformat(timespec="minutes"),
            "summary": it["summary"],
            "via": [it["via"]],
            "direct": it["direct"],
        }
        items.append(new)
        by_key[key] = new

    for i in items:  # 설정을 바꾸면 기존 기사에도 바로 반영되도록 매번 다시 계산
        i["tags"] = find_tags(i["title"] + " " + i["summary"], i["source"], tag_rules)
        i["univs"] = find_univs(i["title"])
    items = [i for i in items if parse_date(i["published"]) >= cutoff and i["source"] not in exclude_sources
             and not excluded(i["title"], exclude_words)]
    assign_groups(items)
    items.sort(key=lambda i: i["published"], reverse=True)
    return items


def main():
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as f:
        cfg = json.load(f)
    existing = []
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            existing = json.load(f).get("items", [])

    status = []
    fresh = collect_feeds(cfg["full_feeds"], cfg["filter_keywords"], status)  # 원문 링크가 먼저 자리 잡도록
    fresh += collect_naver(cfg["google_news_queries"], status)
    fresh += collect_google(cfg["google_news_queries"], status)

    items = merge(existing, fresh, cfg["tags"], cfg["keep_days"], set(cfg.get("exclude_sources", [])),
                  cfg.get("exclude_title_words", []))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"updated": now_kst().isoformat(timespec="minutes"), "status": status, "items": items},
                  f, ensure_ascii=False, indent=1)

    added = len(items) - len(existing)
    failed = [s["name"] for s in status if not s["ok"]]
    print(f"총 {len(items)}건 (이번 실행 +{added}건), 실패한 소스 {len(failed)}개")
    for n in failed:
        print("  실패:", n)
    if status and len(failed) == len(status):
        sys.exit(1)


if __name__ == "__main__":
    main()
