from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService
from webdriver_manager.microsoft import EdgeChromiumDriverManager
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from urllib.parse import quote_plus
import logging
import time
import threading

logger = logging.getLogger("JARVIS.Browser")

class BrowserController:
    def __init__(self):
        self.driver = None
        self.driver_path = None
        logger.info("BrowserController initialized.")
        threading.Thread(target=self._prefetch_driver, daemon=True).start()

    def _prefetch_driver(self):
        try:
            logger.info("Prefetching Edge WebDriver...")
            self.driver_path = EdgeChromiumDriverManager().install()
            logger.info("Edge WebDriver prefetched.")
        except Exception as e:
            logger.error(f"Failed to prefetch Edge WebDriver: {e}")
            
    def _ensure_driver(self):
        if self.driver is not None:
            try:
                # Test if the connection is still alive (user might have closed it manually)
                _ = self.driver.window_handles
            except Exception:
                logger.warning("WebDriver session is dead. Re-initializing...")
                self.driver = None

        if self.driver is None:
            try:
                options = Options()
                options.add_experimental_option("detach", True)
                
                # Cache driver installation path to avoid downloading every time
                if not self.driver_path:
                    self.driver_path = EdgeChromiumDriverManager().install()
                
                service = EdgeService(self.driver_path)
                self.driver = webdriver.Edge(service=service, options=options)
                logger.info("Edge WebDriver initialized.")
            except Exception as e:
                logger.error(f"Failed to initialize Edge WebDriver: {e}")

    def normalize_url(self, url: str):
        if "." not in url:
            return f"https://www.google.com/search?q={quote_plus(url)}"

        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        return url

    def open_url(self, url: str):
        url = self.normalize_url(url)
            
        self._ensure_driver()
        if not self.driver:
            return
            
        try:
            # If current window is an empty tab, just navigate. Otherwise open new tab.
            if self.driver.current_url in ["data:,", "about:blank"]:
                self.driver.get(url)
            else:
                self.driver.switch_to.new_window('tab')
                self.driver.get(url)
            logger.info(f"Opened URL: {url}")
        except Exception as e:
            logger.error(f"Failed to open URL: {e}")

    def close_browser(self):
        try:
            if self.driver:
                self.driver.quit()
                self.driver = None
                logger.info("Browser closed.")
        except Exception as e:
            logger.error(f"Failed to close browser: {e}")

    def close_website(self, domain_or_title: str):
        """Closes a specific tab matching the domain or title"""
        if not self.driver:
            return False
            
        target = domain_or_title.lower()
        closed = False
        handles_to_close = []
        
        try:
            original_handles = self.driver.window_handles
            for handle in original_handles:
                self.driver.switch_to.window(handle)
                url = self.driver.current_url.lower()
                title = self.driver.title.lower()
                if target in url or target in title:
                    handles_to_close.append(handle)
                    
            for handle in handles_to_close:
                self.driver.switch_to.window(handle)
                self.driver.close()
                closed = True
                
            # Switch back to the last available window if any
            if self.driver.window_handles:
                self.driver.switch_to.window(self.driver.window_handles[-1])
            else:
                self.driver = None
                
            if closed:
                logger.info(f"Closed tab matching: {domain_or_title}")
            else:
                logger.warning(f"Could not find tab matching: {domain_or_title}")
        except Exception as e:
            logger.error(f"Failed to close website: {e}")
            
        return closed

    def search(self, query: str):
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        self.open_url(url)
        logger.info(f"Searched for: {query}")
        
    def search_youtube(self, query: str):
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        self.open_url(url)
        logger.info(f"Searched YouTube for: {query}")

    def play_youtube(self, query: str):
        self.search_youtube(query)
        time.sleep(3)
        try:
            videos = self.driver.find_elements(By.ID, "video-title")
            if videos:
                for video in videos:
                    if video.is_displayed():
                        video.click()
                        logger.info(f"Playing YouTube video for query: {query}")
                        break
        except Exception as e:
            logger.error(f"Failed to play YouTube video: {e}")

    def switch_tab(self, keyword: str):
        if not self.driver:
            return False
            
        keyword = keyword.lower()
        try:
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                if keyword in self.driver.title.lower() or keyword in self.driver.current_url.lower():
                    logger.info(f"Switched to tab matching: {keyword}")
                    return True
        except Exception as e:
            logger.error(f"Failed to switch tab: {e}")
        return False

    def list_tabs(self):
        tabs = []
        if not self.driver:
            return tabs
            
        try:
            current_handle = self.driver.current_window_handle
            for handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
                tabs.append({
                    "title": self.driver.title,
                    "url": self.driver.current_url
                })
            # Restore original tab
            self.driver.switch_to.window(current_handle)
        except Exception as e:
            logger.error(f"Failed to list tabs: {e}")
            
        return tabs

    def refresh_tab(self):
        if self.driver:
            try:
                self.driver.refresh()
                logger.info("Tab refreshed.")
            except Exception as e:
                logger.error(f"Failed to refresh tab: {e}")

    def go_back(self):
        if self.driver:
            try:
                self.driver.back()
                logger.info("Navigated back.")
            except Exception as e:
                logger.error(f"Failed to go back: {e}")

    def go_forward(self):
        if self.driver:
            try:
                self.driver.forward()
                logger.info("Navigated forward.")
            except Exception as e:
                logger.error(f"Failed to go forward: {e}")

    def download_file(self, url: str):
        logger.info(f"Attempting to download file from: {url}")
        self.open_url(url)

    def login_website(self, url: str):
        logger.info(f"Opening login page: {url}")
        self.open_url(url)

    def get_current_page_info(self):
        info = {"title": "", "url": ""}
        if self.driver:
            try:
                info["title"] = self.driver.title
                info["url"] = self.driver.current_url
            except Exception as e:
                logger.error(f"Failed to get current page info: {e}")
        return info

    def open_google(self):
        self.open_url("https://google.com")

    def open_youtube(self):
        self.open_url("https://youtube.com")

    def open_github(self):
        self.open_url("https://github.com")
