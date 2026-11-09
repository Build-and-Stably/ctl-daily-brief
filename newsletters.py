"""CTL 데일리 브리프 뉴스레터 수집기.

구글 드라이브 폴더(서비스 계정에 뷰어로 공유)의 PDF·이미지 뉴스레터를 읽어
CTL·AI 관련 문장을 찾고 docs/newsletters.json에 저장한다.
글자가 없는 쪽(스캔·이미지)은 흑백으로 바꿔 Tesseract(한국어)로 읽는다.

필요: pip install pymupdf google-auth requests, tesseract-ocr(+kor)
인증: GDRIVE_SA_KEY(서비스 계정 JSON 내용) 또는 GDRIVE_SA_KEY_FILE(JSON 파일 경로)
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pymupdf
from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "docs", "newsletters.json")
DRIVE = "https://www.googleapis.com/drive/v3/files"
TESSERACT = os.environ.get("TESSERACT", "tesseract")
MIN_PAGE_CHARS = 80  # 이보다 글자가 적은 쪽은 이미지로 보고 OCR한다
OCR_DPI = 200  # 흑백 200dpi가 300dpi나 컬러보다 뉴스레터에서 더 잘 읽혔다
UNIV_RE = re.compile(r"([가-힣]{2,12}(?:대학교|대학))")
PARSER_VERSION = 1  # 글자 읽는 방식을 바꾸면 올려서 기존 파일도 다시 읽게 한다
HANGUL_GAP_RE = re.compile(r"(?<=[가-힣]) (?=[가-힣](?:[^가-힣]|$))")


def now_kst():
    return datetime.now(KST)


def drive_session():
    scopes = ["https://www.googleapis.com/auth/drive.readonly"]
    if os.environ.get("GDRIVE_SA_KEY"):
        cred = service_account.Credentials.from_service_account_info(json.loads(os.environ["GDRIVE_SA_KEY"]),
                                                                      scopes=scopes)
    elif os.environ.get("GDRIVE_SA_KEY_FILE"):
        cred = service_account.Credentials.from_service_account_file(os.environ["GDRIVE_SA_KEY_FILE"], scopes=scopes)
    else:
        return None
    return AuthorizedSession(cred)


def list_files(s, folder):
    files, token = [], None
    while True:
        r = s.get(DRIVE, params={
            "q": f"'{folder}' in parents and trashed=false",
            "fields": "nextPageToken, files(id,name,mimeType,md5Checksum,createdTime,modifiedTime,webViewLink)",
            "pageSize": 200, "pageToken": token,
            "supportsAllDrives": "true", "includeItemsFromAllDrives": "true"})
        r.raise_for_status()
        data = r.json()
        files += data["files"]
        token = data.get("nextPageToken")
        if not token:
            return files


def fix_ocr_spacing(text):
    """한국어 OCR은 '인 덕 대 학 교'처럼 글자마다 띄우는 일이 많아, 한 글자씩 끊긴 줄은 붙인다."""
    lines = []
    for line in text.splitlines():
        toks = line.split()
        single = sum(1 for t in toks if re.fullmatch(r"[가-힣]", t))
        if toks and single / len(toks) >= 0.4:
            prev = None
            while prev != line:
                prev, line = line, HANGUL_GAP_RE.sub("", line)
        lines.append(line)
    return fix_ocr_ai("\n".join(lines))


def fix_ocr_ai(text):
    """Tesseract 한국어 모델은 'AI'를 'Al'이나 한글 '시'로 읽는 일이 잦다. 확실한 문맥만 고친다."""
    text = re.sub(r"(?<![A-Za-z])Al(?![A-Za-z])", "AI", text)
    text = re.sub(r"생\s?성형\s?(?:시|AI)", "생성형 AI", text)
    text = re.sub(r"\(\s*시\s*\)", "(AI)", text)
    text = re.sub(r"(?:(?<=[\s'‘“(])|^)시(?=\s?(?:활용|기반|역량|리터러시|플랫폼|도구|윤리|융합|챗봇|시대))",
                  "AI", text, flags=re.M)
    return text


def ocr_png(path):
    r = subprocess.run([TESSERACT, path, "-", "-l", "kor+eng", "--psm", "4"], capture_output=True, timeout=180)
    return fix_ocr_spacing(r.stdout.decode("utf-8", "replace"))


def read_pages(data, mime, tmp):
    """쪽별 (본문, 읽은 방법) 목록을 돌려준다."""
    if mime.startswith("image/"):
        doc = pymupdf.open(stream=data, filetype=mime.split("/")[1])
    else:
        doc = pymupdf.open(stream=data, filetype="pdf")
    pages = []
    for n, pg in enumerate(doc):
        text = pg.get_text() if not mime.startswith("image/") else ""
        if len(re.sub(r"\s", "", text)) >= MIN_PAGE_CHARS:
            pages.append((text, "text"))
            continue
        png = os.path.join(tmp, f"p{n}.png")
        pg.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY).save(png)
        pages.append((ocr_png(png), "ocr"))
    return pages


def sentences(text):
    text = re.sub(r"[ \t]+", " ", text)
    # 줄바꿈이 문장 중간에 들어간 경우가 많아 한글끼리 이어지는 줄바꿈은 붙인다
    text = re.sub(r"(?<=[가-힣,])\n(?=[가-힣])", "", text)
    text = re.sub(r"\n(?=[가-힣a-z])", " ", text)
    for part in re.split(r"(?<=[.!?。])\s+|\n+", text):
        part = part.strip(" ·•-–—*|")
        if len(re.findall(r"[가-힣A-Za-z]", part)) >= 8:
            yield part


def word_hit(word, text):
    if re.fullmatch(r"[A-Za-z]+", word):  # AI·CTL 같은 영문 약어는 단어 경계로 찾는다 (MAIL, CHAIR 등 오인 방지)
        return re.search(rf"(?<![A-Za-z]){word}(?![A-Za-z])", text) is not None
    return word.replace(" ", "") in re.sub(r"\s", "", text)


def find_hits(pages, topics, per_topic):
    hits = {t: [] for t in topics}
    for n, (text, _) in enumerate(pages, 1):
        for sent in sentences(text):
            for topic, words in topics.items():
                matched = [w for w in words if word_hit(w, sent)]
                if matched and len(hits[topic]) < per_topic and \
                        not any(h["text"] == sent for h in hits[topic]):
                    hits[topic].append({"page": n, "text": sent[:220] + ("…" if len(sent) > 220 else ""),
                                        "words": matched})
    return hits


def count_words(pages, words):
    full = "\n".join(t for t, _ in pages)
    return sum(1 for w in words if word_hit(w, full))


def title_of(name):
    t = re.sub(r"\.(pdf|jpe?g|png)$", "", name, flags=re.I)
    t = re.sub(r"\s*\(\d+\)$", "", t)  # 내려받기 중복 표시 '(1)'
    t = re.sub(r"^\d+\.\s*", "", t)
    return t.replace("_", " ").strip()


def univ_of(name):
    m = UNIV_RE.search(name)
    return m.group(1) if m else ""


def process(s, f, cfg, tmp):
    data = s.get(f"{DRIVE}/{f['id']}", params={"alt": "media", "supportsAllDrives": "true"}).content
    pages = read_pages(data, f["mimeType"], tmp)
    topics = cfg["priority_topics"]
    hits = find_hits(pages, topics, cfg.get("snippets_per_topic", 4))
    full = "\n".join(t for t, _ in pages)
    return {
        "id": f["id"],
        "md5": f.get("md5Checksum"),
        "modified": f["modifiedTime"],
        "title": title_of(f["name"]),
        "univ": univ_of(f["name"]),
        "link": f.get("webViewLink") or f"https://drive.google.com/file/d/{f['id']}/view",
        "received": datetime.fromisoformat(f["createdTime"].replace("Z", "+00:00")).astimezone(KST)
                    .isoformat(timespec="minutes"),
        "pages": len(pages),
        "ocr_pages": sum(1 for _, m in pages if m == "ocr"),
        "chars": len(re.sub(r"\s", "", full)),
        "score": {t: count_words(pages, w) for t, w in topics.items()},
        "hits": hits,
        "other": [x for x in sentences(full)][:3],  # 관련 문장이 없을 때 보여줄 첫 문장들
    }


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    with open(os.path.join(ROOT, "config.json"), encoding="utf-8") as fp:
        cfg = json.load(fp)["newsletter"]
    s = drive_session()
    if s is None:
        print("GDRIVE_SA_KEY가 없어 뉴스레터 수집을 건너뜁니다.")
        return
    old = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as fp:
            old = {n["id"]: n for n in json.load(fp).get("items", [])}

    files = [f for f in list_files(s, cfg["drive_folder_id"])
             if f["mimeType"] == "application/pdf" or f["mimeType"].startswith("image/")]
    files.sort(key=lambda f: f["createdTime"])
    items, seen_md5, errors, added = [], set(), [], 0
    with tempfile.TemporaryDirectory() as tmp:
        for f in files:
            if f.get("md5Checksum") in seen_md5:  # 같은 파일을 두 번 올린 경우
                continue
            seen_md5.add(f.get("md5Checksum"))
            prev = old.get(f["id"])
            # 핵심어 설정이 바뀌면 다시 읽도록 설정 지문도 비교한다
            if prev and prev["modified"] == f["modifiedTime"] and prev.get("cfg") == cfg_sig(cfg):
                items.append(prev)
                continue
            try:
                item = process(s, f, cfg, tmp)
                item["cfg"] = cfg_sig(cfg)
                items.append(item)
                added += 1
                print(f"  읽음: {item['title']} ({item['pages']}쪽, OCR {item['ocr_pages']}쪽) {item['score']}")
            except Exception as e:  # 한 파일이 깨져도 나머지는 계속
                errors.append({"name": f["name"], "error": str(e)[:200]})
                if prev:
                    items.append(prev)

    items.sort(key=lambda n: n["received"], reverse=True)
    with open(OUT, "w", encoding="utf-8") as fp:
        json.dump({"updated": now_kst().isoformat(timespec="minutes"), "errors": errors, "items": items},
                  fp, ensure_ascii=False, indent=1)
    print(f"뉴스레터 {len(items)}건 (새로 읽음 {added}건), 실패 {len(errors)}건")
    for e in errors:
        print("  실패:", e["name"], e["error"])


def cfg_sig(cfg):
    sig = json.dumps([PARSER_VERSION, cfg["priority_topics"]], sort_keys=True)
    return hashlib.md5(sig.encode()).hexdigest()[:8]


if __name__ == "__main__":
    main()
