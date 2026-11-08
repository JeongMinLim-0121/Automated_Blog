# -*- coding: utf-8 -*-
"""이 블로그의 설정으로 티스토리 공통 코드를 실행합니다."""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from settings import (BLOG_LABEL, BLOG_URL, IMAGE_DIR, NOTION_SOURCE_ENV,
                      AI_NAME_ENV, CATEGORY_REQUIRED)
from shared.runner import BlogConfig, run_blog

if __name__ == '__main__':
    run_blog(BlogConfig(
        label=BLOG_LABEL,
        url=BLOG_URL,
        directory=HERE,
        image_dir=IMAGE_DIR,
        source_env=NOTION_SOURCE_ENV,
        ai_name_env=AI_NAME_ENV,
        category_required=CATEGORY_REQUIRED,
    ))
