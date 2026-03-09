import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def create_session():
    """Create a requests.Session with automatic retry on server errors."""
    s = requests.Session()
    retry = Retry(
        total=1,
        backoff_factor=1,
        status_forcelist=[502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s
