# -*- coding: utf-8 -*-
"""이 블로그 전용 실행 진입점 (다른 블로그 폴더에 의존하지 않음)."""
from __future__ import annotations

# Windows 인증서 저장소를 사용해 Notion HTTPS 인증서를 검증합니다.
try:
    import truststore
except ImportError:
    try:
        from pip._vendor import truststore
    except ImportError:
        truststore = None
if truststore is not None:
    truststore.inject_into_ssl()

from settings import BLOG_LABEL, BLOG_URL, IMAGE_DIR
import argparse
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from notion_io import NotionClient, NotionProblem, plain_property, is_checked
from publisher import BlogPublisher, BlogProblem

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent.parent / '.env')

PROP_NAMES = {
    'num': os.getenv('PROP_NUMBER', '번호'),
    'title': os.getenv('PROP_TITLE', '글 제목'),
    'ready': os.getenv('PROP_READY', '작성여부'),
    'published': os.getenv('PROP_PUBLISHED', '게시여부'),
    'draft': os.getenv('PROP_DRAFT', '임시저장여부'),
    'date': os.getenv('PROP_DRAFT_DATE', '임시저장일'),
    'url': os.getenv('PROP_DRAFT_URL', '임시저장URL'),
}


def config():
    token = os.getenv('NOTION_API_KEY', '').strip()
    source = os.getenv('BLOGSPOT_BLOG1_NOTION_DATA_SOURCE_ID', '').strip()
    if not token or not source:
        raise RuntimeError('최상위 .env에 NOTION_API_KEY와 BLOGSPOT_BLOG1_NOTION_DATA_SOURCE_ID를 입력해 주세요.')
    return NotionClient(token, source)


def pick_number(rows: list[dict], number: int) -> dict:
    found = [r for r in rows if plain_property(r, PROP_NAMES['num']) == str(number)]
    if len(found) != 1:
        raise RuntimeError(f'번호 {number}번 검색 결과가 {len(found)}개입니다. 중복/누락된 번호를 확인해 주세요.')
    return found[0]


def validate_schema(schema: dict):
    essentials = [PROP_NAMES[k] for k in ('num', 'title', 'ready', 'published', 'draft')]
    missing = [x for x in essentials if x not in schema]
    if missing:
        raise RuntimeError('노션 데이터소스에 필수 속성이 없습니다: ' + ', '.join(missing)
                           + '\nREADME의 노션 속성 표를 보고 추가한 뒤 다시 실행해 주세요.')
    for key, expected in [('num','number'), ('title','title'), ('ready','checkbox'),
                          ('published','checkbox'), ('draft','checkbox')]:
        name = PROP_NAMES[key]
        if schema[name]['type'] != expected:
            raise RuntimeError(f'노션 속성 {name}은(는) {expected} 유형이어야 합니다.')
    if PROP_NAMES['date'] in schema and schema[PROP_NAMES['date']]['type'] != 'date':
        raise RuntimeError(f'노션 속성 {PROP_NAMES["date"]}은(는) 날짜 유형이어야 합니다.')
    if PROP_NAMES['url'] in schema and schema[PROP_NAMES['url']]['type'] != 'url':
        raise RuntimeError(f'노션 속성 {PROP_NAMES["url"]}은(는) URL 유형이어야 합니다.')


def safe_export(number: int, title: str, html: str) -> Path:
    exports = HERE / 'exports'
    exports.mkdir(exist_ok=True)
    name = re.sub(r'[^a-zA-Z0-9가-힣_-]+', '_', title).strip('_')[:40]
    dst = exports / f'{number:03d}_{name}.html'
    dst.write_text(html, encoding='utf-8')
    return dst


