import pytest
import json
from unittest.mock import AsyncMock, patch
from app.modules import ai_judge

@pytest.fixture
def base_input():
    return ai_judge.JudgeInput(
        original_query="Когда вышел Python 3.12?",
        goal="Узнать точную дату релиза",
        context={"http://python.org": "Python 3.12 был выпущен 2 октября 2023 года."},
        current_iteration=1,
        max_iterations=3
    )

@pytest.mark.asyncio
async def test_scenario_success(base_input):
    """Test standard Complete scenario."""
    mock_json = json.dumps({
        "status": "complete",
        "final_answer": "Python 3.12 вышел 2 октября 2023 года.",
        "missing_info": None,
        "new_queries": []
    })
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_json
        
        result = await ai_judge.judge(base_input)
        
        assert result.status == "complete"
        assert "2 октября 2023" in result.final_answer
        assert result.new_queries == []
        mock_llm.assert_called_once()

@pytest.mark.asyncio
async def test_scenario_incomplete():
    """Test Incomplete scenario requesting more iterations."""
    inp = ai_judge.JudgeInput(
        original_query="Теория струн",
        goal="Понять последние изменения",
        context={"http://science.com": "Теория струн интересна, но новых данных нет."},
        current_iteration=1,
        max_iterations=3
    )
    
    mock_json = json.dumps({
        "status": "incomplete",
        "final_answer": None,
        "missing_info": "Не хватает информации о последних изменениях",
        "new_queries": ["новые открытия в теории струн 2023"]
    })
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_json
        
        result = await ai_judge.judge(inp)
        
        assert result.status == "incomplete"
        assert result.final_answer is None
        assert "изменениях" in result.missing_info
        assert len(result.new_queries) == 1

@pytest.mark.asyncio
async def test_scenario_last_chance_override():
    """Test forced override to 'complete' on final iteration if LLM disobeys."""
    inp = ai_judge.JudgeInput(
        original_query="Секретные планы инопланетян",
        goal="Найти документы Альфа Центавра",
        context={"http://news.com": "Тут пусто."},
        current_iteration=3, # Max iterations!
        max_iterations=3
    )
    
    # LLM stubbornly returns incomplete
    mock_json = json.dumps({
        "status": "incomplete",
        "final_answer": None,
        "missing_info": "Вообще ничего нет",
        "new_queries": ["снова ищем"]
    })
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = mock_json
        
        result = await ai_judge.judge(inp)
        
        # Guard logic should have overridden this to complete
        assert result.status == "complete"
        # Since LLM returned None for final_answer, the safeguard should inject a fallback string
        assert result.final_answer is not None
        assert "Вообще ничего нет" in result.final_answer  # missing info is often appended

@pytest.mark.asyncio
async def test_invalid_json_fallback(base_input):
    """Test regex fallback extraction for judge JSON parsing."""
    messy = "Here is the response:\n{\"status\": \"complete\", \"final_answer\": \"Answer!\"}\nHope this is good."
    
    with patch("app.core.llm.generate_json", new_callable=AsyncMock) as mock_llm:
        mock_llm.return_value = messy
        
        result = await ai_judge.judge(base_input)
        
        assert result.status == "complete"
        assert result.final_answer == "Answer!"
