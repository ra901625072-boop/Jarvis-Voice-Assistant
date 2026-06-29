import pytest
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

# Adjust sys.path to run tests from backend folder root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent import BrowserTools

@pytest.mark.anyio
async def test_decompose_query_simple():
    # Setup simple query which should not be decomposed
    tools = BrowserTools(security=None)
    queries = await tools._decompose_query("simple query")
    assert queries == ["simple query"]

@pytest.mark.anyio
async def test_decompose_query_compound():
    # Setup compound query and mock Gemini client response
    tools = BrowserTools(security=None)
    
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '["IPL 2026 winner", "IPL 2026 Purple Cap"]'
    mock_client.models.generate_content = MagicMock(return_value=mock_response)
    
    with patch("os.getenv", return_value="fake_api_key"), \
         patch("google.genai.Client", return_value=mock_client):
        queries = await tools._decompose_query("IPL 2026 winner and Purple Cap")
        assert len(queries) == 2
        assert "IPL 2026 winner" in queries
        assert "IPL 2026 Purple Cap" in queries

@pytest.mark.anyio
async def test_search_google_live_aggregates():
    tools = BrowserTools(security=None)
    
    # Mock decomposition to return multiple queries
    tools._decompose_query = AsyncMock(return_value=["query 1", "query 2"])
    
    # Mock single search execution
    tools._execute_single_search = AsyncMock(side_effect=lambda q, eng: f"results for {q}")
    
    res = await tools.search_google_live("compound query")
    assert "Decomposed Search Results" in res
    assert "### Search results for 'query 1':\nresults for query 1" in res
    assert "### Search results for 'query 2':\nresults for query 2" in res
