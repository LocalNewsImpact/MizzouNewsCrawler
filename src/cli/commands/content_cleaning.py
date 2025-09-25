"""
Content cleaning commands for detecting and removing boilerplate text.
"""
import click
import sqlite3
from urllib.parse import urlparse
from collections import defaultdict, Counter
import json
from datetime import datetime

from src.utils.content_cleaner_improved import ImprovedContentCleaner
from src.utils.content_cleaner_twophase import TwoPhaseContentCleaner
from src.utils.content_cleaner_balanced import BalancedBoundaryContentCleaner


@click.group()
def content_cleaning():
    """Content cleaning commands for detecting and removing boilerplate text."""
    pass


@content_cleaning.command()
@click.option('--domain', help='Analyze specific domain only')
@click.option('--min-articles', default=2, help='Minimum articles per domain to analyze')
@click.option('--confidence-threshold', default=0.7, help='Confidence threshold for detection')
@click.option('--dry-run', is_flag=True, help='Show what would be cleaned without making changes')
@click.option('--verbose', is_flag=True, help='Show detailed analysis per article')
@click.option('--output-json', help='Save detailed results to JSON file')
def analyze_domains(domain, min_articles, confidence_threshold, dry_run, verbose, output_json):
    """Analyze domains for boilerplate content patterns."""
    
    db_path = 'data/mizzou.db'
    cleaner = ImprovedContentCleaner(db_path=db_path, confidence_threshold=confidence_threshold)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get domain statistics
    if domain:
        cursor.execute('''
            SELECT url, id, content, LENGTH(content) as content_length
            FROM articles 
            WHERE url LIKE ?
            ORDER BY url
        ''', (f'%{domain}%',))
    else:
        cursor.execute('''
            SELECT url, id, content, LENGTH(content) as content_length
            FROM articles 
            ORDER BY url
        ''')
    
    articles = cursor.fetchall()
    
    # Group by domain
    domain_articles = defaultdict(list)
    for url, article_id, content, content_length in articles:
        parsed_domain = urlparse(url).netloc
        domain_articles[parsed_domain].append({
            'id': article_id,
            'url': url,
            'content': content,
            'length': content_length
        })
    
    # Filter domains with minimum articles
    filtered_domains = {
        d: arts for d, arts in domain_articles.items() 
        if len(arts) >= min_articles
    }
    
    if not filtered_domains:
        click.echo(f"No domains found with at least {min_articles} articles")
        return
    
    click.echo(f"Analyzing {len(filtered_domains)} domains with {confidence_threshold} confidence threshold...")
    click.echo(f"Dry run: {'Yes' if dry_run else 'No'}")
    click.echo()
    
    total_stats = {
        'domains_analyzed': 0,
        'articles_analyzed': 0,
        'articles_with_boilerplate': 0,
        'total_characters_removed': 0,
        'processing_time': 0
    }
    
    detailed_results = {}
    
    for domain_name, domain_articles_list in sorted(filtered_domains.items()):
        total_stats['domains_analyzed'] += 1
        
        click.echo(f"📊 Domain: {domain_name} ({len(domain_articles_list)} articles)")
        
        domain_stats = {
            'articles_total': len(domain_articles_list),
            'articles_with_boilerplate': 0,
            'total_chars_removed': 0,
            'avg_confidence': 0,
            'pattern_types': Counter(),
            'articles': []
        }
        
        confidences = []
        
        for article in domain_articles_list:
            total_stats['articles_analyzed'] += 1
            
            # Skip articles with no content
            if not article['content']:
                continue
            
            cleaned_content, telemetry = cleaner.clean_content(
                content=article['content'],
                domain=domain_name,
                article_id=article['id'],
                dry_run=dry_run
            )
            
            total_stats['processing_time'] += telemetry.processing_time
            
            article_result = {
                'id': article['id'],
                'url': article['url'],
                'original_length': telemetry.original_length,
                'cleaned_length': telemetry.cleaned_length,
                'chars_removed': telemetry.original_length - telemetry.cleaned_length,
                'segments_removed': telemetry.segments_removed,
                'removed_segments': telemetry.removed_segments,
                'processing_time': telemetry.processing_time
            }
            
            if telemetry.segments_removed > 0:
                total_stats['articles_with_boilerplate'] += 1
                domain_stats['articles_with_boilerplate'] += 1
                chars_removed = telemetry.original_length - telemetry.cleaned_length
                domain_stats['total_chars_removed'] += chars_removed
                total_stats['total_characters_removed'] += chars_removed
                
                # Track pattern types and confidences
                for segment in telemetry.removed_segments:
                    pattern_type = segment.get('pattern_type', 'unknown')
                    domain_stats['pattern_types'][pattern_type] += 1
                    confidences.append(segment['confidence'])
                
                if verbose:
                    click.echo(f"  ✅ {article['id'][:8]}... - Removed {chars_removed} chars ({telemetry.segments_removed} segments)")
                    for i, segment in enumerate(telemetry.removed_segments, 1):
                        click.echo(f"     {i}. {segment.get('pattern_type', 'unknown')} (conf: {segment['confidence']:.3f}, pos: {segment['position']}, len: {segment['length']})")
            elif verbose:
                click.echo(f"  ⚪ {article['id'][:8]}... - No boilerplate detected")
            
            domain_stats['articles'].append(article_result)
        
        if confidences:
            domain_stats['avg_confidence'] = sum(confidences) / len(confidences)
        
        # Summary for this domain
        if domain_stats['articles_with_boilerplate'] > 0:
            percentage = (domain_stats['articles_with_boilerplate'] / domain_stats['articles_total']) * 100
            click.echo(f"   📈 {domain_stats['articles_with_boilerplate']}/{domain_stats['articles_total']} articles ({percentage:.1f}%) had boilerplate")
            click.echo(f"   🧹 {domain_stats['total_chars_removed']:,} characters {'would be' if dry_run else 'were'} removed")
            click.echo(f"   🎯 Average confidence: {domain_stats['avg_confidence']:.3f}")
            
            if domain_stats['pattern_types']:
                patterns = ', '.join([f"{k}({v})" for k, v in domain_stats['pattern_types'].most_common()])
                click.echo(f"   🔍 Patterns: {patterns}")
        else:
            click.echo("   ⚪ No boilerplate detected")
        
        click.echo()
        detailed_results[domain_name] = domain_stats
    
    # Overall summary
    click.echo("=" * 60)
    click.echo("📊 OVERALL SUMMARY")
    click.echo(f"Domains analyzed: {total_stats['domains_analyzed']}")
    click.echo(f"Articles analyzed: {total_stats['articles_analyzed']}")
    click.echo(f"Articles with boilerplate: {total_stats['articles_with_boilerplate']}")
    
    if total_stats['articles_analyzed'] > 0:
        overall_percentage = (total_stats['articles_with_boilerplate'] / total_stats['articles_analyzed']) * 100
        click.echo(f"Overall detection rate: {overall_percentage:.1f}%")
    
    click.echo(f"Total characters {'would be' if dry_run else 'were'} removed: {total_stats['total_characters_removed']:,}")
    click.echo(f"Total processing time: {total_stats['processing_time']:.2f}s")
    
    # Save detailed results if requested
    if output_json:
        output_data = {
            'timestamp': datetime.now().isoformat(),
            'parameters': {
                'domain_filter': domain,
                'min_articles': min_articles,
                'confidence_threshold': confidence_threshold,
                'dry_run': dry_run
            },
            'summary': total_stats,
            'domains': detailed_results
        }
        
        with open(output_json, 'w') as f:
            json.dump(output_data, f, indent=2)
        click.echo(f"📄 Detailed results saved to: {output_json}")
    
    conn.close()


