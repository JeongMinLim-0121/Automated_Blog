# -*- coding: utf-8 -*-
"""Blogger 전용 브라우저 자동화. 공개 발행은 하지 않습니다."""
from __future__ import annotations
import re
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

class BlogProblem(RuntimeError):
    pass

class BlogPublisher:
    def __init__(self, directory: Path):
        self.directory = directory
        self.profile = directory / 'profiles' / 'blogger_browser'
        self.blog_id = os.getenv('BLOGSPOT_BLOG1_BLOGGER_BLOG_ID', '').strip()

    def _open(self, playwright):
        self.profile.parent.mkdir(exist_ok=True)
        return playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile), headless=False, locale='ko-KR',
            viewport={'width': 1400, 'height': 960}
        )

    def _go(self, page):
        if not self.blog_id:
            raise BlogProblem('Blogger 자동화에는 BLOGSPOT_BLOG1_BLOGGER_BLOG_ID가 필요합니다. 최상위 .env에 입력해 주세요.')
        page.goto(f'https://www.blogger.com/blog/posts/{self.blog_id}', wait_until='domcontentloaded', timeout=60000)

    def login(self):
        with sync_playwright() as p:
            context = self._open(p)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto('https://www.blogger.com/', wait_until='domcontentloaded', timeout=60000)
                print('Google 로그인 후 화면에서 해당 블로그를 선택하세요.')
                print('블로그 관리 URL의 숫자 ID를 최상위 .env의 BLOGSPOT_BLOG1_BLOGGER_BLOG_ID에 입력하세요.')
                input('로그인 완료 후 Enter를 누르세요...')
            finally:
                context.close()

    def _first_visible(self, page, selectors):
        for selector in selectors:
            try:
                loc = page.locator(selector).first
                if loc.count() and loc.is_visible(timeout=1000):
                    return loc
            except Exception:
                pass
        return None

    def _title(self, page, title: str) -> bool:
        loc = self._first_visible(page, [
            'input[aria-label="제목"]', 'input[aria-label="Title"]',
            'input[placeholder*="제목"]', 'input[placeholder*="Title"]',
            'textarea[aria-label="Title"]', 'textarea[aria-label="제목"]'
        ])
        if loc is None:
            return False
        loc.fill(title)
        return loc.input_value() == title

    def _html(self, page, html: str) -> bool:
        # Blogger의 'HTML 보기' 선택 버튼은 언어/버전별로 바뀔 수 있습니다.
        for selector in ['button[aria-label*="보기"]', 'button[aria-label*="View"]', 'button[title*="View"]']:
            try:
                btn = page.locator(selector).first
                if btn.count() and btn.is_visible(timeout=1000):
                    btn.click()
                    break
            except Exception:
                pass
        for selector in ['[role="menuitem"]:has-text("HTML")', 'button:has-text("HTML 보기")', 'button:has-text("HTML view")', 'li:has-text("HTML")']:
            try:
                btn = page.locator(selector).first
                if btn.count() and btn.is_visible(timeout=1000):
                    btn.click()
                    break
            except Exception:
                pass
        loc = self._first_visible(page, [
            'textarea[aria-label*="HTML"]', 'textarea[aria-label*="본문"]',
            '.CodeMirror', 'textarea.editor', 'textarea[spellcheck="false"]'
        ])
        if loc is not None:
            try:
                if loc.evaluate('(el) => !!el.CodeMirror'):
                    return bool(loc.evaluate('(el, html) => {el.CodeMirror.setValue(html); return el.CodeMirror.getValue() === html}', html))
                loc.fill(html)
                return loc.input_value() == html
            except Exception:
                pass
        return False

    def _save(self, page):
        for selector in ['button[aria-label="저장"]', 'button[aria-label="Save"]', 'button:has-text("저장")', 'button:has-text("Save")']:
            try:
                btn = page.locator(selector).first
                if btn.count() and btn.is_visible(timeout=1000):
                    label = (btn.inner_text() or '') + (btn.get_attribute('aria-label') or '')
                    if '발행' in label or '게시' in label or 'Publish' in label:
                        continue
                    btn.click()
                    page.wait_for_timeout(1500)
                    return True
            except Exception:
                continue
        return False

    def draft(self, title: str, html: str) -> dict:
        with sync_playwright() as p:
            context = self._open(p)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                self._go(page)
                input('화면에서 jmlim8038 블로그인지 확인하고 Enter를 누르세요...')
                # Blogger 첫 실행/사이트 UI 변경 시 사용자가 글쓰기 진입을 도울 수 있습니다.
                for selector in ['button:has-text("새 글")', 'a:has-text("새 글")', 'button:has-text("New Post")', 'a:has-text("New Post")']:
                    try:
                        btn=page.locator(selector).first
                        if btn.count() and btn.is_visible(timeout=1000):
                            btn.click()
                            break
                    except Exception:
                        pass
                input('글쓰기 편집기가 열렸으면 Enter를 누르세요...')
                t = self._title(page, title)
                h = self._html(page, html)
                if not t:
                    print('제목 자동 입력에 실패했습니다. 수동으로 입력하세요.')
                if not h:
                    print('HTML 자동 입력에 실패했습니다. exports 파일을 HTML 보기 모드에 붙여넣어 주세요.')
                saved = self._save(page) if t and h else False
                if not saved:
                    print('저장 버튼을 확인하지 못했습니다. 직접 "저장"만 누르세요. "게시/발행"은 누르지 마세요.')
                print('Blogger는 일부 화면에서 자동으로 초안을 저장합니다. 실제 임시보관함을 확인해 주세요.')
                input('저장 확인을 위한 작업이 끝나면 Enter를 누르세요...')
                return {'attempted': True, 'url': page.url}
            finally:
                context.close()
