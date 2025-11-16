#!/usr/bin/env python3
"""Test AFP detection patterns on production articles."""
import sys
from src.models.database import DatabaseManager
from src.models import Article
from src.utils.content_type_detector import ContentTypeDetector
from src.utils.byline_cleaner import BylineCleaner


def main():
    """Test AFP detection on production AFP articles."""
    db = DatabaseManager()
    
    with db.get_session() as session:
        # Get AFP articles that are NOT marked as wire
        afp_articles = (
            session.query(Article)
            .filter(Article.author.ilike("%afp%"))
            .filter(Article.status != "wire")
            .limit(10)
            .all()
        )
        
        print(f"\n{'='*80}")
        print(f"Testing AFP Detection on {len(afp_articles)} Articles")
        print(f"{'='*80}\n")
        
        detector = ContentTypeDetector()
        byline_cleaner = BylineCleaner()
        
        detected_count = 0
        
        for article in afp_articles:
            # Clean author if present
            cleaned_author = byline_cleaner.clean(article.author) if article.author else None
            
            # Detect content type
            content_type, service = detector.detect_content_type(
                url=article.url or "",
                text=article.text or "",
                content=article.content or "",
                author=cleaned_author or article.author or ""
            )
            
            detected = content_type == "wire"
            if detected:
                detected_count += 1
            
            print(f"Article UID: {article.article_uid}")
            print(f"  URL: {article.url[:80]}..." if article.url and len(article.url) > 80 else f"  URL: {article.url}")
            print(f"  Author: {article.author}")
            print(f"  Current Status: {article.status}")
            print(f"  {'✅' if detected else '❌'} Detected Type: {content_type}")
            print(f"  Detected Service: {service}")
            
            # Show relevant text snippets
            if article.text:
                # Check for dateline pattern
                first_line = article.text.split('\n')[0] if '\n' in article.text else article.text[:100]
                if 'AFP' in first_line.upper() or 'FRANCE' in first_line.upper():
                    print(f"  Dateline: {first_line[:150]}")
                
                # Check for "told AFP" pattern
                if 'told AFP' in article.text or 'told Agence France-Presse' in article.text:
                    # Find and show the context
                    idx = article.text.find('told AFP')
                    if idx == -1:
                        idx = article.text.find('told Agence France-Presse')
                    if idx >= 0:
                        context_start = max(0, idx - 50)
                        context_end = min(len(article.text), idx + 100)
                        context = article.text[context_start:context_end].replace('\n', ' ')
                        print(f"  Attribution: ...{context}...")
            
            print()
        
        print(f"{'='*80}")
        print(f"Summary: {detected_count}/{len(afp_articles)} articles detected as wire")
        print(f"{'='*80}\n")
        
        return detected_count == len(afp_articles)


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
