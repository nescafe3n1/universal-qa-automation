"""Live XHR / fetch traffic sniffing during the crawl."""

from urllib.parse import urlparse

from qa_generator.config import API_CONTENT_TYPES, API_URL_MARKERS, STATIC_EXTENSIONS
from qa_generator.utils import same_site


def is_api_request(req, res) -> bool:
    """Identify if an HTTP request/response qualifies as an API / dynamic data endpoint."""
    url = req.url.lower()

    if req.resource_type in ["fetch", "xhr"]:
        return True

    if req.headers.get("x-inertia") or req.headers.get("x-requested-with") == "XMLHttpRequest":
        return True

    if res:
        content_type = res.headers.get("content-type", "").lower()
        if any(ct in content_type for ct in API_CONTENT_TYPES):
            return True

    return any(marker in url for marker in API_URL_MARKERS)


def make_sniffer(scan_data: dict, base_url: str):
    """Return attach_sniffer(page, role_tag) which records same-site API calls into scan_data."""
    seen_endpoints = set()

    def attach_sniffer(page, role_tag="public"):
        def handle_response(res):
            try:
                req = res.request
                req_u = req.url
                parsed_u = urlparse(req_u)
                if parsed_u.path.lower().endswith(STATIC_EXTENSIONS):
                    return
                # Third-party calls (analytics, CDNs, chat widgets) are not the site under test.
                if not same_site(req_u, base_url):
                    return
                if not is_api_request(req, res):
                    return

                endpoint_key = f"{req.method}:{parsed_u.path}"
                if endpoint_key in seen_endpoints:
                    return
                seen_endpoints.add(endpoint_key)

                content_type = res.headers.get("content-type", "")
                sample_response = None
                try:
                    if "application/json" in content_type:
                        sample_response = res.json()
                except Exception:
                    pass

                sample_keys = []
                if isinstance(sample_response, dict):
                    sample_keys = list(sample_response.keys())[:6]
                elif isinstance(sample_response, list) and sample_response and isinstance(sample_response[0], dict):
                    sample_keys = list(sample_response[0].keys())[:6]

                req_headers = {k.lower(): v for k, v in req.headers.items()}
                scan_data["captured_apis"].append({
                    "url": req_u,
                    "method": req.method,
                    "status": res.status,
                    "path": parsed_u.path,
                    "query": parsed_u.query,
                    "role": role_tag,
                    "content_type": content_type,
                    "has_json": sample_response is not None,
                    "json_is_list": isinstance(sample_response, list),
                    "sample_keys": sample_keys,
                    # Token-authenticated calls can't be replayed without leaking the token into test files.
                    "needs_bearer_token": "authorization" in req_headers,
                })
            except Exception:
                pass

        page.on("response", handle_response)
        page.on("pageerror", lambda err: scan_data["page_errors"].append(str(err)))

    return attach_sniffer
