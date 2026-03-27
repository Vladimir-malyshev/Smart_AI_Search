import os
import pytest
import asyncio
from aioresponses import aioresponses
from app.modules import jina_reader

@pytest.mark.asyncio
async def test_successful_fetch():
    """Test standard Markdown extraction from a valid URL."""
    url = "https://habr.com/ru/post/12345/"
    markdown = "# Title\n\n" + ("This is a sample article content that needs to be long enough to pass the quality check of at least 100 characters. " * 2)
    
    with aioresponses() as m:
        m.get(f"https://r.jina.ai/{url}", status=200, body=markdown)
        
        results = await jina_reader.fetch_all([url])
        
        assert url in results
        assert results[url] == markdown

@pytest.mark.asyncio
async def test_truncation():
    """Test that content is truncated according to JINA_MAX_CHARS."""
    url = "https://long-article.com"
    # Create content larger than default 20,000 chars
    long_content = "X" * 25000
    
    with aioresponses() as m:
        m.get(f"https://r.jina.ai/{url}", status=200, body=long_content)
        
        results = await jina_reader.fetch_all([url])
        
        assert url in results
        content = results[url]
        assert len(content) <= jina_reader.JINA_MAX_CHARS + len(jina_reader.TRUNCATION_MARKER)
        assert content.endswith(jina_reader.TRUNCATION_MARKER)
        assert content.startswith("X" * jina_reader.JINA_MAX_CHARS)

@pytest.mark.asyncio
async def test_blocked_content():
    """Test detection of blocked content (Cloudflare, paywalls)."""
    url = "https://blocked.com"
    blocked_markdown = "Just a moment... Please wait while we check your browser."
    
    with aioresponses() as m:
        m.get(f"https://r.jina.ai/{url}", status=200, body=blocked_markdown)
        
        results = await jina_reader.fetch_all([url])
        
        assert url in results
        assert results[url] is None

@pytest.mark.asyncio
async def test_http_error_handling():
    """Test handling of 404 and 500 errors."""
    url_404 = "https://not-found.com"
    url_500 = "https://server-error.com"
    
    with aioresponses() as m:
        m.get(f"https://r.jina.ai/{url_404}", status=404)
        m.get(f"https://r.jina.ai/{url_500}", status=500)
        
        results = await jina_reader.fetch_all([url_404, url_500])
        
        assert results[url_404] is None
        assert results[url_500] is None

@pytest.mark.asyncio
async def test_timeout_handling():
    """Test handling of slow responses."""
    url = "https://slow-site.com"
    
    with aioresponses() as m:
        # aioresponses doesn't natively support delay in a simple way for timeouts easily without complex callback,
        # but we can simulate a timeout error by letting it fail or mocking the exception.
        m.get(f"https://r.jina.ai/{url}", exception=asyncio.TimeoutError())
        
        results = await jina_reader.fetch_all([url])
        
        assert results[url] is None