@content_cleaning.command()
@click.argument('article_id')
@click.option('--confidence-threshold', default=0.7, help='Confidence threshold for detection')
@click.option('--dry-run', is_flag=True, help='Show what would be cleaned without making changes')
@click.option('--show-content', is_flag=True, help='Show before/after content samples')
def clean_article(article_id, confidence_threshold, dry_run, show_content):
    """Clean a specific article by ID."""
    
    db_path = 'data/mizzou.db'
    cleaner = ImprovedContentCleaner(db_path=db_path, confidence_threshold=confidence_threshold)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('SELECT url, content FROM articles WHERE id = ?', (article_id,))
    result = cursor.fetchone()
    
    if not result:
        click.echo(f"❌ Article not found: {article_id}")
        return
    
    url, content = result
    domain = urlparse(url).netloc
    
    click.echo(f"🔍 Analyzing article: {article_id}")
    click.echo(f"📡 Domain: {domain}")
    click.echo(f"📏 Original length: {len(content):,} characters")
    click.echo(f"🎯 Confidence threshold: {confidence_threshold}")
    click.echo(f"🧪 Dry run: {'Yes' if dry_run else 'No'}")
    click.echo()
    
    if show_content:
        click.echo("📖 Original content (first 300 chars):")
        click.echo(repr(content[:300]))
        click.echo()
    
    # Clean the content
    cleaned_content, telemetry = cleaner.clean_content(
        content=content,
        domain=domain,
        article_id=article_id,
        dry_run=dry_run
    )
    
    # Show results
    if telemetry.segments_removed > 0:
        chars_removed = telemetry.original_length - telemetry.cleaned_length
        click.echo(f"✅ Boilerplate detected and {'would be' if dry_run else 'was'} removed!")
        click.echo(f"📊 Segments removed: {telemetry.segments_removed}")
        click.echo(f"🧹 Characters removed: {chars_removed:,}")
        click.echo(f"⏱️  Processing time: {telemetry.processing_time:.3f}s")
        click.echo()
        
        for i, segment in enumerate(telemetry.removed_segments, 1):
            click.echo(f"{i}. Pattern: {segment.get('pattern_type', 'unknown')}")
            click.echo(f"   Position: {segment['position']}")
            click.echo(f"   Length: {segment['length']}")
            click.echo(f"   Confidence: {segment['confidence']:.3f}")
            click.echo(f"   Text: {repr(segment['text'][:100])}{'...' if len(segment['text']) > 100 else ''}")
            click.echo()
        
        if show_content and not dry_run:
            click.echo("📖 Cleaned content (first 300 chars):")
            click.echo(repr(cleaned_content[:300]))
            click.echo()
        
        # Update database if not dry run
        if not dry_run:
            cursor.execute('UPDATE articles SET content = ? WHERE id = ?', (cleaned_content, article_id))
            conn.commit()
            click.echo("💾 Article content updated in database")
    else:
        click.echo("⚪ No boilerplate detected")
        click.echo(f"⏱️  Processing time: {telemetry.processing_time:.3f}s")
    
    conn.close()


