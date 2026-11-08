# Automated Blog — 플랫폼별 Playwright 프로젝트

플랫폼별 폴더 아래에 URL이 다른 블로그를 각각 둡니다. 노션 토큰과 블로그별 데이터소스 ID는 최상위 `.env` 한 파일에서 관리하고, 로그인 프로필과 HTML 백업은 각 블로그 폴더에 보관합니다.

```text
Automated Blog/
├─ requirements.txt
├─ 설치.bat
├─ .env.example  → 최상위 .env로 복사
├─ images/
│  ├─ tistory/TstoryBlog1/  ↔ tistory/TstoryBlog1
│  ├─ tistory/TstoryBlog2/  ↔ tistory/TstoryBlog2
│  ├─ blogspot/Blogspot1/   ↔ blogspot/Blogspot1
│  └─ blogspot/Blogspot2/   (추가할 블로그용)
├─ tistory/
│  ├─ shared/ (티스토리 공통 실행·노션·이미지·게시 코드)
│  ├─ TstoryBlog1/ (seoebear.tistory.com)
│  └─ TstoryBlog2/ (takeanews.tistory.com)
└─ blogspot/
   └─ Blogspot1/ (jmlim8038.blogspot.com)
```

## 블로그 주소

- `tistory/TstoryBlog1`: https://seoebear.tistory.com/ (관리자 접속에 기존 주소 사용)
- `tistory/TstoryBlog2`: https://takeanews.tistory.com/
- `blogspot/Blogspot1`: https://jmlim8038.blogspot.com/

## 1. 준비

