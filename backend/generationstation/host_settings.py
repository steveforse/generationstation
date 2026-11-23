"""Settings the person changes from the app (stored in the host's database), with `.env` values as fallbacks."""
import urllib.error
import urllib.parse

SEARXNG = "searxng_url"


class SettingsInvalid(ValueError):
    pass


class HostSettings:
    def __init__(self, store, env_searxng_url=None, web=None):
        self.store = store
        self.env_searxng_url = (env_searxng_url or "").rstrip("/") or None
        self.web = web  # WebTools, for the search test

    def searxng_url(self):
        """The search service the chat uses: the saved address ("" turns search off), else the .env one."""
        saved = self.store.get_setting(SEARXNG) if hasattr(self.store, "get_setting") else None
        if saved is None:
            return self.env_searxng_url
        return saved or None

    def get(self):
        saved = self.store.get_setting(SEARXNG) if hasattr(self.store, "get_setting") else None
        source = "settings" if saved is not None else "environment" if self.env_searxng_url else "none"
        return {"searxng_url": self.searxng_url() or "", "searxng_source": source}

    def set(self, searxng_url):
        self.store.set_setting(SEARXNG, clean_url(searxng_url))
        return self.get()

    def test_search(self, searxng_url=None):
        """Run one real search: whether the address answers with JSON results, in plain words."""
        url = clean_url(searxng_url) if searxng_url is not None else self.searxng_url()
        if not url:
            return {"ok": False, "message": "No search address is set."}
        try:
            results = self.web.query("lighthouse", 5, base=url)
        except urllib.error.HTTPError as exc:
            hint = " SearXNG needs json in search.formats." if exc.code == 403 else ""
            return {"ok": False, "message": f"The service answered {exc.code}.{hint}"}
        except (urllib.error.URLError, OSError) as exc:
            return {"ok": False, "message": f"It did not answer ({getattr(exc, 'reason', exc)})."}
        except ValueError:
            return {"ok": False, "message": "It answered, but not with search results. Is json in SearXNG's search.formats?"}
        if not results:
            return {"ok": True, "message": "It answered, but found nothing for a test search. Check its search engines."}
        return {"ok": True, "message": f"Works: {len(results)} results for a test search, e.g. “{results[0].get('title', '')[:80]}”."}


def clean_url(value):
    """A search address as stored: "" (off) or an http(s) address without a query, trailing slash removed."""
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) > 300:
        raise SettingsInvalid("The address is too long.")
    parts = urllib.parse.urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise SettingsInvalid("Use an address starting with http:// or https://.")
    if parts.query or parts.fragment:
        raise SettingsInvalid("Use the service's main address, without ?… or #….")
    return value.rstrip("/")
