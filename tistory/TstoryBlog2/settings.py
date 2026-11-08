from pathlib import Path

BLOG_LABEL = 'TstoryBlog2'
BLOG_URL = 'https://takeanews.tistory.com'
IMAGE_DIR = Path(__file__).resolve().parents[2] / 'images' / 'tistory' / BLOG_LABEL
NOTION_SOURCE_ENV = 'TSTORY_BLOG2_NOTION_DATA_SOURCE_ID'
AI_NAME_ENV = 'TSTORY_BLOG2_PROP_AI_NAME'
CATEGORY_REQUIRED = True
