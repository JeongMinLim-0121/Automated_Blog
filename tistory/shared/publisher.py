# -*- coding: utf-8 -*-
"""Tistory 전용 브라우저 자동화. 공개 발행 버튼을 누르지 않습니다."""
from __future__ import annotations
import html as html_lib
import json
import re
import time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from .image_meta import suggest_alt

IMAGE_TOKEN = re.compile(r'\[##_Image\|.*?_##\]', re.S)
IMAGE_SLOT = re.compile(r'<!--\s*IMAGE\s*:\s*(\d+)\s*-->(\s*<img\b[^>]*>)?', re.I | re.S)
EMPTY_SRC = re.compile(r'\bsrc\s*=\s*(["\'])\s*\1', re.I)

class BlogProblem(RuntimeError):
    pass

class BlogPublisher:
    TITLE_FIELDS = '#post-title-inp, input[placeholder*="제목"], textarea[placeholder*="제목"], input[aria-label*="제목"]'

    def __init__(self, directory: Path, site: str):
        self.directory = directory
        self.profile = directory / 'profiles' / 'tistory_browser'
        self.auth_state = directory / 'profiles' / 'tistory_auth.json'
        self.site = site.rstrip('/')

    def _open(self, playwright):
        self.profile.parent.mkdir(exist_ok=True)
        # timezone_id를 사용하지 않음: 일부 Windows의 ZoneInfoNotFoundError 방지
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(self.profile), headless=False, locale='ko-KR',
            viewport={'width': 1400, 'height': 960}, accept_downloads=True
        )
        # Chromium 종료 후 세션 쿠키가 사라진 경우 저장해 둔 인증 상태를 복원합니다.
        if self.auth_state.exists():
            try:
                state = json.loads(self.auth_state.read_text(encoding='utf-8'))
                existing = {(c['domain'], c['path'], c['name']) for c in context.cookies()}
                cookies = [c for c in state.get('cookies', [])
                           if (c['domain'], c['path'], c['name']) not in existing
                           and (c.get('expires', -1) <= 0 or c['expires'] > time.time())]
                if cookies:
                    context.add_cookies(cookies)
            except (OSError, ValueError, KeyError):
                pass
        return context

    def _save_auth(self, context):
        self.auth_state.parent.mkdir(exist_ok=True)
        context.storage_state(path=str(self.auth_state))

    def login(self):
        with sync_playwright() as p:
            context = self._open(p)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(self.site + '/manage', wait_until='domcontentloaded', timeout=60000)
                try:
                    page.wait_for_url(re.compile(re.escape(self.site) + r'/manage(?:/|$|\?)'), timeout=15000)
                    self._save_auth(context)
                    print('기존 티스토리 로그인 상태를 확인했습니다.')
                    return
                except PWTimeout:
                    print('로그인 세션이 없습니다. 브라우저에서 카카오 로그인을 완료하세요.')
                    try:
                        page.wait_for_url(re.compile(re.escape(self.site) + r'/manage(?:/|$|\?)'),
                                          wait_until='domcontentloaded', timeout=300000)
                    except PWTimeout as exc:
                        raise BlogProblem('티스토리 관리자 화면에 들어가지 못했습니다. 로그인을 확인해 주세요.') from exc
                    self._save_auth(context)
                    print('브라우저 프로필에 로그인 정보가 저장됐습니다.')
            finally:
                context.close()

    @staticmethod
    def _first_visible(page, selectors):
        for selector in selectors:
            loc = page.locator(selector).first
            try:
                if loc.count() and loc.is_visible(timeout=1500):
                    return loc
            except Exception:
                pass
        return None

    def _title(self, page, title: str) -> bool:
        loc = self._first_visible(page, [
            '#post-title-inp', 'input[placeholder*="제목"]',
            'textarea[placeholder*="제목"]', 'input[aria-label*="제목"]'
        ])
        if loc is None: return False
        loc.fill(title)
        return True

    def _category(self, page, category: str) -> bool:
        button = page.locator('#category-btn').first
        button.wait_for(state='visible', timeout=15000)
        if button.locator('.mce-txt').inner_text().strip() == category:
            return True
        button.click()
        option = page.locator('#category-list').get_by_role('option', name=category, exact=True)
        if option.count() != 1:
            raise BlogProblem(f'티스토리에서 카테고리 "{category}"를 찾지 못했습니다.')
        option.click()
        try:
            page.wait_for_function(
                '(name) => document.querySelector("#category-btn .mce-txt")?.textContent?.trim() === name',
                arg=category, timeout=5000,
            )
        except PWTimeout as exc:
            raise BlogProblem(f'티스토리 카테고리 "{category}" 선택을 확인하지 못했습니다.') from exc
        return True

    def _resume_draft(self, page, title: str):
        count_link = page.locator('.btn-draft a.count').first
        count_link.wait_for(state='visible', timeout=10000)
        count_label = count_link.get_attribute('aria-label') or ''
        match = re.search(r'(\d+)개', count_label)
        if not match:
            raise BlogProblem('티스토리 임시저장 글 개수를 확인하지 못했습니다.')
        if int(match.group(1)) == 0:
            # 처음 0개로 보였다가 저장 목록이 늦게 로드되는 경우가 있습니다.
            page.wait_for_timeout(3000)
            count_label = count_link.get_attribute('aria-label') or ''
            match = re.search(r'(\d+)개', count_label)
            if not match:
                raise BlogProblem('티스토리 임시저장 글 개수를 다시 확인하지 못했습니다.')
            if int(match.group(1)) == 0:
                return
        count_link.click()
        page.locator('.link_info').first.wait_for(state='visible', timeout=10000)
        matches = [link for link in page.locator('.link_info').all()
                   if link.inner_text().strip() == title]
        if len(matches) > 1:
            raise BlogProblem(f'티스토리에 같은 제목의 임시저장 글이 {len(matches)}건 있습니다. 중복 저장을 막기 위해 중단합니다.')
        if not matches:
            page.keyboard.press('Escape')
            return
        matches[0].click()
        page.wait_for_function(
            '(expected) => document.querySelector("#post-title-inp")?.value === expected',
            arg=title, timeout=10000,
        )
        print('같은 제목의 기존 임시저장 글을 이어서 편집합니다.')

    def _html_mode(self, page) -> bool:
        html_editor = page.locator('.CodeMirror.cm-s-tistory-html').first
        if html_editor.is_visible():
            return True
        try:
            mode_button = page.locator('#editor-mode-layer-btn').first
            mode_button.wait_for(state='visible', timeout=15000)
        except PWTimeout:
            return False

        def confirm_mode_change(dialog):
            # 자동 복구 원고 등의 다른 확인 창은 수락하지 않습니다.
            if dialog.type == 'confirm' and '작성 모드' in dialog.message:
                dialog.accept()
            else:
                dialog.dismiss()

        page.on('dialog', confirm_mode_change)
        try:
            mode_button.click()
            html_option = page.locator('#editor-mode-html').first
            html_option.wait_for(state='visible', timeout=5000)
            html_option.click()
            html_editor.wait_for(state='visible', timeout=10000)
            return True
        except PWTimeout:
            return False
        finally:
            page.remove_listener('dialog', confirm_mode_change)

    def _set_html(self, page, html: str) -> bool:
        try:
            cm = page.locator('.CodeMirror.cm-s-tistory-html:visible').first
            if cm.count() and cm.is_visible(timeout=1500):
                # ReactCodemirror는 setValue()의 변경을 저장 상태에 반영하지 않을 수 있습니다.
                # 사용자 입력과 같은 키보드 이벤트로 본문을 넣습니다.
                cm.click()
                page.keyboard.press('ControlOrMeta+A')
                page.keyboard.insert_text(html)
                ok = cm.evaluate('(el, html) => { if (!el.CodeMirror) return false; el.CodeMirror.save(); return el.CodeMirror.getValue() === html; }', html)
                if ok: return True
        except Exception:
            pass
        loc = self._first_visible(page, ['textarea#editor-tistory', 'textarea[aria-label*="HTML"]', 'textarea.CodeMirror', 'textarea#html-editor'])
        if loc is not None:
            loc.fill(html)
            return loc.input_value() == html
        return False

    @staticmethod
    def _image_token_with_alt(token: str, alt: str) -> str:
        prefix, separator, metadata_text = token.rpartition('|')
        if not separator or not metadata_text.endswith('_##]'):
            raise BlogProblem('업로드된 이미지의 ALT 정보를 읽지 못했습니다.')
        try:
            metadata = json.loads(metadata_text[:-4])
            if not isinstance(metadata, dict):
                raise ValueError('이미지 정보가 객체가 아닙니다.')
        except (ValueError, TypeError) as exc:
            raise BlogProblem('업로드된 이미지의 ALT 정보를 읽지 못했습니다.') from exc
        metadata['alt'] = alt
        return prefix + '|' + json.dumps(metadata, ensure_ascii=False, separators=(',', ':')) + '_##]'

    @classmethod
    def _replace_image_slots(cls, html: str, uploaded: dict[int, str], ai_name: str) -> str:
        def replace(match):
            index = int(match.group(1))
            if index not in uploaded:
                raise BlogProblem(f'IMAGE:{index:02d}에 업로드된 이미지가 없습니다. 임시저장을 중단합니다.')
            adjacent_img = match.group(2)
            if adjacent_img and not EMPTY_SRC.search(adjacent_img):
                raise BlogProblem(f'IMAGE:{index:02d} 뒤에 이미 주소가 있는 이미지가 있어 중단합니다.')
            alt = suggest_alt(ai_name, index)
            if adjacent_img:
                attr = re.search(r'\s+alt\s*=\s*(["\'])(.*?)\1', adjacent_img, re.I | re.S)
                if attr and attr.group(2).strip():
                    alt = html_lib.unescape(attr.group(2))
            return f'<p>{cls._image_token_with_alt(uploaded[index], alt)}</p>'

        result = IMAGE_SLOT.sub(replace, html)
        if IMAGE_SLOT.search(result) or any(EMPTY_SRC.search(tag) for tag in re.findall(r'<img\b[^>]*>', result, re.I | re.S)):
            raise BlogProblem('이미지 표시 또는 빈 이미지 주소가 남아 있어 임시저장을 중단합니다.')
        return result

    def _upload_image(self, page, path: Path) -> str:
        page.wait_for_function('() => !!window.tinymce?.activeEditor?.initialized', timeout=15000)
        before = IMAGE_TOKEN.findall(page.evaluate('() => window.tinymce.activeEditor.getContent()'))
        page.locator('#mceu_0').click()
        try:
            with page.expect_file_chooser(timeout=10000) as chooser:
                page.locator('#attach-image').click()
            chooser.value.set_files(str(path))
        except PWTimeout as exc:
            raise BlogProblem(f'사진 첨부 창을 열지 못했습니다: {path.name}') from exc
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            page.wait_for_timeout(400)
            try:
                tokens = IMAGE_TOKEN.findall(page.evaluate('() => window.tinymce.activeEditor.getContent()'))
            except Exception:
                continue
            if len(tokens) <= len(before):
                continue
            for token in reversed(tokens):
                try:
                    filename = json.loads(token.rsplit('|', 1)[-1][:-4]).get('filename')
                except (ValueError, AttributeError):
                    continue
                if filename == path.name:
                    return token
        raise BlogProblem(f'사진 업로드 결과를 확인하지 못했습니다: {path.name}')

    @staticmethod
    def _set_image_caption(page, path: Path, caption: str) -> str:
        fields = [field for frame in page.frames if frame != page.main_frame
                  for image in frame.locator('img[data-filename]').all()
                  if image.get_attribute('data-filename') == path.name
                  for field in [image.locator('xpath=..').locator('figcaption')]
                  if field.count() == 1 and not field.inner_text().strip()]
        if len(fields) != 1:
            raise BlogProblem(f'캡션을 입력할 사진을 편집기에서 찾지 못했습니다: {path.name}')
        caption_field = fields[0]
        caption_field.click()
        page.keyboard.insert_text(caption)
        if caption_field.inner_text().strip() != caption:
            raise BlogProblem(f'사진 캡션 입력을 확인하지 못했습니다: {path.name}')
        for token in IMAGE_TOKEN.findall(page.evaluate('() => window.tinymce.activeEditor.getContent()')):
            try:
                metadata = json.loads(token.rsplit('|', 1)[-1][:-4])
            except (ValueError, AttributeError):
                continue
            if metadata.get('filename') == path.name and metadata.get('caption') == caption:
                return token
        raise BlogProblem(f'사진 캡션이 HTML에 반영되지 않았습니다: {path.name}')

    @staticmethod
    def _representative_button(page, path: Path):
        matches = [(frame, image) for frame in page.frames if frame != page.main_frame
                   for image in frame.locator('img[data-filename]').all()
                   if image.get_attribute('data-filename') == path.name]
        if len(matches) != 1:
            raise BlogProblem(f'대표 이미지로 지정할 사진을 편집기에서 찾지 못했습니다: {path.name}')
        image_frame, image = matches[0]
        image.click()

        # 이미지 도구막대는 에디터 iframe 안이나 바깥에 나타날 수 있습니다.
        # 선택한 이미지가 들어 있는 프레임을 먼저 확인합니다.
        button = None
        for scope in (image_frame, page):
            candidate = scope.locator('.mce-represent-image-btn:visible').first
            try:
                candidate.wait_for(state='visible', timeout=3000)
                button = candidate
                break
            except PWTimeout:
                continue
        if button is None:
            raise BlogProblem(f'대표 이미지 선택 버튼을 찾지 못했습니다: {path.name}')
        return button

    @staticmethod
    def _representative_selected(button) -> bool:
        return button.evaluate('''element =>
            element.classList.contains('active') ||
            element.getAttribute('aria-pressed') === 'true' ||
            element.getAttribute('aria-checked') === 'true' ||
            !!element.querySelector('input:checked')
        ''')

    @classmethod
    def _set_representative_image(cls, page, path: Path):
        button = cls._representative_button(page, path)
        if not cls._representative_selected(button):
            button.click(timeout=5000)
        for _ in range(20):
            if cls._representative_selected(button):
                break
            page.wait_for_timeout(250)
        else:
            raise BlogProblem(f'대표 이미지의 "대표" 표시가 켜지지 않았습니다: {path.name}')
        print(f'대표 이미지 지정 완료: {path.name}')

    def _confirm_saved_representative(self, page, title: str, path: Path,
                                      expected_alt: dict[str, str]):
        for attempt in range(2):
            page.goto(self.site + '/manage/newpost', wait_until='domcontentloaded', timeout=60000)
            page.locator(self.TITLE_FIELDS).first.wait_for(state='visible', timeout=15000)
            try:
                with page.expect_response(
                    lambda response: response.request.method == 'GET'
                    and re.search(r'/manage/drafts/\d+(?:\?|$)', response.url),
                    timeout=15000,
                ) as draft_response:
                    self._resume_draft(page, title)
            except PWTimeout as exc:
                raise BlogProblem('저장된 임시글을 다시 불러오지 못해 대표 이미지를 확인할 수 없습니다.') from exc
            response = draft_response.value
            if not response.ok:
                raise BlogProblem(f'임시글 다시 불러오기 실패: HTTP {response.status}')
            try:
                draft = response.json()['draft']
                thumbnail = draft.get('thumbnail', '').split('?', 1)[0]
                tokens = IMAGE_TOKEN.findall(draft['content'])
            except (ValueError, KeyError, TypeError, AttributeError) as exc:
                raise BlogProblem('저장된 임시글의 대표 이미지 정보를 읽지 못했습니다.') from exc
            if draft.get('title') != title:
                raise BlogProblem('다시 불러온 임시글의 제목이 달라 대표 이미지를 확인할 수 없습니다.')
            saved_images = []
            for token in tokens:
                try:
                    saved_images.append(json.loads(token.rsplit('|', 1)[-1][:-4]))
                except (ValueError, AttributeError):
                    continue
            for filename, alt in expected_alt.items():
                if not any(item.get('filename') == filename and item.get('alt') == alt
                           for item in saved_images):
                    raise BlogProblem(f'저장된 임시글에서 이미지 ALT를 확인하지 못했습니다: {filename}')
            for token in tokens:
                try:
                    metadata = json.loads(token.rsplit('|', 1)[-1][:-4])
                except (ValueError, AttributeError):
                    continue
                if (metadata.get('filename') == path.name
                        and thumbnail and thumbnail in token):
                    print(f'저장된 대표 이미지 확인: {path.name}')
                    return
            if attempt == 1:
                break
            print('저장된 대표 이미지가 01번 사진과 달라 다시 지정하고 저장합니다.')
            self._set_representative_image(page, path)
            if not self._save(page):
                raise BlogProblem('대표 이미지를 다시 선택했지만 임시저장 버튼을 찾지 못했습니다.')
        raise BlogProblem(f'저장된 대표 이미지가 01번 사진과 일치하지 않습니다: {path.name}')

    def _confirm_saved_draft(self, page, title: str):
        page.goto(self.site + '/manage/newpost', wait_until='domcontentloaded', timeout=60000)
        page.locator(self.TITLE_FIELDS).first.wait_for(state='visible', timeout=15000)
        try:
            with page.expect_response(
                lambda response: response.request.method == 'GET'
                and re.search(r'/manage/drafts/\d+(?:\?|$)', response.url),
                timeout=15000,
            ) as draft_response:
                self._resume_draft(page, title)
        except PWTimeout as exc:
            raise BlogProblem('저장된 임시글을 다시 불러오지 못했습니다.') from exc
        response = draft_response.value
        if not response.ok:
            raise BlogProblem(f'임시글 다시 불러오기 실패: HTTP {response.status}')
        try:
            draft = response.json()['draft']
        except (ValueError, KeyError, TypeError) as exc:
            raise BlogProblem('저장된 임시글 정보를 읽지 못했습니다.') from exc
        if draft.get('title') != title or not draft.get('content', '').strip():
            raise BlogProblem('저장된 임시글의 제목 또는 본문을 확인하지 못했습니다.')
        print(f'저장된 임시글 확인: {title}')

    def _basic_mode(self, page) -> bool:
        if page.locator('#grammar-check-btn').is_visible():
            return True

        def confirm_mode_change(dialog):
            if dialog.type == 'confirm' and '작성 모드' in dialog.message:
                dialog.accept()
            else:
                dialog.dismiss()

        page.on('dialog', confirm_mode_change)
        try:
            html_mode_button = page.locator('button:has(> i.mce-txt:text-is("HTML")):visible').first
            html_mode_button.wait_for(state='visible', timeout=10000)
            html_mode_button.click()
            basic_option = page.locator('#editor-mode-kakao-tistory:visible').first
            basic_option.wait_for(state='visible', timeout=5000)
            basic_option.click()
            page.locator('#grammar-check-btn').wait_for(state='visible', timeout=10000)
            page.wait_for_function(
                '() => (window.tinymce?.activeEditor?.getContent()?.trim().length || 0) > 0',
                timeout=10000,
            )
            return True
        except PWTimeout:
            return False
        finally:
            page.remove_listener('dialog', confirm_mode_change)

    def _spellcheck_once(self, page) -> tuple[int, int, bool]:
        button = page.locator('#grammar-check-btn').first
        button.wait_for(state='visible', timeout=10000)
        try:
            with page.expect_response(
                lambda response: '/manage/post/plugins/grammar-check.json' in response.url,
                timeout=20000,
            ) as response_info:
                button.click()
        except PWTimeout as exc:
            raise BlogProblem('맞춤법 검사 응답을 받지 못했습니다. 임시저장을 중단합니다.') from exc
        response = response_info.value
        if not response.ok:
            raise BlogProblem(f'맞춤법 검사 실패: HTTP {response.status}')
        try:
            sentences = response.json()['sentences']
            has_suggestions = any(
                item.get('etype') != 'no_error'
                for sentence in sentences for item in sentence.get('result', [])
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise BlogProblem('맞춤법 검사 결과를 읽지 못했습니다. 임시저장을 중단합니다.') from exc
        if not has_suggestions:
            return 0, 0, False
        close_button = page.locator('.grammar_close').first
        try:
            close_button.wait_for(state='visible', timeout=10000)
        except PWTimeout as exc:
            raise BlogProblem('맞춤법 검사 결과 화면을 확인하지 못했습니다. 임시저장을 중단합니다.') from exc
        try:
            total = int(page.locator('.grammar_total_count').first.inner_text())
        except ValueError as exc:
            raise BlogProblem('맞춤법 검사 항목 수를 확인하지 못했습니다. 임시저장을 중단합니다.') from exc
        corrected = skipped = 0
        for _ in range(total):
            if not close_button.is_visible():
                break
            replacement = page.locator('.grammar_wanna_word').first.input_value().strip()
            replace_button = page.locator('.grammar_check_replace').first
            if replacement and replace_button.is_enabled():
                replace_button.click()
                corrected += 1
            else:
                page.locator('.grammar_check_next').first.click()
                skipped += 1
            page.wait_for_timeout(250)
        if close_button.is_visible():
            raise BlogProblem('맞춤법 검사가 끝나지 않아 임시저장을 중단합니다.')
        if not page.evaluate('() => (window.tinymce?.activeEditor?.getContent()?.trim().length || 0) > 0'):
            raise BlogProblem('맞춤법 검사 후 본문이 비어 있어 임시저장을 중단합니다.')
        return corrected, skipped, True

    def _spellcheck(self, page):
        corrected_total = skipped_total = 0
        for _ in range(10):
            before = page.evaluate('() => window.tinymce?.activeEditor?.getContent() || ""')
            corrected, skipped, has_suggestions = self._spellcheck_once(page)
            corrected_total += corrected
            skipped_total += skipped
            if not has_suggestions:
                print(f'맞춤법 검사 완료: 자동 수정 {corrected_total}건, 넘기기 {skipped_total}건')
                return
            after = page.evaluate('() => window.tinymce?.activeEditor?.getContent() || ""')
            if after == before:
                if corrected:
                    raise BlogProblem('맞춤법 수정 후 본문 변경을 확인하지 못해 임시저장을 중단합니다.')
                print(f'맞춤법 검사 완료: 자동 수정 {corrected_total}건, 넘기기 {skipped_total}건')
                return
        raise BlogProblem('맞춤법 검사에서 수정 항목이 계속 발견되어 임시저장을 중단합니다.')

    def _save(self, page) -> bool:
        # '완료'/'발행'은 누르지 않음. 정확한 임시저장만 클릭.
        for selector in ['.btn-draft a.action', 'button:has-text("임시저장")',
                         'button[aria-label*="임시저장"]']:
            try:
                loc = page.locator(selector).first
                loc.wait_for(state='visible', timeout=5000)
                label = (loc.inner_text() or '') + ' ' + (loc.get_attribute('aria-label') or '')
                if '임시저장' not in label or '발행' in label or '공개' in label:
                    continue
                loc.click()
                page.wait_for_timeout(1500)
                print('임시저장 버튼을 클릭했습니다. 저장된 임시글을 다시 불러와 확인합니다.')
                return True
            except Exception:
                continue
        return False

    def draft(self, title: str, html: str, category: str | None = None,
              images: dict[int, Path] | None = None, ai_name: str = '') -> dict:
        if images and not ai_name.strip():
            raise BlogProblem('이미지 캡션에 사용할 AI 이름이 비어 있습니다.')
        with sync_playwright() as p:
            context = self._open(p)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(self.site + '/manage/newpost', wait_until='domcontentloaded', timeout=60000)
                try:
                    page.locator(self.TITLE_FIELDS).first.wait_for(state='visible', timeout=15000)
                    print('저장된 티스토리 로그인으로 글쓰기 화면에 접속했습니다.')
                except PWTimeout:
                    raise BlogProblem('글쓰기 화면을 확인하지 못했습니다. 먼저 python run.py login으로 로그인해 주세요.')
                self._save_auth(context)
                self._resume_draft(page, title)
                if category:
                    self._category(page, category)
                    print(f'티스토리 카테고리: {category}')
                title_ok = self._title(page, title)
                if not title_ok:
                    raise BlogProblem('제목 입력 칸을 찾지 못해 임시저장을 중단합니다.')
                uploaded = {}
                for index, path in sorted((images or {}).items()):
                    self._upload_image(page, path)
                    uploaded[index] = self._set_image_caption(page, path, ai_name)
                    print(f'IMAGE:{index:02d} 사진 업로드 및 캡션 입력 완료: {path.name} → {ai_name}')
                html = self._replace_image_slots(html, uploaded, ai_name)
                expected_alt = {}
                for token in IMAGE_TOKEN.findall(html):
                    try:
                        metadata = json.loads(token.rsplit('|', 1)[-1][:-4])
                    except (ValueError, AttributeError):
                        continue
                    if isinstance(metadata, dict) and metadata.get('filename'):
                        expected_alt[metadata['filename']] = metadata.get('alt')
                for path in (images or {}).values():
                    if not expected_alt.get(path.name):
                        raise BlogProblem(f'업로드된 이미지의 ALT가 본문에 없습니다: {path.name}')
                mode_ok = self._html_mode(page)
                html_ok = mode_ok and self._set_html(page, html)
                if not html_ok:
                    raise BlogProblem('HTML 자동 입력에 실패해 임시저장을 중단합니다.')
                saved_click = False
                if title_ok and html_ok:
                    if not self._basic_mode(page):
                        raise BlogProblem('HTML 입력 후 기본모드 전환 또는 본문 확인에 실패했습니다. 임시저장을 중단합니다.')
                    print('기본모드에서 맞춤법 검사를 시작합니다.')
                    self._spellcheck(page)
                    body = page.evaluate('() => window.tinymce.activeEditor.getContent()')
                    body_images = []
                    for token in IMAGE_TOKEN.findall(body):
                        try:
                            body_images.append(json.loads(token.rsplit('|', 1)[-1][:-4]))
                        except (ValueError, AttributeError):
                            continue
                    for path in (images or {}).values():
                        if not any(item.get('filename') == path.name and item.get('caption') == ai_name
                                   and item.get('alt') == expected_alt.get(path.name)
                                   for item in body_images):
                            raise BlogProblem(f'맞춤법 검사 후 사진, 캡션 또는 ALT가 본문에서 사라졌습니다: {path.name}')
                    if images and 1 in images:
                        self._set_representative_image(page, images[1])
                    saved_click = self._save(page)
                    if saved_click and images and 1 in images:
                        self._confirm_saved_representative(page, title, images[1], expected_alt)
                if not saved_click:
                    raise BlogProblem('임시저장 버튼을 찾거나 클릭하지 못해 저장을 확인할 수 없습니다.')
                if not images or 1 not in images:
                    self._confirm_saved_draft(page, title)
                print('임시저장 확인 완료. 공개 발행은 하지 않았습니다.')
                return {'saved': True, 'url': page.url}
            finally:
                context.close()
