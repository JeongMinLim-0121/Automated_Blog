from pathlib import Path

BLOG_LABEL = 'TstoryBlog1'
BLOG_URL = 'https://seoebear.tistory.com'
IMAGE_DIR = Path(__file__).resolve().parents[2] / 'images' / 'tistory' / BLOG_LABEL
NOTION_SOURCE_ENV = 'TSTORY_BLOG1_NOTION_DATA_SOURCE_ID'
AI_NAME_ENV = 'TSTORY_BLOG1_PROP_AI_NAME'
CATEGORY_REQUIRED = True