@content_cleaning.command()
@click.option('--domain', help='Apply cleaning to specific domain only')
@click.option('--confidence-threshold', default=0.8, help='Confidence threshold for cleaning')
@click.option('--limit', type=int, help='Limit number of articles to process')
@click.option('--dry-run', is_flag=True, help='Show what would be cleaned without making changes')
@click.option('--verbose', is_flag=True, help='Show progress for each article')
def apply_cleaning(domain, confidence_threshold, limit, dry_run, verbose):
    """Apply content cleaning to articles in the database."""
    
    db_path = 'data/mizzou.db'
    cleaner = ImprovedContentCleaner(db_path=db_path, confidence_threshold=confidence_threshold)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Build query
    query = 'SELECT id, url, content FROM articles'
    params = []
    
    if domain:
        query += ' WHERE url LIKE ?'
        params.append(f'%{domain}%')
    
    query += ' ORDER BY url'
    
    if limit:
        query += ' LIMIT ?'
        params.append(limit)
    
    cursor.execute(query, params)
    articles = cursor.fetchall()
    
    if not articles:
        click.echo("No articles found matching criteria")
        return
    
    click.echo(f"🚀 Processing {len(articles)} articles...")
    click.echo(f"🎯 Confidence threshold: {confidence_threshold}")
    click.echo(f"🧪 Dry run: {'Yes' if dry_run else 'No'}")
    click.echo()
    
    stats = {
        'processed': 0,
        'cleaned': 0,
        'chars_removed': 0,
        'processing_time': 0
    }
    
    updates = []
    
    for article_id, url, content in articles:
        stats['processed'] += 1
        domain_name = urlparse(url).netloc
        
        cleaned_content, telemetry = cleaner.clean_content(
            content=content,
            domain=domain_name,
            article_id=article_id,
            dry_run=dry_run
        )
        
        stats['processing_time'] += telemetry.processing_time
        
        if telemetry.segments_removed > 0:
            stats['cleaned'] += 1
            chars_removed = telemetry.original_length - telemetry.cleaned_length
            stats['chars_removed'] += chars_removed
            
            if not dry_run:
                updates.append((cleaned_content, article_id))
            
            if verbose:
                click.echo(f"✅ {article_id[:8]}... ({domain_name}) - Removed {chars_removed} chars")
        elif verbose:
            click.echo(f"⚪ {article_id[:8]}... ({domain_name}) - No changes")
        
        # Progress indicator for large batches
        if stats['processed'] % 100 == 0:
            percentage = (stats['processed'] / len(articles)) * 100
            click.echo(f"📊 Progress: {stats['processed']}/{len(articles)} ({percentage:.1f}%)")
    
    # Apply updates if not dry run
    if updates and not dry_run:
        cursor.executemany('UPDATE articles SET content = ? WHERE id = ?', updates)
        conn.commit()
        click.echo(f"💾 Updated {len(updates)} articles in database")
    
    # Final summary
    click.echo()
    click.echo("=" * 50)
    click.echo("📊 CLEANING SUMMARY")
    click.echo(f"Articles processed: {stats['processed']}")
    click.echo(f"Articles cleaned: {stats['cleaned']}")
    
    if stats['processed'] > 0:
        percentage = (stats['cleaned'] / stats['processed']) * 100
        click.echo(f"Cleaning rate: {percentage:.1f}%")
    
    click.echo(f"Characters {'would be' if dry_run else 'were'} removed: {stats['chars_removed']:,}")
    click.echo(f"Total processing time: {stats['processing_time']:.2f}s")
    
    conn.close()


