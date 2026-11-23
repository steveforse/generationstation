"""The search address: saved from the app, falling back to .env, checked, and read fresh by the chat."""
import io
import json
import urllib.error

import pytest

from generationstation.chat_tools import WebTools
from generationstation.host_settings import HostSettings, SettingsInvalid


class Store:
    def __init__(self):
        self.values = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value):
        self.values[key] = value


def results(*titles):
    return io.BytesIO(json.dumps({"results": [{"title": t, "url": f"https://example.org/{i}"} for i, t in enumerate(titles)]}).encode())


def test_env_is_the_fallback_and_a_saved_address_wins():
    store = Store()
    settings = HostSettings(store, "http://env-searx:8080/")
    assert settings.get() == {"searxng_url": "http://env-searx:8080", "searxng_source": "environment"}
    assert settings.set("  http://searxng.example.lan/ ") == {"searxng_url": "http://searxng.example.lan", "searxng_source": "settings"}
    assert settings.searxng_url() == "http://searxng.example.lan"
    assert settings.set("")["searxng_source"] == "settings" and settings.searxng_url() is None  # saved empty turns it off
    assert HostSettings(Store()).get() == {"searxng_url": "", "searxng_source": "none"}


@pytest.mark.parametrize("bad", ["searxng.example.lan", "ftp://x", "http://x/search?q=1", "http://" + "a" * 300])
def test_bad_addresses_are_refused(bad):
    with pytest.raises(SettingsInvalid):
        HostSettings(Store()).set(bad)


def test_the_search_test_says_whether_it_works():
    asked = []
    def ok(request, timeout=None):
        asked.append(request.full_url)
        return results("Lighthouse - Wikipedia", "Fresnel lens")
    settings = HostSettings(Store(), web=WebTools(None, opener=ok))
    outcome = settings.test_search("http://searxng.example.lan")
    assert outcome["ok"] and outcome["message"].startswith("Works: 2 results") and "format=json" in asked[0]
    def forbidden(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)
    settings.web = WebTools(None, opener=forbidden)
    assert settings.test_search("http://searxng.example.lan") == {"ok": False, "message": "The service answered 403. SearXNG needs json in search.formats."}
    assert settings.test_search(None) == {"ok": False, "message": "No search address is set."}


def test_the_chat_reads_the_address_fresh():
    store = Store()
    settings = HostSettings(store)
    web = WebTools(settings.searxng_url, opener=lambda request, timeout=None: results("A"))
    assert [t["function"]["name"] for t in web.schemas()] == ["read_page"]
    settings.set("http://searxng.example.lan")
    assert [t["function"]["name"] for t in web.schemas()] == ["web_search", "read_page"]
