# MimiEcho — 프로젝트 컨텍스트

## 에이전트 지침

**이 파일은 항상 최신 상태를 유지해야 한다.**
코드를 수정할 때마다 변경 내용이 이 파일에 반영되어 있는지 확인하고, 관련 섹션을 함께 업데이트한다.
업데이트가 필요한 대표적인 경우:
- 모듈 추가/삭제/이름 변경
- 클래스·메서드 시그니처 변경
- 환경변수 추가/삭제
- 모델명, 상수, 기본값 변경
- 실행 흐름 또는 스케줄 변경
- 알려진 제약사항 추가/해소

네이버 카페 특정 게시판의 새 게시글을 자동으로 수집 → Claude AI로 요약 → Discord로 전송하는 Python 봇.
GitHub Actions로 **매주 토요일 16:00 KST**에 자동 실행되며, 수동 실행도 지원한다.

## 디렉토리 구조

```
MimiEcho/
├── .github/workflows/weekly_summary.yml  # GitHub Actions 워크플로우
├── src/
│   ├── scraper.py      # 네이버 카페 스크래퍼 (Playwright 헤드리스 Chrome)
│   ├── summarizer.py   # Claude AI 요약 (Anthropic SDK)
│   └── notifier.py     # Discord Webhook 알림 (Embed 형식)
├── main.py             # 진입점 — 전체 파이프라인 오케스트레이션
├── requirements.txt
├── .env.example        # 필요한 환경변수 목록
└── last_processed_id.txt  # 상태 파일: 마지막으로 처리한 게시글 ID
```

## 실행 흐름 (main.py)

```
last_processed_id.txt 읽기
        ↓
NaverCafeScraper.get_new_posts()   # ID > last_id 인 글만 수집
        ↓
AISummarizer.summarize(post)       # 게시글마다 Claude로 요약
        ↓
DiscordNotifier.send(post, summary) # Discord Embed 전송
        ↓
last_processed_id.txt 업데이트 (최대 ID 저장)
```

## 모듈 상세

### src/scraper.py
- 클래스: `NaverCafeScraper`, 데이터클래스: `CafePost`, 예외: `NaverLoginError` / `ClubIdResolutionError`
- Playwright 헤드리스 Chromium으로 네이버 로그인 (JS 암호화 자동 처리)
- **카페 식별**: 숫자 club_id 대신 텍스트 URL name 사용 (예: `daechi2dongchurch`)
  - `_resolve_club_id(page, cafe_url_name)` 이 실행 시점에 카페 메인 페이지에서 숫자 ID를 자동 추출
  - 추출 전략: iframe src → 페이지 소스 정규식 순서로 시도
- 게시글 목록 조회(`ARTICLE_LIST_URL`)는 내부적으로 숫자 club_id 사용 (Naver API 제약)
- 게시글 읽기(`ARTICLE_READ_URL`)는 `cafe.naver.com/{cafe_url_name}/{article_id}` 형식 (숫자 불필요)
- 네이버 카페는 콘텐츠가 `<iframe id="cafe_main">` 안에 렌더링됨 → `page.frame(name="cafe_main")`으로 접근
- 셀렉터 폴백: Smart Editor 3 (`.se-main-container`) → 구 에디터 (`#tbody`) 순서로 시도
- `max_posts=20` 안전 캡: 첫 실행 시 수백 개 글이 한꺼번에 처리되는 것을 방지

### src/summarizer.py
- 클래스: `AISummarizer`
- 모델: `claude-sonnet-4-6` (기본값, 생성자에서 변경 가능)
- 요약 섹션 3개: `📋 핵심 주제` / `✅ 결정된 사항` / `📌 향후 행동 지침`
- 본문 8,000자 초과 시 자동 트런케이션 후 API 호출
- 시스템 프롬프트와 유저 프롬프트 분리 (`SYSTEM_PROMPT`, `USER_PROMPT_TEMPLATE`)

### src/notifier.py
- 클래스: `DiscordNotifier`
- 메서드: `send(post, summary)` / `send_error(msg)` / `send_no_posts_notice()`
- Discord Embed 색상: Naver 초록 (`0x03C75A`), 에러: 빨강 (`0xFF0000`)
- Discord description 한도(4,096자) 자동 처리

## 필수 환경변수

| 변수 | 설명 |
|------|------|
| `NAVER_COOKIES` | **(권장)** Naver 세션 쿠키 — `NID_AUT=x;NID_SES=y;NID_JKL=z` 형식 |
| `NAVER_ID` | (대안) 네이버 아이디 — 로컬 첫 실행 시에만 사용 가능 |
| `NAVER_PW` | (대안) 네이버 비밀번호 |
| `CAFE_URL_NAME` | 카페 URL의 텍스트 식별자 (예: `daechi2dongchurch`) — 숫자 ID는 자동 추출 |
| `CAFE_BOARD_ID` | 게시판 숫자 ID (`search.menuid=` 파라미터) |
| `DISCORD_WEBHOOK_URL` | Discord 채널 Webhook URL |
| `ANTHROPIC_API_KEY` | Anthropic API 키 |

로컬 실행 시 `.env` 파일로 관리 (`python-dotenv` 자동 로드).
CI 실행 시 GitHub Repository Secrets에서 주입.

### Naver 인증 방식 선택

| | 쿠키(`NAVER_COOKIES`) | ID/PW(`NAVER_ID`+`NAVER_PW`) |
|---|---|---|
| GitHub Actions | **가능** | 불가 (기기인증 차단) |
| 로컬 첫 실행 | 가능 | 가능 (기기인증 1회 필요) |
| 추천 | **Yes** | No |

쿠키 얻는 법: Chrome → naver.com 로그인 → F12 → Application → Cookies → .naver.com → `NID_AUT`, `NID_SES`, `NID_JKL` 값 복사

## 상태 관리

`last_processed_id.txt` — 마지막으로 Discord에 전송한 게시글의 article ID를 저장.
- `0` → 초기 상태 (다음 실행 시 최신 50개 중 새 글 수집)
- GitHub Actions 워크플로우가 실행 후 이 파일을 자동으로 커밋 (`[skip ci]` 태그)

## 로컬 개발

```bash
# 의존성 설치
pip install -r requirements.txt
playwright install chromium

# 환경변수 설정
cp .env.example .env   # 값 입력 후 저장

# 실행
python main.py
```

## GitHub Actions 스케줄

- **자동**: `cron: "0 7 * * 6"` = 매주 토요일 07:00 UTC = 16:00 KST
- **수동**: GitHub UI → Actions → `MimiEcho Weekly Summary` → `Run workflow`
- `workflow_dispatch` 입력값 `dry_run`은 현재 환경변수로 전달되지만 `main.py`에서 아직 처리 로직 미구현 (향후 확장 포인트)

## 알려진 제약 / 주의사항

- 네이버 2단계 인증 계정은 자동 로그인 불가 → 전용 계정 사용 권장
- 네이버가 로그인 후 "로그인 상태 유지" 팝업을 띄울 경우 자동으로 처리함 (`#new\\.save` 셀렉터)
- 카페 게시판 HTML 구조가 변경되면 `TITLE_SELECTORS` / `CONTENT_SELECTORS` 상수 업데이트 필요
- Playwright는 GitHub Actions `ubuntu-latest`에서 `playwright install-deps chromium` 필수