def main():
    parser = argparse.ArgumentParser(description='노션 → 전용 블로그 초안 자동화')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check', help='노션 연결/필드 확인')
    commands.add_parser('list', help='노션 목록 확인, 게시물 수정 없음')
    commands.add_parser('login', help='브라우저 로그인 상태 저장')
    p = commands.add_parser('preview', help='원고 HTML을 로컬 파일로 확인')
    p.add_argument('--number', type=int, required=True)
    d = commands.add_parser('draft', help='선택한 번호만 임시저장 시도')
    d.add_argument('--number', type=int, required=True)
    d.add_argument('--force', action='store_true', help='이미 임시저장 표기된 글 재시도')
    batch = commands.add_parser('draft-range', help='선택한 번호 범위의 미게시 글을 순서대로 임시저장')
    batch.add_argument('--from', dest='start', type=int, required=True, help='시작 번호 (포함)')
    batch.add_argument('--to', dest='end', type=int, required=True, help='끝 번호 (포함)')
    batch.add_argument('--dry-run', action='store_true', help='실제 저장 없이 처리 대상만 확인')
    args = parser.parse_args()
    print(f'\n[{BLOG_LABEL}] {BLOG_URL}')
    if args.command == 'login':
        BlogPublisher(HERE).login()
        return
    notion = config()
    schema = notion.schema()
    validate_schema(schema)
    print('노션 연결 및 필수 속성 확인 완료')
    if PROP_NAMES['date'] not in schema:
        print('안내: 임시저장일 날짜 속성은 선택사항이므로 날짜는 기록하지 않습니다.')
    if args.command == 'check':
        return
    rows = notion.rows()

    if args.command == 'draft-range':
        if args.start < 1 or args.end < args.start:
            raise RuntimeError('범위는 1 이상의 시작 번호와 그보다 크거나 같은 종료 번호로 지정하세요.')
        if args.end - args.start + 1 > 100:
            raise RuntimeError('실수로 대량 처리하지 않도록 한 번에 최대 100개 번호만 처리합니다.')
        # 범위 안의 글만 선택합니다. 완료/기존 임시저장/중복 번호는 제외합니다.
        by_number = {}
        for item in rows:
            s = plain_property(item, PROP_NAMES['num'])
            if s.isdecimal():
                by_number.setdefault(int(s), []).append(item)
        jobs, skips = [], []
        for number in range(args.start, args.end + 1):
            matches = by_number.get(number, [])
            if len(matches) != 1:
                skips.append((number, '번호 없음' if not matches else '노션 번호 중복'))
                continue
            item = matches[0]
            if is_checked(item, PROP_NAMES['published']):
                skips.append((number, '이미 공개 게시됨'))
            elif is_checked(item, PROP_NAMES['draft']):
                skips.append((number, '이미 임시저장됨'))
            elif not is_checked(item, PROP_NAMES['ready']):
                skips.append((number, '작성완료 체크가 꺼짐'))
            elif not plain_property(item, PROP_NAMES['title']).strip():
                skips.append((number, '제목이 비어 있음'))
            else:
                jobs.append((number, item))
        print(f'\n범위 {args.start}~{args.end} | 대상 {len(jobs)}편 | 건너뜀 {len(skips)}편')
        for number, item in jobs:
            print(f'  [대상] {number}: {plain_property(item, PROP_NAMES["title"])}')
        for number, reason in skips:
            print(f'  [제외] {number}: {reason}')
        if args.dry_run:
            print('미리보기만 실행했습니다. 브라우저 및 노션 게시 상태를 변경하지 않았습니다.')
            return
        if not jobs:
            print('임시저장 대상이 없습니다.')
            return
        if input('위 대상만 순서대로 임시저장하시겠습니까? 계속하려면 "시작" 입력: ').strip() != '시작':
            print('취소했습니다.')
            return
        saved = 0
        for index, (number, item) in enumerate(jobs, 1):
            title = plain_property(item, PROP_NAMES['title'])
            print(f'\n[{index}/{len(jobs)}] {number}번: {title}')
            try:
                html = notion.html_for_page(item['id'])
                # Blogger용 HTML 원고는 변경하지 않습니다.
                export = safe_export(number, title, html)
                print(f'HTML 백업: {export}')
                print(f'이 블로그 이미지 폴더: {IMAGE_DIR}')
                if re.search(r"""<img\b[^>]*\bsrc\s*=\s*[\"']\s*[\"']""", html, re.I):
                    print('주의: 이미지 src가 비어 있습니다. 저장본에서 직접 확인해야 합니다.')
                result = BlogPublisher(HERE).draft(title, html)
                if not result.get('attempted'):
                    print('편집기 저장 시도가 끝나지 않아 범위 작업을 중단합니다.')
                    break
                answer = input('실제 임시저장 목록에서 제목과 본문을 확인했나요? "확인" 입력 (아니면 중단): ').strip()
                if answer != '확인':
                    print('저장 여부 불확실: 노션 상태를 바꾸지 않고 전체 작업을 중단합니다.')
                    break
                notion.update_draft(item['id'], PROP_NAMES, PROP_NAMES['date'] in schema,
                                    PROP_NAMES['url'] in schema, result.get('url', ''))
                saved += 1
                print(f'{number}번 임시저장 확인 및 노션 기록 완료')
            except (NotionProblem, BlogProblem, RuntimeError, ValueError) as exc:
                print(f'{number}번에서 오류: {exc}', file=sys.stderr)
                print('중복 저장 위험을 막기 위해 이후 번호는 처리하지 않습니다.')
                break
        print(f'\n범위 실행 종료: 노션에 임시저장 완료로 기록한 글 {saved}편 / 대상 {len(jobs)}편')
        print('실제 공개 발행은 하지 않았습니다. 재실행하면 체크된 번호는 건너뜁니다.')
        return

    if args.command == 'list':
        def keyfunc(r):
            s = plain_property(r, PROP_NAMES['num'])
            try: return (0, int(s))
            except ValueError: return (1, s)
        for r in sorted(rows, key=keyfunc):
            number = plain_property(r, PROP_NAMES['num']) or '?'
            title = plain_property(r, PROP_NAMES['title'])
            status = ('게시완료' if is_checked(r, PROP_NAMES['published']) else
                      '임시저장' if is_checked(r, PROP_NAMES['draft']) else
                      '작성완료' if is_checked(r, PROP_NAMES['ready']) else '작성중')
            print(f'{number:>4} | {status:<7} | {title}')
        print(f'총 {len(rows)}개')
        return
    r = pick_number(rows, args.number)
    title = plain_property(r, PROP_NAMES['title'])
    if not title:
        raise RuntimeError('글 제목이 비어 있습니다.')
    if not is_checked(r, PROP_NAMES['ready']):
        raise RuntimeError('작성여부 체크가 꺼져 있습니다. 작성 완료 후 다시 실행해 주세요.')
    if is_checked(r, PROP_NAMES['published']):
        raise RuntimeError('이미 게시여부가 체크된 글입니다. 중복 저장을 막기 위해 중단합니다.')
    if args.command == 'draft' and is_checked(r, PROP_NAMES['draft']) and not args.force:
        raise RuntimeError('이미 임시저장여부가 체크되어 있습니다. 정말 재시도하려면 --force 옵션을 사용하세요.')
    html = notion.html_for_page(r['id'])
    export = safe_export(args.number, title, html)
    print(f'제목: {title}\nHTML 길이: {len(html):,}자\n복사본: {export}')
    print(f'이 블로그 이미지 폴더: {IMAGE_DIR}')
    if re.search(r"""<img\b[^>]*\bsrc\s*=\s*["']\s*["']""", html, re.I):
        print('주의: HTML에 src가 빈 이미지가 있습니다. 실제 이미지는 별도로 넣어야 합니다.')
    if args.command == 'preview':
        print('미리보기 전용: 티스토리/블로그스팟에 아무것도 작성하지 않았습니다.')
        return
    answer = input('이 번호만 임시저장 작업을 진행할까요? [예/y]: ').strip().lower()
    if answer not in ('예', 'y', 'yes'):
        print('취소했습니다.')
        return
    # 이 단계에서 웹 편집기 입력과 저장을 시도합니다. 사람 확인 전에는 노션 수정 금지.
    result = BlogPublisher(HERE).draft(title, html)
    if not result.get('attempted'):
        print('자동 입력/임시저장 시도가 완료되지 않아 노션을 수정하지 않았습니다.')
        return
    print('\n중요: 브라우저의 임시저장 목록에서 제목과 본문이 실제로 저장됐는지 확인하세요.')
    answer = input('실제 임시저장된 것을 확인했나요? 확인했다면 "확인" 입력: ').strip()
    if answer != '확인':
        print('확인 전이므로 노션에 성공 표시하지 않았습니다. 나중에 다시 확인하세요.')
        return
    notion.update_draft(r['id'], PROP_NAMES, PROP_NAMES['date'] in schema,
                        PROP_NAMES['url'] in schema, result.get('url', ''))
    print('노션 임시저장여부 업데이트 완료. 게시여부와 발행일은 변경하지 않았습니다.')


if __name__ == '__main__':
    try:
        main()
    except (NotionProblem, BlogProblem, RuntimeError, ValueError) as exc:
        print(f'\n오류: {exc}', file=sys.stderr)
        sys.exit(1)
