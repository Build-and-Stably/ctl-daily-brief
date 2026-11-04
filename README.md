# CTL 데일리 브리프

국내 대학 교수학습센터·RISE·교육정책 소식을 매일 자동으로 모아 보여주는 페이지입니다.

- **페이지**: GitHub Pages (`docs/index.html`)
- **수집**: `collect.py` — GitHub Actions가 매일 06:30, 12:30(KST)에 실행하고 `docs/items.json`을 갱신합니다.
- **소스**: 구글 뉴스 검색 RSS, 한국대학신문·교수신문·대학저널·베리타스알파·에듀진 RSS, 정책브리핑(교육부) — 모두 공식 RSS만 사용합니다(스크래핑 없음).

## 자주 하는 수정 — `config.json`만 고치면 됩니다

| 항목 | 설명 |
|---|---|
| `google_news_queries` | 구글 뉴스 검색어. 따옴표로 감싸면 정확히 일치하는 표현만 찾습니다. `{"q": 검색어, "require": [...]}` 형태로 쓰면 제목에 `require` 단어가 있는 기사만 남깁니다. |
| `full_feeds` | 전체 기사를 받는 언론사 RSS. 아래 `filter_keywords`가 들어간 기사만 남깁니다. |
| `filter_keywords` | 언론사 RSS에서 남길 기사의 키워드 |
| `tags` | 페이지 상단 분류 칩. 제목·요약에 단어가 있으면 해당 분류가 붙습니다. |
| `exclude_sources` | 제외할 매체 이름 |
| `keep_days` | 기사 보관 기간(일) |

GitHub 웹에서 `config.json`을 열어 연필 아이콘으로 바로 수정해도 되고, 다음 수집 때부터 반영됩니다.
바로 반영하려면 **Actions → 매일 소식 수집 → Run workflow**를 누르세요.

## 네이버 뉴스 추가 (선택)

1. https://developers.naver.com 에서 애플리케이션 등록 → 사용 API: **검색**
2. 저장소 **Settings → Secrets and variables → Actions**에 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` 등록
3. 다음 수집부터 자동으로 네이버 뉴스도 함께 모읍니다(검색어는 `google_news_queries`를 같이 사용).

## 내 PC에서 실행해 보기

```
py collect.py
py -m http.server -d docs 8000   # 브라우저에서 http://localhost:8000
```
