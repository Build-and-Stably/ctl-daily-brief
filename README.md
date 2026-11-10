# CTL 데일리 브리프

국내 대학 교수학습·교육과정·원격교육·RISE·교육정책 소식을 매일 자동으로 모아 보여주는 페이지입니다.

- **페이지**: GitHub Pages (`docs/index.html`)
- **수집**: `collect.py` — GitHub Actions가 매일 05:00, 12:30(KST)에 실행하고(GitHub 사정으로 1~4시간 늦어질 수 있음) `docs/items.json`을 갱신합니다.
- **뉴스레터**: `newsletters.py` — 공문으로 받은 다른 대학 뉴스레터(PDF·이미지)를 구글 드라이브 폴더에서 읽어 `docs/newsletters.json`에 저장합니다. 페이지의 **뉴스레터** 탭에서 CTL·AI 관련 문장이 있는 호를 먼저 보여줍니다.
- **소스**: 구글 뉴스 검색 RSS, 한국대학신문·교수신문·대학저널·베리타스알파·에듀진 RSS, 정책브리핑(교육부) — 모두 공식 RSS만 사용합니다(스크래핑 없음).

## 자주 하는 수정 — `config.json`만 고치면 됩니다

| 항목 | 설명 |
|---|---|
| `google_news_queries` | 구글 뉴스 검색어. 따옴표로 감싸면 정확히 일치하는 표현만 찾습니다. `{"q": 검색어, "require": [...]}` 형태로 쓰면 제목에 `require` 단어가 있는 기사만 남깁니다. |
| `full_feeds` | 전체 기사를 받는 언론사 RSS. 아래 `filter_keywords`가 들어간 기사만 남깁니다. |
| `filter_keywords` | 언론사 RSS에서 남길 기사의 키워드 |
| `tags` | 페이지 상단 분류 칩. 제목·요약에 단어가 있으면 해당 분류가 붙습니다. |
| `exclude_sources` | 제외할 매체 이름 |
| `exclude_title_words` | 제목에 이 단어가 있으면 제외 (예: 북한). `{"word": [...], "unless": [...]}`로 쓰면 `unless` 단어가 함께 있는 기사는 남깁니다. |
| `keep_days` | 기사 보관 기간(일) |
| `newsletter.drive_folder_id` | 뉴스레터 PDF를 넣는 구글 드라이브 폴더 ID |
| `newsletter.priority_topics` | 뉴스레터에서 먼저 보여줄 주제(CTL, AI)와 핵심어. 영문 약어(AI, CTL)는 단어 단위로 찾습니다. 바꾸면 다음 수집 때 모든 뉴스레터를 다시 읽습니다. |

GitHub 웹에서 `config.json`을 열어 연필 아이콘으로 바로 수정해도 되고, 다음 수집 때부터 반영됩니다.
바로 반영하려면 **Actions → 매일 소식 수집 → Run workflow**를 누르세요.

## 네이버 뉴스 추가 (선택)

1. https://developers.naver.com 에서 애플리케이션 등록 → 사용 API: **검색**
2. 저장소 **Settings → Secrets and variables → Actions**에 `NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` 등록
3. 다음 수집부터 자동으로 네이버 뉴스도 함께 모읍니다(검색어는 `google_news_queries`를 같이 사용).

## 뉴스레터 넣기

1. 구글 드라이브의 뉴스레터 폴더에 PDF(또는 JPG·PNG)를 넣습니다. 파일 이름에 대학명이 있으면 대학이 자동으로 표시됩니다.
2. 다음 수집(05:00·12:30) 때 새 파일만 읽습니다. 같은 파일을 두 번 넣어도 한 번만 나옵니다. 폴더에서 지우면 페이지에서도 빠집니다.
3. 글자가 없는 쪽(스캔·이미지)은 흑백으로 바꿔 OCR(Tesseract 한국어)로 읽으므로 오탈자가 섞일 수 있습니다.

폴더는 서비스 계정(`ctl-brief-reader@ctl-brief.iam.gserviceaccount.com`)에 **뷰어**로 공유되어 있어야 하고, 그 키(JSON)는 저장소 Secrets의 `GDRIVE_SA_KEY`에 들어 있습니다.
폴더 공유는 "링크가 있는 모든 사용자 — 뷰어"로 되어 있어 동료도 페이지의 원문 링크를 열 수 있습니다(새로 넣는 파일도 폴더 설정을 따릅니다).

### 드라이브 폴더가 뉴스레터 탭의 원본입니다

- 페이지의 원문 링크는 드라이브 파일을 직접 가리키므로 **파일을 지우면 링크가 끊기고, 다음 수집 때 탭에서도 빠집니다.** 탭에 남겨 둘 뉴스레터는 지우지 마세요.
- 탭에서 내리고 싶을 때만 폴더에서 지우거나 다른 폴더로 옮기면 됩니다.
- 같은 폴더 안에서 이름을 바꾸는 것은 괜찮습니다(파일 ID가 같아 링크가 유지됩니다).

## 내 PC에서 실행해 보기

```
py collect.py
# 뉴스레터 (Tesseract 설치 필요, 키 파일 경로 지정)
$env:GDRIVE_SA_KEY_FILE="키파일.json"; py newsletters.py
py -m http.server -d docs 8000   # 브라우저에서 http://localhost:8000
```