if __name__ == '__main__':
    content_cleaning()


@content_cleaning_group.command("clean-content")
@click.argument("article-id", type=int)
@click.option("--dry-run/--apply", default=True,
              help="Show what would be removed without applying changes")
@click.option("--confidence-threshold", type=float, default=0.7,
              help="Minimum confidence score to remove content")
def clean_content_command(article_id: int, dry_run: bool,
                         confidence_threshold: float):
    """Clean content for a specific article."""
    try:
        # Get article
        conn = sqlite3.connect("mizzou.db")
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, url, content
            FROM articles 
            WHERE id = ?
        """, (article_id,))
        
        row = cursor.fetchone()
        if not row:
            click.echo(f"Article {article_id} not found", err=True)
            return 1
        
        article_id, url, content = row
        conn.close()
        
        # Extract domain from URL
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        
        # Initialize cleaner
        cleaner = ContentCleaner(
            db_path="mizzou.db",
            confidence_threshold=confidence_threshold
        )
        
        # Clean content
        cleaned_content, telemetry = cleaner.clean_content(
            content=content,
            domain=domain,
            article_id=article_id,
            dry_run=dry_run
        )
        
        # Display results
        click.echo(f"Article ID: {article_id}")
        click.echo(f"Domain: {domain}")
        click.echo(f"Original length: {telemetry.original_length}")
        click.echo(f"Cleaned length: {telemetry.cleaned_length}")
        click.echo(f"Characters removed: "
                  f"{telemetry.original_length - telemetry.cleaned_length}")
        click.echo(f"Segments removed: {telemetry.segments_removed}")
        click.echo(f"Processing time: {telemetry.processing_time:.3f}s")
        
        if dry_run:
            click.echo("\n(Dry run - no changes applied)")
        else:
            click.echo("\nContent has been cleaned and updated")
        
    except Exception as e:
        logger.error(f"Error cleaning article {article_id}: {e}")
        click.echo(f"Error: {e}", err=True)
        return 1


@content_cleaning_group.command("list-domains")
@click.option("--min-articles", type=int, default=10,
              help="Minimum articles per domain to include")
def list_domains_command(min_articles: int):
    """List domains with article counts for analysis."""
    try:
        conn = sqlite3.connect("mizzou.db")
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                CASE 
                    WHEN url LIKE 'http://%' THEN 
                        substr(url, 8, instr(substr(url, 8), '/') - 1)
                    WHEN url LIKE 'https://%' THEN 
                        substr(url, 9, instr(substr(url, 9), '/') - 1)
                    ELSE 'unknown'
                END as domain,
                COUNT(*) as article_count
            FROM articles 
            WHERE content IS NOT NULL 
            AND content != ''
            GROUP BY domain
            HAVING article_count >= ?
            ORDER BY article_count DESC
        """, (min_articles,))
        
        results = cursor.fetchall()
        conn.close()
        
        click.echo("Domains with sufficient articles for analysis:")
        click.echo("-" * 50)
        
        for domain, count in results:
            click.echo(f"{domain:<40} {count:>8} articles")
        
        click.echo(f"\nFound {len(results)} domains with "
                  f"{min_articles}+ articles")
        
    except Exception as e:
        logger.error(f"Error listing domains: {e}")
        click.echo(f"Error: {e}", err=True)
        return 1


def _display_analysis_results(results: dict):
    """Display analysis results in a readable format."""
    click.echo("=" * 60)
    click.echo(f"DOMAIN ANALYSIS: {results['domain']}")
    click.echo("=" * 60)
    
    click.echo(f"Articles analyzed: {results['articles']}")
    click.echo(f"Boilerplate segments found: {results['boilerplate_segments']}")
    
    if results['segments']:
        click.echo("\nTop boilerplate patterns:")
        click.echo("-" * 40)
        
        for i, segment in enumerate(results['segments'][:10], 1):
            click.echo(f"\n{i}. Confidence: {segment['confidence_score']:.3f}")
            click.echo(f"   Occurrences: {segment['occurrence_count']}")
            click.echo(f"   Position: {segment['avg_position']['start']:.1%} "
                      f"- {segment['avg_position']['end']:.1%}")
            click.echo(f"   Text: {segment['text']}")
    else:
        click.echo("\nNo significant boilerplate patterns detected.")


