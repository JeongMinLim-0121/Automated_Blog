# -*- coding: utf-8 -*-
"""이 폴더 전용 노션 접근 모듈. 다른 블로그 폴더와 독립적입니다."""
from __future__ import annotations
import re
import requests

API = 'https://api.notion.com/v1'
VERSION = '2025-09-03'


class NotionProblem(RuntimeError):
    pass


class NotionClient:
    def __init__(self, token: str, data_source_id: str):
        self.data_source_id = data_source_id.strip().removeprefix('collection://')
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {token.strip()}',
            'Notion-Version': VERSION,
            'Content-Type': 'application/json',
        })

    def request(self, method: str, path: str, **kwargs) -> dict:
        try:
            r = self.session.request(method, API + path, timeout=30, **kwargs)
        except requests.RequestException as exc:
            raise NotionProblem(f'노션 접속 실패: {exc}') from exc
        if not r.ok:
            try:
                err = r.json().get('message', r.text)
            except ValueError:
                err = r.text[:400]
            raise NotionProblem(f'노션 API 오류 HTTP {r.status_code}: {err}')
        return r.json()

    def schema(self) -> dict:
        return self.request('GET', f'/data_sources/{self.data_source_id}').get('properties', {})

    def rows(self) -> list[dict]:
        result, cursor = [], None
        while True:
            payload = {'page_size': 100}
            if cursor:
                payload['start_cursor'] = cursor
            data = self.request('POST', f'/data_sources/{self.data_source_id}/query', json=payload)
            result.extend(data.get('results', []))
            cursor = data.get('next_cursor')
            if not data.get('has_more') or not cursor:
                break
        return result

    def children(self, block_id: str) -> list[dict]:
        result, cursor = [], None
        while True:
            params = {'page_size': 100}
            if cursor:
                params['start_cursor'] = cursor
            data = self.request('GET', f'/blocks/{block_id}/children', params=params)
            result.extend(data.get('results', []))
            cursor = data.get('next_cursor')
            if not data.get('has_more') or not cursor:
                break
        return result

    def html_for_page(self, page_id: str) -> str:
        """하위 블록까지 검색하고 html/yaml 코드 블록에서 HTML을 추출합니다."""
        candidates: list[tuple[int, str]] = []
        pending = [(page_id, 0)]
        while pending:
            block_id, depth = pending.pop(0)
            for block in self.children(block_id):
                typ = block.get('type')
                if typ == 'code':
                    payload = block.get('code', {})
                    raw = ''.join(x.get('plain_text', '') for x in payload.get('rich_text', []))
                    # 앞뒤의 펜스가 복사되어 있을 때만 제거
                    raw = re.sub(r'^\s*```(?:html|yaml)?\s*\n', '', raw, flags=re.I)
                    raw = re.sub(r'\n```\s*$', '', raw)
                    if re.search(r'<(?:article|div|h[1-6]|p|section|ul|table|img)\b', raw, re.I):
                        language = payload.get('language', '').lower()
                        score = len(raw) + (1000000 if language == 'html' else 0)
                        candidates.append((score, raw))
                if block.get('has_children') and depth < 4:
                    pending.append((block['id'], depth + 1))
        if not candidates:
            raise NotionProblem('이 페이지에서 HTML이 포함된 코드 블록을 찾지 못했어요. 노션에 HTML 코드 블록을 넣어주세요.')
        return max(candidates, key=lambda item: item[0])[1].strip()

    def update_draft(self, page_id: str, names: dict, has_date: bool, has_url: bool, draft_url: str = ''):
        from datetime import datetime, timezone, timedelta
        props = {names['draft']: {'checkbox': True}}
        if has_date:
            kst = timezone(timedelta(hours=9))
            props[names['date']] = {'date': {'start': datetime.now(kst).isoformat(timespec='seconds')}}
        if has_url and draft_url and draft_url.startswith('https://'):
            props[names['url']] = {'url': draft_url}
        self.request('PATCH', f'/pages/{page_id}', json={'properties': props})


def plain_property(page: dict, name: str) -> str:
    prop = page.get('properties', {}).get(name, {})
    typ = prop.get('type')
    if typ in ('title', 'rich_text'):
        return ''.join(item.get('plain_text', '') for item in prop.get(typ, []))
    if typ == 'select':
        return (prop.get('select') or {}).get('name') or ''
    if typ == 'number':
        value = prop.get('number')
        return '' if value is None else str(int(value)) if float(value).is_integer() else str(value)
    if typ == 'checkbox':
        return 'true' if prop.get('checkbox', False) else 'false'
    return ''


def is_checked(page: dict, name: str) -> bool:
    return bool(page.get('properties', {}).get(name, {}).get('checkbox', False))