Windows PowerShell에서 `Automated Blog` 폴더에 이동해 다음을 실행합니다.

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
```

또는 `설치.bat`을 실행하세요. 이미 설치된 Playwright는 다시 설치할 필요가 없습니다.

## 2. 블로그마다 서로 다른 노션 데이터베이스 연결

최상위 `.env`에 공통 `NOTION_API_KEY`는 한 번만 입력합니다. 블로그마다 다른 데이터소스 ID는 `TSTORY_BLOG1_NOTION_DATA_SOURCE_ID`처럼 구분해서 입력합니다. `TstoryBlog2`의 데이터소스 ID는 아직 비어 있습니다.

Notion에서 페이지 안에 데이터베이스를 만들어 다음 속성을 추가하세요.

| 속성 | 유형 | 필수 |
|---|---|---|
| 글 제목 | 제목 | 필수 |
| 번호 | 숫자 | 필수 |
| 작성여부 | 체크박스 | 필수 |
| 게시여부 | 체크박스 | 필수 |
| 임시저장여부 | 체크박스 | 필수 |
| 임시저장일 | 날짜 | 선택 |
| 임시저장URL | URL | 선택 |
| 카테고리 | 선택 | TstoryBlog1 필수, TstoryBlog2 선택 |

개별 글 페이지 안에는 HTML 코드 블록을 보관합니다. 본문에는 게시할 태그의 HTML을 넣고, 글 제목은 DB의 `글 제목`에서 가져옵니다.
Notion API v2025-09-03 기준 **데이터베이스 ID가 아닌 데이터소스 ID**가 필요합니다.
개인 액세스 토큰은 워크스페이스 접근 범위에서 동작하고, 일반 내부 연결은 해당 DB 접근 권한을 별도로 받아야 합니다.

최상위 폴더에서 설정 파일을 만들고, 실행할 블로그 폴더로 이동합니다.

```powershell
Copy-Item .env.example .env
notepad .env
cd tistory/TstoryBlog1
python run.py check
python run.py list
python run.py login
python run.py preview --number 19
python run.py draft --number 19
```

`Blogspot1`은 최상위 `.env`에 `BLOGSPOT_BLOG1_BLOGGER_BLOG_ID`도 입력해야 합니다. Blogger 관리자 URL에 보이는 숫자 ID이며 공개 블로그 주소와 다릅니다.

## 3. 안전장치

- 처음 실행할 때는 **초안 저장까지만** 시도합니다. 공개/발행 버튼은 자동 클릭하지 않습니다.
- 수정 중 실패해도 **게시여부**와 **발행일**은 변경하지 않습니다.
- 본문 HTML은 `exports` 폴더에 자동 백업합니다.
- **임시저장여부**는 티스토리의 저장된 임시글을 다시 불러와 자동 확인한 뒤에만 체크됩니다.
- 노션에 이미 `게시여부` 또는 `임시저장여부`가 체크된 글은 중복 저장을 방지합니다.
- 티스토리 화면이 변경되면 `tistory/shared/publisher.py`를 한 번 수정합니다. 블로그스팟 코드는 `blogspot/Blogspot1/`에서 관리합니다.
- 티스토리 글의 `IMAGE` 표시에 맞는 로컬 파일은 Playwright로 업로드하고 `IMAGE:01`을 대표 이미지로 지정합니다. 노션 첨부 파일의 자동 다운로드는 지원하지 않습니다.
- `profiles` 폴더에는 로그인 쿠키가 있을 수 있습니다. 외부 전송·Git 업로드 금지.
- `Asia/Seoul` timezone 패키지 의존을 사용하지 않아 Windows ZoneInfo 오류를 피했습니다.

## 4. 나중에 블로그 추가하기

티스토리 블로그를 추가할 때는 기존 블로그 폴더의 `run.py`, `settings.py`, `시작하기.bat`을 새 폴더로 복사합니다. 새 `settings.py`에서 이름·URL·이미지 폴더·환경변수 이름·카테고리 필수 여부를 지정하고, 최상위 `.env`에 새 데이터소스 ID를 추가합니다. 공통 기능은 `tistory/shared/`에서 한 번 수정하면 모든 티스토리 블로그에 적용됩니다. 로그인 정보가 있는 `profiles/`와 원고 `exports/`는 복사하지 마세요. 블로그스팟은 현재 별도 코드입니다.

## 코드 상태

TstoryBlog1은 실제 계정에서 임시저장 및 본문 재열기를 확인했습니다. 다른 블로그는 해당 계정에서 UI 확인이 필요합니다.

## 티스토리 이미지 ALT 규칙 (2026-11 업데이트)

`TstoryBlog1`, `TstoryBlog2`에서 각자의 노션 AI 이름 속성을 ALT 기본값으로 사용합니다.
기존 `<img src="...">` 태그의 ALT를 보완하고 `exports/*.images.json`에 01번 이미지 대표 후보와 해당 블로그의 `images/` 경로를 기록합니다.
티스토리의 `<!-- IMAGE:01 -->`은 이미지 폴더의 `번호_AI이름.png`와 연결합니다. 임시저장할 때 사진을 업로드한 뒤 생성된 티스토리 이미지 코드에 ALT를 넣고 표시 위치에 삽입합니다. 노션 이름을 이미지 캡션에 쓰고 첫 이미지를 대표 이미지로 지정한 다음, 저장된 글을 다시 열어 ALT도 확인합니다.


## v3: 1번~20번 범위 임시저장 기능

각 블로그 폴더에서 독립적으로 실행합니다.

```powershell
python run.py draft-range --from 1 --to 20 --dry-run
python run.py draft-range --from 1 --to 20
```

1번과 20번 모두 포함합니다. 먼저 미리보기로 대상 확인 후 실제 실행하세요.
이미 `게시여부` 또는 `임시저장여부`가 체크된 번호, 작성 전 상태, 누락/중복 번호는 제외됩니다.
실행 중 추가 입력 없이 각 글을 임시저장하고, 저장된 임시글을 자동 확인한 뒤 노션에 기록합니다.
중단되면 이미 확인하고 노션에 기록한 항목은 다음 실행에서 자동 제외됩니다.
현재 공개 발행은 지원하지 않습니다. 로컬 IMAGE 표시 파일을 업로드하고 `IMAGE:01`을 대표 이미지로 지정합니다.
