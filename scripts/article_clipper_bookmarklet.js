/**
 * Article Clipper Bookmarklet for MizzouNewsCrawler
 * 
 * Extracts article metadata and copies to clipboard in Google Sheets format.
 * Based on extraction logic from src/crawler/__init__.py
 * 
 * Fields extracted (tab-separated):
 * 1. URL
 * 2. Headline
 * 3. Publication Date
 * 4. Byline/Author
 * 5. Story Text (first 5000 chars)
 * 
 * USAGE:
 * 1. Create a new bookmark in your browser
 * 2. Copy the minified version below as the URL
 * 3. Navigate to any article and click the bookmark
 * 4. Paste into Google Sheets (Ctrl+V / Cmd+V)
 */

(function() {
    'use strict';
    
    // ========== EXTRACTION FUNCTIONS ==========
    
    function extractUrl() {
        return window.location.href;
    }
    
    function extractTitle() {
        // 1. Try Open Graph title (most reliable for articles)
        const ogTitle = document.querySelector('meta[property="og:title"]');
        if (ogTitle && ogTitle.content) {
            return ogTitle.content.trim();
        }
        
        // 2. Try JSON-LD headline
        const jsonLdScripts = document.querySelectorAll('script[type="application/ld+json"]');
        for (const script of jsonLdScripts) {
            try {
                const data = JSON.parse(script.textContent);
                const items = Array.isArray(data) ? data : [data];
                for (const item of items) {
                    if (item && item.headline) {
                        return item.headline.trim();
                    }
                }
            } catch (e) {}
        }
        
        // 3. Try h1 (common for article headlines)
        const h1 = document.querySelector('article h1, .article h1, main h1, h1');
        if (h1) {
            return h1.textContent.trim();
        }
        
        // 4. Fallback to title tag (often includes site name)
        const title = document.querySelector('title');
        if (title) {
            // Remove common site suffixes
            let text = title.textContent.trim();
            text = text.replace(/\s*[\|\-–—]\s*[^|\-–—]+$/, '').trim();
            return text;
        }
        
        return '';
    }
    
    function extractPublishDate() {
        // 1. Try JSON-LD datePublished (most standardized)
        const jsonLdScripts = document.querySelectorAll('script[type="application/ld+json"]');
        for (const script of jsonLdScripts) {
            try {
                const data = JSON.parse(script.textContent);
                const items = Array.isArray(data) ? data : [data];
                for (const item of items) {
                    if (!item) continue;
                    const datePublished = item.datePublished || item.dateCreated || item.publishedDate;
                    if (datePublished) {
                        const dateStr = typeof datePublished === 'object' 
                            ? (datePublished['@value'] || datePublished.value || String(datePublished))
                            : String(datePublished);
                        const parsed = new Date(dateStr);
                        if (!isNaN(parsed)) {
                            return formatDate(parsed);
                        }
                    }
                }
            } catch (e) {}
        }
        
        // 2. Try meta tags in priority order
        const metaSelectors = [
            'meta[property="article:published_time"]',
            'meta[name="pubdate"]',
            'meta[name="publishdate"]',
            'meta[name="date"]',
            'meta[itemprop="datePublished"]',
            'meta[name="publish_date"]',
            'meta[property="article:published"]',
            'meta[name="DC.date.issued"]',
            'meta[name="sailthru.date"]'
        ];
        
        for (const selector of metaSelectors) {
            const meta = document.querySelector(selector);
            if (meta && meta.content) {
                const parsed = new Date(meta.content);
                if (!isNaN(parsed)) {
                    return formatDate(parsed);
                }
            }
        }
        
        // 3. Try time element with datetime attribute
        const timeElements = document.querySelectorAll('time[datetime]');
        for (const time of timeElements) {
            const parsed = new Date(time.getAttribute('datetime'));
            if (!isNaN(parsed)) {
                return formatDate(parsed);
            }
        }
        
        return '';
    }
    
    function formatDate(date) {
        // Format as YYYY-MM-DD for Google Sheets
        const year = date.getFullYear();
        const month = String(date.getMonth() + 1).padStart(2, '0');
        const day = String(date.getDate()).padStart(2, '0');
        return `${year}-${month}-${day}`;
    }
    
    function extractAuthor() {
        // 1. Try JSON-LD author (most structured)
        const jsonLdScripts = document.querySelectorAll('script[type="application/ld+json"]');
        for (const script of jsonLdScripts) {
            try {
                const data = JSON.parse(script.textContent);
                const items = Array.isArray(data) ? data : [data];
                for (const item of items) {
                    if (!item) continue;
                    let author = item.author;
                    if (author) {
                        if (Array.isArray(author)) {
                            const names = author.map(a => typeof a === 'string' ? a : (a.name || '')).filter(Boolean);
                            if (names.length) return names.join(', ');
                        } else if (typeof author === 'object' && author.name) {
                            return author.name.trim();
                        } else if (typeof author === 'string') {
                            return author.trim();
                        }
                    }
                }
            } catch (e) {}
        }
        
        // 2. Try meta tags
        const metaSelectors = [
            'meta[name="author"]',
            'meta[property="article:author"]',
            'meta[name="article:author"]',
            'meta[name="byl"]',
            'meta[name="sailthru.author"]'
        ];
        
        for (const selector of metaSelectors) {
            const meta = document.querySelector(selector);
            if (meta && meta.content) {
                return cleanAuthor(meta.content);
            }
        }
        
        // 3. Try common byline selectors
        const bylineSelectors = [
            '[rel="author"]',
            '.byline',
            '.author',
            '.article-author',
            '.post-author',
            '[itemprop="author"]',
            '.byline__name',
            '.author-name'
        ];
        
        for (const selector of bylineSelectors) {
            const element = document.querySelector(selector);
            if (element) {
                const text = element.textContent.trim();
                if (text && text.length < 200) { // Sanity check
                    return cleanAuthor(text);
                }
            }
        }
        
        return '';
    }
    
    function cleanAuthor(text) {
        // Remove common prefixes
        let cleaned = text.replace(/^(By|Written by|Author:?)\s*/i, '');
        // Remove extra whitespace
        cleaned = cleaned.replace(/\s+/g, ' ').trim();
        return cleaned;
    }
    
    function extractContent() {
        // Clone body to avoid modifying the actual page
        const clone = document.body.cloneNode(true);
        
        // Remove unwanted elements
        const removeSelectors = [
            'script', 'style', 'nav', 'header', 'footer', 'aside',
            '.sidebar', '.navigation', '.menu', '.social-share',
            '.comments', '.related-articles', '.advertisement', '.ad',
            '[role="navigation"]', '[role="complementary"]'
        ];
        
        for (const selector of removeSelectors) {
            clone.querySelectorAll(selector).forEach(el => el.remove());
        }
        
        // Try content selectors in priority order
        const contentSelectors = [
            'article .article-body',
            'article .story-body',
            'article .entry-content',
            'article .post-content',
            'article .content',
            '[itemprop="articleBody"]',
            '.article-content',
            '.story-content',
            '.post-content',
            '.entry-content',
            'article',
            '[role="main"]',
            'main',
            '.content'
        ];
        
        for (const selector of contentSelectors) {
            const element = clone.querySelector(selector);
            if (element) {
                const text = cleanText(element.textContent);
                if (text.length > 200) { // Minimum content length
                    return text.substring(0, 5000); // Limit for clipboard
                }
            }
        }
        
        // Fallback to body
        const text = cleanText(clone.textContent);
        return text.substring(0, 5000);
    }
    
    function cleanText(text) {
        // Normalize whitespace
        return text
            .replace(/[\t\n\r]+/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }
    
    // ========== MAIN EXTRACTION ==========
    
    function extractArticle() {
        const url = extractUrl();
        const title = extractTitle();
        const publishDate = extractPublishDate();
        const author = extractAuthor();
        const content = extractContent();
        
        return {
            url,
            title,
            publishDate,
            author,
            content
        };
    }
    
    function formatForSheets(data) {
        // Tab-separated for direct paste into Google Sheets
        // Escape tabs and newlines in content
        const escapedContent = data.content
            .replace(/\t/g, ' ')
            .replace(/\n/g, ' ');
        
        return [
            data.url,
            data.title,
            data.publishDate,
            data.author,
            escapedContent
        ].join('\t');
    }
    
    function copyToClipboard(text) {
        // Modern clipboard API
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(() => {
                showNotification('✓ Article copied to clipboard!', 'success');
            }).catch(err => {
                fallbackCopy(text);
            });
        } else {
            fallbackCopy(text);
        }
    }
    
    function fallbackCopy(text) {
        // Fallback for older browsers or non-HTTPS
        const textarea = document.createElement('textarea');
        textarea.value = text;
        textarea.style.cssText = 'position:fixed;left:-9999px;top:-9999px;';
        document.body.appendChild(textarea);
        textarea.select();
        try {
            document.execCommand('copy');
            showNotification('✓ Article copied to clipboard!', 'success');
        } catch (err) {
            showNotification('✗ Copy failed - please copy manually', 'error');
            console.error('Copy failed:', err);
        }
        document.body.removeChild(textarea);
    }
    
    function showNotification(message, type) {
        // Remove any existing notification
        const existing = document.getElementById('article-clipper-notification');
        if (existing) existing.remove();
        
        const notification = document.createElement('div');
        notification.id = 'article-clipper-notification';
        notification.textContent = message;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 24px;
            background: ${type === 'success' ? '#4CAF50' : '#f44336'};
            color: white;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            font-size: 14px;
            font-weight: 500;
            border-radius: 4px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 999999;
            animation: slideIn 0.3s ease-out;
        `;
        
        // Add animation keyframes
        if (!document.getElementById('article-clipper-styles')) {
            const style = document.createElement('style');
            style.id = 'article-clipper-styles';
            style.textContent = `
                @keyframes slideIn {
                    from { transform: translateX(100%); opacity: 0; }
                    to { transform: translateX(0); opacity: 1; }
                }
            `;
            document.head.appendChild(style);
        }
        
        document.body.appendChild(notification);
        
        // Auto-remove after 3 seconds
        setTimeout(() => {
            notification.style.opacity = '0';
            notification.style.transition = 'opacity 0.3s';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    }
    
    // ========== EXECUTE ==========
    
    try {
        const data = extractArticle();
        const formatted = formatForSheets(data);
        copyToClipboard(formatted);
        
        // Log extraction results for debugging
        console.log('Article Clipper extracted:', data);
    } catch (error) {
        showNotification('✗ Extraction failed: ' + error.message, 'error');
        console.error('Article Clipper error:', error);
    }
    
})();

/**
 * MINIFIED BOOKMARKLET (copy this as the bookmark URL):
 * 
 * javascript:(function(){function e(){return window.location.href}function t(){var e=document.querySelector('meta[property="og:title"]');if(e&&e.content)return e.content.trim();for(var t=document.querySelectorAll('script[type="application/ld+json"]'),n=0;n<t.length;n++)try{var r=JSON.parse(t[n].textContent),o=Array.isArray(r)?r:[r];for(var i of o)if(i&&i.headline)return i.headline.trim()}catch(e){}var a=document.querySelector("article h1, .article h1, main h1, h1");if(a)return a.textContent.trim();var c=document.querySelector("title");return c?c.textContent.trim().replace(/\s*[\|\-–—]\s*[^|\-–—]+$/,"").trim():""}function n(){for(var e=document.querySelectorAll('script[type="application/ld+json"]'),t=0;t<e.length;t++)try{var n=JSON.parse(e[t].textContent),o=Array.isArray(n)?n:[n];for(var i of o)if(i){var a=i.datePublished||i.dateCreated||i.publishedDate;if(a){var c="object"==typeof a?a["@value"]||a.value||String(a):String(a),l=new Date(c);if(!isNaN(l))return r(l)}}}catch(e){}for(var s=["article:published_time","pubdate","publishdate","date","datePublished","publish_date","article:published","DC.date.issued","sailthru.date"],u=0;u<s.length;u++){var d=document.querySelector('meta[property="'+s[u]+'"],meta[name="'+s[u]+'"],meta[itemprop="'+s[u]+'"]');if(d&&d.content){var f=new Date(d.content);if(!isNaN(f))return r(f)}}for(var p=document.querySelectorAll("time[datetime]"),m=0;m<p.length;m++){var g=new Date(p[m].getAttribute("datetime"));if(!isNaN(g))return r(g)}return""}function r(e){return e.getFullYear()+"-"+String(e.getMonth()+1).padStart(2,"0")+"-"+String(e.getDate()).padStart(2,"0")}function o(){for(var e=document.querySelectorAll('script[type="application/ld+json"]'),t=0;t<e.length;t++)try{var n=JSON.parse(e[t].textContent),r=Array.isArray(n)?n:[n];for(var o of r)if(o&&o.author){var a=o.author;if(Array.isArray(a)){var c=a.map(e=>"string"==typeof e?e:e.name||"").filter(Boolean);if(c.length)return c.join(", ")}else if("object"==typeof a&&a.name)return a.name.trim();else if("string"==typeof a)return a.trim()}}catch(e){}for(var l=['meta[name="author"]','meta[property="article:author"]','meta[name="byl"]','meta[name="sailthru.author"]'],s=0;s<l.length;s++){var u=document.querySelector(l[s]);if(u&&u.content)return i(u.content)}for(var d=['[rel="author"]',".byline",".author",".article-author","[itemprop=author]",".byline__name"],f=0;f<d.length;f++){var p=document.querySelector(d[f]);if(p){var m=p.textContent.trim();if(m&&m.length<200)return i(m)}}return""}function i(e){return e.replace(/^(By|Written by|Author:?)\s*/i,"").replace(/\s+/g," ").trim()}function a(){var e=document.body.cloneNode(!0);["script","style","nav","header","footer","aside",".sidebar",".comments",".related-articles",".advertisement",".ad"].forEach(t=>e.querySelectorAll(t).forEach(e=>e.remove()));for(var t=["article .article-body","article .story-body","[itemprop=articleBody]",".article-content",".story-content","article",'[role="main"]',"main"],n=0;n<t.length;n++){var r=e.querySelector(t[n]);if(r){var o=c(r.textContent);if(o.length>200)return o.substring(0,5e3)}}return c(e.textContent).substring(0,5e3)}function c(e){return e.replace(/[\t\n\r]+/g," ").replace(/\s+/g," ").trim()}function l(e,t){var n=document.createElement("div");n.id="acn",n.textContent=e,n.style.cssText="position:fixed;top:20px;right:20px;padding:12px 24px;background:"+("success"===t?"#4CAF50":"#f44336")+";color:#fff;font:500 14px system-ui;border-radius:4px;box-shadow:0 4px 12px rgba(0,0,0,.3);z-index:999999",document.body.appendChild(n),setTimeout(()=>n.remove(),3e3)}try{var s={url:e(),title:t(),publishDate:n(),author:o(),content:a()},u=[s.url,s.title,s.publishDate,s.author,s.content.replace(/\t/g," ").replace(/\n/g," ")].join("\t");navigator.clipboard?navigator.clipboard.writeText(u).then(()=>l("✓ Copied!","success")).catch(()=>l("✗ Copy failed","error")):l("✗ Clipboard unavailable","error"),console.log("Extracted:",s)}catch(e){l("✗ "+e.message,"error")}})();
 */
