# -*- coding: utf-8 -*-
"""여러 티스토리 블로그에서 사용하는 공통 명령 실행 코드."""
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

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from .notion_io import NotionClient, NotionProblem, plain_property, is_checked
from .publisher import BlogPublisher, BlogProblem
from .image_meta import fill_existing_img_alts, resolve_local_images

@dataclass(frozen=True)
class BlogConfig:
    label: str
    url: str
    directory: Path
    image_dir: Path
    source_env: str
    ai_name_env: str
    category_required: bool

BLOG: BlogConfig
PROP_NAMES: dict[str, str]


def configure(blog: BlogConfig):
    global BLOG, PROP_NAMES
    BLOG = blog
    load_dotenv(blog.directory.parent.parent / '.env')
    PROP_NAMES = {
        'num': os.getenv('PROP_NUMBER', '번호'),
        'title': os.getenv('PROP_TITLE', '글 제목'),
        'ready': os.getenv('PROP_READY', '작성여부'),
        'published': os.getenv('PROP_PUBLISHED', '게시여부'),
        'draft': os.getenv('PROP_DRAFT', '임시저장여부'),
        'date': os.getenv('PROP_DRAFT_DATE', '임시저장일'),
        'url': os.getenv('PROP_DRAFT_URL', '임시저장URL'),
        'category': os.getenv('PROP_CATEGORY', '카테고리'),
    }


def config():
    token = os.getenv('NOTION_API_KEY', '').strip()
    source = os.getenv(BLOG.source_env, '').strip()
    if not token or not source:
        raise RuntimeError(f'최상위 .env에 NOTION_API_KEY와 {BLOG.source_env}를 입력해 주세요.')
    return NotionClient(token, source)


def pick_number(rows: list[dict], number: int) -> dict:
    found = [r for r in rows if plain_property(r, PROP_NAMES['num']) == str(number)]
    if len(found) != 1:
        raise RuntimeError(f'번호 {number}번 검색 결과가 {len(found)}개입니다. 중복/누락된 번호를 확인해 주세요.')
    return found[0]


def validate_schema(schema: dict):
    keys = ['num', 'title', 'ready', 'published', 'draft']
    if BLOG.category_required:
        keys.append('category')
    essentials = [PROP_NAMES[k] for k in keys]
    missing = [x for x in essentials if x not in schema]
    if missing:
        raise RuntimeError('노션 데이터소스에 필수 속성이 없습니다: ' + ', '.join(missing)
                           + '\nREADME의 노션 속성 표를 보고 추가한 뒤 다시 실행해 주세요.')
    expected_types = [('num','number'), ('title','title'), ('ready','checkbox'),
                      ('published','checkbox'), ('draft','checkbox')]
    if BLOG.category_required:
        expected_types.append(('category', 'select'))
    for key, expected in expected_types:
        name = PROP_NAMES[key]
        if schema[name]['type'] != expected:
            raise RuntimeError(f'노션 속성 {name}은(는) {expected} 유형이어야 합니다.')
    if PROP_NAMES['date'] in schema and schema[PROP_NAMES['date']]['type'] != 'date':
        raise RuntimeError(f'노션 속성 {PROP_NAMES["date"]}은(는) 날짜 유형이어야 합니다.')
    if PROP_NAMES['url'] in schema and schema[PROP_NAMES['url']]['type'] != 'url':
        raise RuntimeError(f'노션 속성 {PROP_NAMES["url"]}은(는) URL 유형이어야 합니다.')


def safe_export(number: int, title: str, html: str) -> Path:
    exports = BLOG.directory / 'exports'
    exports.mkdir(exist_ok=True)
    name = re.sub(r'[^a-zA-Z0-9가-힣_-]+', '_', title).strip('_')[:40]
    dst = exports / f'{number:03d}_{name}.html'
    dst.write_text(html, encoding='utf-8')
    return dst


