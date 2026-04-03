import os
os.environ["REDIS_URL"] = "redis://localhost:6379"

import pytest
import json
from unittest.mock import AsyncMock, patch
from app.modules import snippet_evaluator
from app.modules.execution_engine import SearchSnippet

@pytest.fixture
def mock_snippets():
    return [
        SearchSnippet(url=f"https://source{i}.com", title=f"Title {i}", snippet=f"Snippet {i}")
        for i in range(5)
    ]

@pytest.mark.asyncio
async def test_successful_evaluation(mock_snippets):
    """Test standard evaluation where LLM selects valid URLs."""
    expected_selected = ["https://source0.com", "https://source2.com"]
    mock_json = json.dumps({"selected_urls": expected_selected})
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_json
        
        result = await snippet_evaluator.evaluate_snippets("test goal", mock_snippets)
        
        assert len(result) == 2
        assert result == expected_selected
        mock_llm.assert_called_once()

@pytest.mark.asyncio
async def test_anti_hallucination(mock_snippets):
    """Test anti-hallucination logic by returning invented URLs."""
    selected_mix = ["https://source1.com", "https://hallucinated.com"]
    mock_json = json.dumps({"selected_urls": selected_mix})
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_json
        
        # Should drop the hallucinated URL
        result = await snippet_evaluator.evaluate_snippets("test goal", mock_snippets)
        
        assert len(result) == 1
        assert result == ["https://source1.com"]

@pytest.mark.asyncio
async def test_no_relevant_snippets(mock_snippets):
    """Test behavior when LLM finds no relevant snippets."""
    mock_json = json.dumps({"selected_urls": []})
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_json
        
        result = await snippet_evaluator.evaluate_snippets("test goal", mock_snippets)
        
        assert result == []

@pytest.mark.asyncio
async def test_invalid_llm_response(mock_snippets):
    """Test graceful handling of non-JSON or malformed LLM response."""
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = "invalid json response"
        
        result = await snippet_evaluator.evaluate_snippets("test goal", mock_snippets)
        
        assert result == []
