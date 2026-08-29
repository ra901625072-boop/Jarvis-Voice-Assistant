import pytest
import os
from modules.controls.app_controller import AppController
from modules.routing.task_classifier import TaskClassifier
from modules.skills.browser_automation_skill import BrowserAutomationSkill

class TestBrowserControlAndRouting:
    def test_app_controller_browser_alias_resolution(self):
        ctrl = AppController()
        
        browser_path = ctrl._find_app_path("browser")
        assert browser_path is not None
        assert browser_path.endswith(".exe")
        
        the_browser_path = ctrl._find_app_path("the browser")
        assert the_browser_path == browser_path

        web_browser_path = ctrl._find_app_path("web browser")
        assert web_browser_path == browser_path

    def test_task_classifier_open_browser_intents(self):
        report1 = TaskClassifier.classify("open browser")
        assert report1.primary_intent == "open_app"
        assert report1.suggested_tool == "open_application"
        assert report1.extracted_params.get("app_name") == "browser"

        report2 = TaskClassifier.classify("open the browser")
        assert report2.primary_intent == "open_app"
        assert report2.suggested_tool == "open_application"
        assert report2.extracted_params.get("app_name") == "browser"

        report3 = TaskClassifier.classify("launch browser")
        assert report3.extracted_params.get("app_name") == "browser"

    def test_task_classifier_search_on_browser_intent(self):
        report = TaskClassifier.classify("search for weather in mumbai on browser")
        assert report.primary_intent == "search_google"
        assert report.suggested_tool == "search_google"
        assert report.extracted_params.get("query") == "weather in mumbai"

    def test_browser_automation_skill_close_flag_default(self):
        skill = BrowserAutomationSkill()
        import inspect
        sig = inspect.signature(skill.automate_web_flow)
        assert "close_on_finish" in sig.parameters
        assert sig.parameters["close_on_finish"].default is False

    def test_browser_settings_and_profile_configuration(self):
        from config.settings import (
            JARVIS_BROWSER_TYPE,
            JARVIS_BROWSER_PROFILE_DIR,
            JARVIS_AUTO_OPEN_BROWSER,
            JARVIS_BROWSER_STARTUP_URL
        )
        assert JARVIS_BROWSER_TYPE in ("msedge", "chrome", "chromium")
        assert "browser_profile" in JARVIS_BROWSER_PROFILE_DIR
        assert isinstance(JARVIS_AUTO_OPEN_BROWSER, bool)
        assert JARVIS_BROWSER_STARTUP_URL.startswith("http")

    @pytest.mark.anyio
    async def test_browser_controller_ensure_separate_browser_mocked(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from modules.controls.browser_controller import BrowserController

        ctrl = BrowserController()
        with patch.object(ctrl, "_ensure_driver", new_callable=AsyncMock) as mock_ensure:
            with patch.object(ctrl, "_focus_browser_window") as mock_focus:
                # Mock a dummy context and page
                mock_page = AsyncMock()
                mock_page.is_closed = MagicMock(return_value=False)
                mock_page.url = "about:blank"
                mock_context = AsyncMock()
                mock_context.pages = [mock_page]
                ctrl.context = mock_context
                ctrl.page = mock_page

                res = await ctrl.ensure_separate_browser(start_url="http://localhost:8000")
                assert res is True
                mock_ensure.assert_awaited_once()
                mock_page.goto.assert_awaited_once_with("http://localhost:8000", wait_until="domcontentloaded", timeout=15000)
                mock_page.bring_to_front.assert_awaited_once()
                mock_focus.assert_called_once()

    @pytest.mark.anyio
    async def test_browser_controller_open_url_executes_in_separate_browser(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from modules.controls.browser_controller import BrowserController

        ctrl = BrowserController()
        with patch.object(ctrl, "_ensure_driver", new_callable=AsyncMock) as mock_ensure:
            with patch.object(ctrl, "_focus_browser_window") as mock_focus:
                mock_page = AsyncMock()
                mock_page.is_closed = MagicMock(return_value=False)
                mock_page.url = "about:blank"
                mock_context = AsyncMock()
                mock_context.pages = [mock_page]
                ctrl.context = mock_context
                ctrl.page = mock_page

                res = await ctrl.open_url("https://github.com")
                assert "Successfully opened https://github.com in separate browser." in res
                mock_page.goto.assert_awaited_once_with("https://github.com", wait_until="domcontentloaded", timeout=15000)
                mock_page.bring_to_front.assert_awaited_once()
                mock_focus.assert_called_once()

    @pytest.mark.anyio
    async def test_browser_tools_open_separate_browser(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from tools.builtin.browser.tool import BrowserTools

        mock_security = MagicMock()
        tools = BrowserTools(security=mock_security)
        
        with patch.object(tools.browser_ctrl, "ensure_separate_browser", new_callable=AsyncMock) as mock_ensure:
            mock_ensure.return_value = True
            res = await tools.open_separate_browser()
            assert "JARVIS separate dedicated browser is opened" in res
            mock_ensure.assert_awaited_once_with(None)

    def test_browser_controller_is_server_tab_detection(self):
        from modules.controls.browser_controller import BrowserController
        ctrl = BrowserController()
        
        assert ctrl.is_server_tab("http://localhost:8000") is True
        assert ctrl.is_server_tab("http://localhost:8000/") is True
        assert ctrl.is_server_tab("http://127.0.0.1:8000") is True
        assert ctrl.is_server_tab("http://192.168.1.100:8000/api/docs") is True
        assert ctrl.is_server_tab("https://www.google.com") is False
        assert ctrl.is_server_tab("https://en.wikipedia.org/wiki/Black_hole") is False

    @pytest.mark.anyio
    async def test_browser_controller_never_navigates_over_server_tab(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from modules.controls.browser_controller import BrowserController

        ctrl = BrowserController()
        with patch.object(ctrl, "_ensure_driver", new_callable=AsyncMock):
            with patch.object(ctrl, "_focus_browser_window"):
                # Server page
                server_page = AsyncMock()
                server_page.is_closed = MagicMock(return_value=False)
                server_page.url = "http://localhost:8000"

                # Research page to be created
                research_page = AsyncMock()
                research_page.is_closed = MagicMock(return_value=False)
                research_page.url = "about:blank"

                mock_context = AsyncMock()
                mock_context.pages = [server_page]
                mock_context.new_page = AsyncMock(return_value=research_page)

                ctrl.context = mock_context
                ctrl.page = server_page

                # Searching or opening a URL for research (e.g. black hole)
                res = await ctrl.open_url("https://www.google.com/search?q=black+hole")
                assert "Successfully opened" in res
                
                # Server page MUST NOT be navigated
                server_page.goto.assert_not_called()
                
                # Context MUST have created a new tab for research
                mock_context.new_page.assert_awaited_once()
                research_page.goto.assert_awaited_once_with(
                    "https://www.google.com/search?q=black+hole",
                    wait_until="domcontentloaded",
                    timeout=15000
                )

    @pytest.mark.anyio
    async def test_browser_controller_close_website_protects_server_tab(self):
        from unittest.mock import AsyncMock, MagicMock, patch
        from modules.controls.browser_controller import BrowserController

        ctrl = BrowserController()
        with patch.object(ctrl, "_ensure_driver", new_callable=AsyncMock):
            server_page = AsyncMock()
            server_page.is_closed = MagicMock(return_value=False)
            server_page.url = "http://localhost:8000"
            server_page.title = AsyncMock(return_value="JARVIS - Multi-Agent Control Center")

            other_page = AsyncMock()
            other_page.is_closed = MagicMock(return_value=False)
            other_page.url = "https://www.google.com/search?q=black+hole"
            other_page.title = AsyncMock(return_value="black hole - Google Search")

            mock_context = AsyncMock()
            mock_context.pages = [server_page, other_page]
            ctrl.context = mock_context
            ctrl.page = other_page

            with patch.object(ctrl, "_return_pooled_page", new_callable=AsyncMock) as mock_return:
                # Attempt to close localhost/server
                res = await ctrl.close_website("localhost")
                # Server tab was protected, not returned/closed
                mock_return.assert_not_called()
                assert res is False

                # Attempt to close Google research tab
                res_google = await ctrl.close_website("google")
                mock_return.assert_awaited_once_with(other_page)
                assert res_google is True


