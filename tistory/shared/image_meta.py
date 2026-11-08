# -*- coding: utf-8 -*-
"""티스토리 이미지 ALT/대표 이미지 순서 규칙.

기존 HTML에 실제 src가 있는 <img>라면 ALT를 자동 추가합니다.
로컬 번호_AI이름 파일은 IMAGE 표시 위치에 업로드합니다. 노션 첨부 파일 다운로드는 별도입니다.
"""
from __future__ import annotations
import html as html_lib
import re
import unicodedata
from pathlib import Path

IMG_PATTERN = re.compile(r'<img\b[^>]*>', re.I | re.S)
ALT_PATTERN = re.compile(r'\s+alt\s*=\s*(?:"[^"]*"|\'[^\']*\')', re.I)
IMAGE_MARKER = re.compile(r'<!--\s*IMAGE\s*:\s*(\d+)\s*-->', re.I)
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}


def resolve_local_images(source_html: str, number: int, ai_name: str,
                         image_dir: Path) -> dict[int, Path]:
    """IMAGE:01은 번호_AI이름, IMAGE:02부터는 번호_AI이름_02 파일에 연결합니다."""
    indices = sorted({int(value) for value in IMAGE_MARKER.findall(source_html)})
    if not indices:
        if re.search(r'<img\b[^>]*\bsrc\s*=\s*(["\'])\s*\1', source_html, re.I):
            raise ValueError('src가 빈 이미지에 IMAGE:01 표시가 없어 이미지 위치를 확인할 수 없습니다.')
        return {}
    if 0 in indices:
        raise ValueError('이미지 표시는 IMAGE:01부터 시작해야 합니다.')
    if not image_dir.is_dir():
        raise ValueError(f'이미지 폴더가 없습니다: {image_dir}')
    resolved = {}
    for index in indices:
        stem = f'{number}_{ai_name.strip()}' + (f'_{index:02d}' if index > 1 else '')
        expected = unicodedata.normalize('NFC', stem).casefold()
        matches = [path for path in image_dir.iterdir()
                   if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
                   and unicodedata.normalize('NFC', path.stem).casefold() == expected]
        if len(matches) != 1:
            raise ValueError(f'IMAGE:{index:02d}에 맞는 이미지 파일이 {len(matches)}개입니다. '
                             f'{image_dir}에서 {stem}.png 같은 이름의 파일을 하나만 두세요.')
        if matches[0].stat().st_size == 0:
            raise ValueError(f'이미지 파일이 비어 있습니다: {matches[0]}')
        resolved[index] = matches[0]
    return resolved


def suggest_alt(ai_name: str, index: int, description: str = '') -> str:
    """노션 속성 AI 이름을 바탕으로 ALT를 제안합니다.

    각 사진에 노션 캡션/설명이 있다면 그것을 더해 접근성을 개선합니다.
    """
    name = re.sub(r'\s+', ' ', ai_name).strip() or '이미지'
    desc = re.sub(r'\s+', ' ', description).strip()
    if desc:
        return f'{name} {desc}'
    if index == 1:
        return f'{name} 대표 이미지'
    return f'{name} 관련 화면 {index}'


def fill_existing_img_alts(source_html: str, ai_name: str) -> tuple[str, list[dict]]:
    """기존 img 태그의 빈 ALT만 채우고 기존 의미 있는 ALT는 존중합니다."""
    result = []
    counter = 0

    def rewrite(match):
        nonlocal counter
        counter += 1
        tag = match.group(0)
        alt = suggest_alt(ai_name, counter)
        attr = re.search(r'\s+alt\s*=\s*(["\'])(.*?)\1', tag, re.I | re.S)
        if attr and attr.group(2).strip():
            alt = html_lib.unescape(attr.group(2))
            new_tag = tag
        else:
            escaped = html_lib.escape(alt, quote=True)
            if attr:
                new_tag = tag[:attr.start()] + f' alt="{escaped}"' + tag[attr.end():]
            else:
                n = tag.rfind('>')
                slash = tag[:n].rstrip().endswith('/')
                if slash:
                    slash_at = tag[:n].rfind('/')
                    new_tag = tag[:slash_at] + f' alt="{escaped}" /' + tag[n:]
                else:
                    new_tag = tag[:n] + f' alt="{escaped}"' + tag[n:]
        result.append({'index': counter, 'alt': alt, 'representative': counter == 1,
                       'needs_upload': bool(re.search(r'\bsrc\s*=\s*["\']\s*["\']', tag, re.I))})
        return new_tag

    updated = IMG_PATTERN.sub(rewrite, source_html)
    markers = sorted({int(x) for x in IMAGE_MARKER.findall(updated)})
    for idx in markers:
        if not any(x['index'] == idx for x in result):
            result.append({'index': idx, 'alt': suggest_alt(ai_name, idx),
                           'representative': idx == 1, 'needs_upload': True})
    result.sort(key=lambda x: x['index'])
    return updated, result
