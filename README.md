# MimiEcho 🔔

> 네이버 카페 게시글을 자동으로 AI 요약하여 Discord에 전송하는 봇

## 주요 기능

| 모듈 | 설명 |
|------|------|
| **Scraper** | Playwright(헤드리스 Chrome)로 네이버 로그인 → 지정 게시판 신규 글 수집 |
| **Summarizer** | Claude AI(Anthropic)로 핵심 주제 / 결정 사항 / Action Items 요약 |
| **Notifier** | Discord Webhook으로 Embed 형식 전송 (제목, 작성일, 요약, 원문 링크) |
| **Workflow** | GitHub Actions — 매주 토요일 16:00 KST 자동 실행 + 수동 실행 지원 |

---

## 디렉토리 구조

```
MimiEcho/
├── .github/
│   └── workflows/
│       └── weekly_summary.yml   # GitHub Actions 워크플로우
├── src/
│   ├── __init__.py
│   ├── scraper.py               # 네이버 카페 스크래퍼
│   ├── summarizer.py            # Claude AI 요약기
│   └── notifier.py              # Discord 알림 발송
├── main.py                      # 메인 진입점
├── requirements.txt
├── .env.example                 # 환경변수 예시
└── last_processed_id.txt        # 마지막 처리 게시글 ID (상태 파일)
```

---

## 설치 및 로컬 실행

### 1. 의존성 설치

```bash
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium   # Linux only
```

### 2. 환경변수 설정

```bash
cp .env.example .env
# .env 파일을 열어 각 값을 입력하세요
```

| 변수 | 설명 |
|------|------|
| `NAVER_ID` | 네이버 아이디 |
| `NAVER_PW` | 네이버 비밀번호 |
| `CAFE_CLUB_ID` | 카페 고유 숫자 ID (`search.clubid=` 파라미터) |
| `CAFE_BOARD_ID` | 게시판(메뉴) 숫자 ID (`search.menuid=` 파라미터) |
| `DISCORD_WEBHOOK_URL` | Discord 채널 Webhook URL |
| `ANTHROPIC_API_KEY` | [Anthropic Console](https://console.anthropic.com/) API 키 |

#### CAFE_CLUB_ID / CAFE_BOARD_ID 찾는 방법

카페 게시판에서 URL을 확인하세요:
```
https://cafe.naver.com/mycafe?iframe_url=/ArticleList.nhn
  ?search.clubid=12345678          ← CAFE_CLUB_ID
  &search.menuid=123               ← CAFE_BOARD_ID
```

### 3. 실행

```bash
python main.py
```

---

## GitHub Actions 설정

### Repository Secrets 등록

`Settings → Secrets and variables → Actions → New repository secret`에서 아래 시크릿을 등록하세요:

- `NAVER_ID`
- `NAVER_PW`
- `CAFE_CLUB_ID`
- `CAFE_BOARD_ID`
- `DISCORD_WEBHOOK_URL`
- `ANTHROPIC_API_KEY`

### 자동 실행 스케줄

| 트리거 | 조건 |
|--------|------|
| 자동 | 매주 **토요일 16:00 KST** (`cron: "0 7 * * 6"`) |
| 수동 | GitHub Actions → `workflow_dispatch` → Run workflow |

### 상태 파일 관리

`last_processed_id.txt`는 워크플로우 실행 후 자동으로 커밋됩니다.
이 파일이 `0`이면 다음 실행 시 최신 50개 글 중 새 글을 수집합니다.

---

## Discord 출력 예시

```
📝 [2025-01-15 정기 회의록]
───────────────────────────
📋 핵심 주제
- 신규 서비스 런칭 일정 논의
- 마케팅 예산 조정 건

✅ 결정된 사항
- 런칭일: 2월 1일로 확정
- 예산: 전월 대비 20% 증액

📌 향후 행동 지침
- 개발팀: 1/25까지 QA 완료
- 마케팅팀: SNS 홍보 콘텐츠 1/28까지 준비

✍️ 작성자: 홍길동   📅 작성일: 2025.01.15.
🔗 [게시글 바로가기]
```

---

## 주의사항

- 네이버 계정에 **2단계 인증**이 활성화된 경우 자동 로그인이 실패할 수 있습니다. 전용 계정 사용을 권장합니다.
- 과도한 스크래핑은 네이버 정책에 위배될 수 있으므로 주 1회 실행을 권장합니다.
- `NAVER_PW`는 반드시 **GitHub Secrets**에만 보관하고 코드에 하드코딩하지 마세요.
