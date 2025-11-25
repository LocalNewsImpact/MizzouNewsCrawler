from src.models.database import DatabaseManager
from src.models import Article
from src.utils.content_type_detector import ContentTypeDetector
from sqlalchemy import select

urls = [
    "https://abc17news.com/alerts/2025/11/24/dense-fog-advisory-issued-november-24-at-417am-cst-until-november-24-at-900am-cst-by-nws-kansas-city-pleasant-hill-mo",
    "https://www.ksmu.org/2025-11-23/the-trump-administration-is-softening-its-tone-on-fema",
    "https://www.ky3.com/2025/11/23/donald-glover-says-he-had-stroke"
]

db = DatabaseManager()
detector = ContentTypeDetector()

with db.get_session() as session:
    for url in urls:
        print(f"\n--- Inspecting: {url} ---")
        article = session.execute(select(Article).where(Article.url == url)).scalar_one_or_none()
        if article:
            print(f"Author: '{article.author}'")
            print(f"Title: '{article.title}'")
            content_snippet = article.content[:300] if article.content else "None"
            print(f"Content Start: {content_snippet}")
            
            result = detector.detect(
                url=article.url,
                title=article.title,
                metadata=article.meta,
                content=article.content,
                author=article.author
            )
            print(f"Result: {result}")
        else:
            print("Article not found")