@content_cleaning.command()
@click.option('--domain', required=True, help='Domain to analyze')
@click.option('--sample-size', default=20, help='Number of articles to sample')
@click.option('--min-occurrences', default=3, help='Minimum occurrences to consider')
@click.option('--dry-run', is_flag=True, help='Show analysis without making changes')
def analyze_exact(domain, sample_size, min_occurrences, dry_run):
    """Analyze domain for EXACT duplicate text segments using two-phase approach."""
    
    db_path = 'data/mizzou.db'
    cleaner = TwoPhaseContentCleaner(db_path=db_path)
    
    click.echo(f"Analyzing {domain} for exact duplicate segments...")
    click.echo(f"Sample size: {sample_size}, Min occurrences: {min_occurrences}")
    
    results = cleaner.analyze_domain(domain, sample_size, min_occurrences)
    
    if not results['segments']:
        click.echo("No exact duplicate segments found.")
        return
    
    stats = results['stats']
    click.echo("\n=== ANALYSIS RESULTS ===")
    click.echo(f"Articles analyzed: {results['article_count']}")
    click.echo(f"Segments found: {len(results['segments'])}")
    click.echo(f"Affected articles: {stats['affected_articles']}")
    click.echo(f"Total removable characters: {stats['total_removable_chars']:,}")
    click.echo(f"Removal percentage: {stats['removal_percentage']:.1f}%")
    
    click.echo("\n=== EXACT DUPLICATE SEGMENTS ===")
    for i, segment in enumerate(results['segments'], 1):
        click.echo(f"\n--- Segment {i} ---")
        click.echo(f"Type: {segment['pattern_type']}")
        click.echo(f"Length: {segment['length']} characters")
        click.echo(f"Occurrences: {segment['occurrences']} articles")
        click.echo(f"Position consistency: {segment['position_consistency']:.3f}")
        click.echo(f"Article IDs: {', '.join(segment['article_ids'][:5])}...")
        
        # Show text preview
        preview = segment['text'][:200].replace('\n', '\\n')
        click.echo(f"Text preview: '{preview}{'...' if len(segment['text']) > 200 else ''}'")
        
        if dry_run:
            click.echo("(DRY RUN - no changes made)")


@content_cleaning.command()
@click.option('--domain', required=True, help='Domain to analyze')
@click.option('--sample-size', default=20, help='Number of articles to sample')
@click.option('--min-occurrences', default=3, help='Minimum occurrences for boilerplate detection')
@click.option('--show-text', is_flag=True, help='Show full text of detected segments')
def analyze_balanced(domain, sample_size, min_occurrences, show_text):
    """Analyze domain using balanced boundary content cleaner."""
    
    cleaner = BalancedBoundaryContentCleaner()
    result = cleaner.analyze_domain(domain, sample_size, min_occurrences)
    
    click.echo(f"Domain: {result['domain']}")
    click.echo(f"Articles analyzed: {result['article_count']}")
    click.echo(f"Segments found: {len(result['segments'])}")
    
    if 'stats' in result:
        stats = result['stats']
        click.echo(f"Affected articles: {stats['affected_articles']}")
        click.echo(f"Total removable characters: {stats['total_removable_chars']:,}")
        click.echo(f"Removal percentage: {stats['removal_percentage']:.1f}%")
    
    if result['segments']:
        click.echo("\nDetected segments:")
        click.echo("=" * 60)
        
        for i, segment in enumerate(result['segments'], 1):
            click.echo(f"{i}. Pattern: {segment['pattern_type']}")
            click.echo(f"   Occurrences: {segment['occurrences']}")
            click.echo(f"   Length: {segment['length']} chars")
            click.echo(f"   Boundary score: {segment['boundary_score']:.2f}")
            
            if show_text:
                click.echo(f"   Text: \"{segment['text']}\"")
            else:
                preview = segment['text'][:100]
                click.echo(f"   Preview: \"{preview}{'...' if len(segment['text']) > 100 else ''}\"")
            
            click.echo()
    else:
        click.echo("No boilerplate segments detected.")


# Register the command group
def register_commands(cli):
    """Register content cleaning commands with the main CLI."""
    cli.add_command(content_cleaning)