def main(blog: BlogConfig):
    configure(blog)
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
    print(f'\n[{blog.label}] {blog.url}')
    if args.command == 'login':
        BlogPublisher(blog.directory, blog.url).login()
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
            elif blog.category_required and not plain_property(item, PROP_NAMES['category']).strip():
                skips.append((number, '카테고리가 비어 있음'))
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
        saved = 0
        for index, (number, item) in enumerate(jobs, 1):
            title = plain_property(item, PROP_NAMES['title'])
            category = plain_property(item, PROP_NAMES['category']).strip() if blog.category_required else None
            print(f'\n[{index}/{len(jobs)}] {number}번: {title}')
            try:
                html = notion.html_for_page(item['id'])
                ai_property = os.getenv(blog.ai_name_env, 'AI 이름').strip()
                ai_name = plain_property(item, ai_property).strip() or title
                html, image_plan = fill_existing_img_alts(html, ai_name)
                local_images = resolve_local_images(html, number, ai_name, blog.image_dir)
                # 사진은 글쓰기 화면에서 업로드하고, 이 파일에는 매칭 계획을 남깁니다.
                plan_file = safe_export(number, title, html).with_suffix('.images.json')
                plan_file.write_text(json.dumps({
                    'number': number, 'title': title, 'ai_name': ai_name, 'image_caption': ai_name,
                    'cover_image_index': 1, 'images': image_plan,
                    'image_folder': blog.image_dir.relative_to(blog.directory.parent.parent).as_posix(),
                    'local_files': {f'{index:02d}': path.name for index, path in local_images.items()},
                    'note': 'IMAGE 표시의 로컬 파일은 글쓰기 화면에서 업로드하고 IMAGE:01을 대표 이미지로 지정합니다.'
                }, ensure_ascii=False, indent=2), encoding='utf-8')
                export = safe_export(number, title, html)
                print(f'HTML 백업: {export}')
                print(f'이 블로그 이미지 폴더: {blog.image_dir}')
                if local_images:
                    print(f'로컬 이미지 {len(local_images)}개를 IMAGE 표시 위치에 업로드합니다.')
                result = BlogPublisher(blog.directory, blog.url).draft(title, html, category, local_images, ai_name)
                if not result.get('saved'):
                    print('임시저장을 확인하지 못해 범위 작업을 중단합니다.')
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
    category = plain_property(r, PROP_NAMES['category']).strip() if blog.category_required else None
    if not title:
        raise RuntimeError('글 제목이 비어 있습니다.')
    if blog.category_required and not category:
        raise RuntimeError('노션 카테고리가 비어 있습니다.')
    if not is_checked(r, PROP_NAMES['ready']):
        raise RuntimeError('작성여부 체크가 꺼져 있습니다. 작성 완료 후 다시 실행해 주세요.')
    if is_checked(r, PROP_NAMES['published']):
        raise RuntimeError('이미 게시여부가 체크된 글입니다. 중복 저장을 막기 위해 중단합니다.')
    if args.command == 'draft' and is_checked(r, PROP_NAMES['draft']) and not args.force:
        raise RuntimeError('이미 임시저장여부가 체크되어 있습니다. 정말 재시도하려면 --force 옵션을 사용하세요.')
    html = notion.html_for_page(r['id'])
    # 노션 목록의 AI 이름 속성을 우선 활용합니다. 속성이 없다면 글 제목을 사용합니다.
    ai_property = os.getenv(blog.ai_name_env, 'AI 이름').strip()
    ai_name = plain_property(r, ai_property).strip() or title
    html, image_plan = fill_existing_img_alts(html, ai_name)
    local_images = resolve_local_images(html, args.number, ai_name, blog.image_dir)
    export = safe_export(args.number, title, html)
    plan_file = export.with_suffix('.images.json')
    plan_file.write_text(json.dumps({
        'number': args.number, 'title': title, 'ai_name': ai_name, 'image_caption': ai_name,
        'cover_image_index': 1, 'images': image_plan,
        'image_folder': blog.image_dir.relative_to(blog.directory.parent.parent).as_posix(),
        'local_files': {f'{index:02d}': path.name for index, path in local_images.items()},
        'note': 'IMAGE 표시의 로컬 파일은 임시저장 시 업로드하고 IMAGE:01을 대표 이미지로 지정합니다. 노션 첨부 다운로드는 별도입니다.'
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'ALT 기준: 노션 {ai_property} = {ai_name}')
    print(f'이미지 캡션: {ai_name}')
    print(f'이미지 작업 계획: {plan_file}')
    print(f'이 블로그 이미지 폴더: {blog.image_dir}')
    for index, path in local_images.items():
        print(f'IMAGE:{index:02d} → {path.name}')
    if image_plan:
        print(f'이미지 {len(image_plan)}개 탐지 · 01번 대표 이미지로 지정 예정')
    print(f'제목: {title}\nHTML 길이: {len(html):,}자\n복사본: {export}')
    if local_images:
        print('IMAGE 표시 위치의 빈 이미지 주소는 임시저장 시 로컬 파일로 교체합니다.')
    if args.command == 'preview':
        print('미리보기 전용: 티스토리/블로그스팟에 아무것도 작성하지 않았습니다.')
        return
    # 티스토리에서 임시저장을 다시 불러와 확인한 뒤에만 노션 상태를 갱신합니다.
    result = BlogPublisher(blog.directory, blog.url).draft(title, html, category, local_images, ai_name)
    if not result.get('saved'):
        print('임시저장을 확인하지 못해 노션을 수정하지 않았습니다.')
        return
    notion.update_draft(r['id'], PROP_NAMES, PROP_NAMES['date'] in schema,
                        PROP_NAMES['url'] in schema, result.get('url', ''))
    print('노션 임시저장여부 업데이트 완료. 게시여부와 발행일은 변경하지 않았습니다.')


def run_blog(blog: BlogConfig):
    try:
        main(blog)
    except (NotionProblem, BlogProblem, RuntimeError, ValueError) as exc:
        print(f'\n오류: {exc}', file=sys.stderr)
        sys.exit(1)
