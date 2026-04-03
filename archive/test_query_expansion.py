import pytest
import json
from unittest.mock import AsyncMock, patch
from app.modules import query_expansion

@pytest.mark.asyncio
async def test_successful_expansion():
    """Test standard query expansion with valid JSON response."""
    mock_json = json.dumps({"queries": ["query1", "query2", "query3"]})
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_json
        
        result = await query_expansion.expand_query("test query", "test goal")
        
        assert len(result) == 3
        assert result == ["query1", "query2", "query3"]
        mock_llm.assert_called_once()

@pytest.mark.asyncio
async def test_markdown_cleaning():
    """Test handling JSON wrapped in markdown formatting."""
    raw_response = "```json\n" + json.dumps({"queries": ["q1", "q2"]}) + "\n```"
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = raw_response
        
        result = await query_expansion.expand_query("test", "goal")
        
        assert result == ["q1", "q2"]

@pytest.mark.asyncio
async def test_query_trimming():
    """Test trimming of queries that exceed the word count limit."""
    long_query = "word " * 15
    mock_json = json.dumps({"queries": [long_query.strip(), "short query"]})
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_json
        
        # Default limit is 10 words
        result = await query_expansion.expand_query("test", "goal")
        
        # First query should be trimmed to 10 words
        expected_long = " ".join(["word"] * 10)
        assert result[0] == expected_long
        assert result[1] == "short query"

@pytest.mark.asyncio
async def test_invalid_query_count():
    """Test response with fewer queries than allowed."""
    mock_json = json.dumps({"queries": ["just one query"]})
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_json
        
        with pytest.raises(ValueError, match="Количество запросов"):
            await query_expansion.expand_query("test", "goal")

@pytest.mark.asyncio
async def test_broken_json_recovery():
    """Test regex fallback for extracting JSON from conversational clutter."""
    messy_response = "Here are the queries you requested: {\"queries\": [\"fix1\", \"fix2\"]}. Hope this helps!"
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = messy_response
        
        result = await query_expansion.expand_query("test", "goal")
        
        assert result == ["fix1", "fix2"]
