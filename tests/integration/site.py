"""
A small test website with the things the tool looks for, and switches that break it on purpose.

It lets the tests prove both halves of the promise: tests generated from a healthy site pass, and the SAME tests
fail when the site stops doing what it did during the scan.

Features: tabs, accordion + <details>, carousel, pagination, search + cards, a filter dropdown, a contact form with a
file upload, a popup with a form, login (user and admin), a public cart page that login lands on, a protected account
area with a harmless and a destructive form, an admin area, and a page that only exists inside a browser.

Switches (site.broken is a set of names):
    "js"          every inline script and onclick is removed: tabs, accordion, carousel and popup stop working
    "pagination"  the next-page link goes nowhere
    "submit500"   the popup form answers with a server error
    "a11y"        a NEW accessibility problem appears on the home page (an image without a description, a button without a name)

The healthy home page already has some accessibility problems (the search box, dropdown and form fields have no labels),
like many real sites. The tool should remember those and only fail on new ones.
"""

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

STYLE = "<style>button,summary{text-transform:uppercase}</style>"   # labels look like capitals on screen, as on many sites

HOME = """
<h1>Test Shop</h1>
<div role="tablist">
  <button role="tab" id="t1" aria-selected="true" aria-controls="p1" onclick="selectTab(1)">Alpha</button>
  <button role="tab" id="t2" aria-selected="false" aria-controls="p2" onclick="selectTab(2)">Beta</button>
</div>
<div id="p1" role="tabpanel">Alpha panel</div><div id="p2" role="tabpanel" hidden>Beta panel</div>

<h2>FAQ</h2>
<button id="faq1" aria-expanded="false" aria-controls="a1" onclick="toggle(this, 'a1')">What is shipping?</button>
<div id="a1" hidden>Fast.</div>
<details><summary>Returns policy</summary><p>30 days.</p></details>

<div class="carousel"><div class="slides">
  <div class="slide" id="s1">Slide one</div><div class="slide" id="s2" style="display:none">Slide two</div></div>
  <button aria-label="Next slide" onclick="nextSlide()">&rsaquo;</button></div>

<ul class="pagination"><li><a href="/">1</a></li><li><a href="__NEXT__" rel="next">Next</a></li></ul>
<p>__PAGE__</p>

<p id="flash" style="color:#cccccc;background:#ffffff">Welcome offer</p>
<input type="search" id="q" placeholder="Search rooms" oninput="filterCards()">
<select name="category"><option value="">All</option><option value="court">Courts</option><option value="studio">Studios</option></select>
<article class="card">Premium Court</article><article class="card">Deluxe Studio</article><article class="card">Standard Room</article>

<h2>To do</h2>
<input id="todo" placeholder="What needs to be done?" onkeydown="if (event.key === 'Enter') addTodo(this)">
<ul id="todos"></ul>
<input id="nick" placeholder="Your nickname">   <!-- a box outside any form that does nothing when Enter is pressed -->

<form action="/contact" method="post">
  <input name="full_name" required><input type="email" name="email" required>
  <input type="file" name="attachment" accept="image/*"><button type="submit">Send</button>
</form>

<button id="open-news" onclick="document.getElementById('dlg').style.display='block'">Subscribe</button>
<div id="dlg" role="dialog" aria-modal="true" style="display:none;border:1px solid #000;padding:10px">
  <button aria-label="Close" onclick="document.getElementById('dlg').style.display='none'">x</button>
  <form action="/subscribe" method="post"><input type="email" name="news_email" required><button type="submit">Join</button></form>
</div>

<script>
function selectTab(n) { for (const i of [1, 2]) { document.getElementById('t' + i).setAttribute('aria-selected', i == n);
                                                 document.getElementById('p' + i).hidden = i != n; } }
function toggle(b, id) { const open = b.getAttribute('aria-expanded') === 'true'; b.setAttribute('aria-expanded', !open);
                         document.getElementById(id).hidden = open; }
setTimeout(function () { document.getElementById('flash').style.color = '#000000'; }, 700);   // low contrast only for a moment
let cur = 1;
function nextSlide() { cur = cur == 1 ? 2 : 1; document.getElementById('s1').style.display = cur == 1 ? '' : 'none';
                       document.getElementById('s2').style.display = cur == 2 ? '' : 'none'; }
function addTodo(box) { const item = document.createElement('li'); item.textContent = box.value;
                        document.getElementById('todos').appendChild(item); box.value = ''; }
function filterCards() { const q = document.getElementById('q').value.toLowerCase();
  document.querySelectorAll('article.card').forEach(a => a.style.display = a.innerText.toLowerCase().includes(q) ? '' : 'none'); }
</script>
"""

LOGIN = '<h1>Login</h1><form action="/login" method="post"><input name="email" type="email"><input name="password" type="password"><button type="submit">Log in</button></form>'
ACCOUNT = '<h1>My account</h1><a href="/account/profile">Profile</a> <a href="/logout">Logout</a>'
PROFILE = """<h1>Profile</h1>
<form action="/account/profile" method="post"><input name="display_name" required><textarea name="bio"></textarea>
<select name="lang"><option value="">Language</option><option value="en">English</option></select><button type="submit">Save profile</button></form>
<form action="/account/delete" method="post"><input name="confirm" placeholder="type DELETE" required><button type="submit">Delete my account</button></form>"""
ADMIN = '<h1>Admin dashboard</h1><a href="/admin/products">Products</a> <a href="/logout">Logout</a>'
PRODUCTS = """<h1>Products</h1>
<form action="/admin/products" method="post"><input name="title" required><input type="number" name="price" min="1" required>
<input type="checkbox" name="active"><button type="submit">Add product</button></form>"""
THANKS = "<h1>Thank you</h1><p>Your submission has been received.</p>"

# A cookie wall: covers the whole page and swallows every click until it is answered. Answering sets a cookie, so the
# wall appears once per browser. (The handlers are onpointerup, so the "js" switch below does not take them away.)
WALL = """<div id="cookie-banner" class="cookie-consent" style="position:fixed;inset:0;z-index:9999;background:rgba(255,255,255,.96);padding:40px">
  <p>We use cookies to make this shop work. Please choose.</p>
  <button onpointerup="document.cookie='consent=1; path=/'; document.getElementById('cookie-banner').remove()">Accept all</button>
  <button onpointerup="document.cookie='consent=0; path=/'; document.getElementById('cookie-banner').remove()">Reject all</button>
  <button>Manage preferences</button></div>"""


def page(body: str, who=None) -> str:
    # Logged-in people get more links, as on a real site: the browser-only page, and their own profile / product pages.
    extra = {"user": ' <a href="/app">App</a> <a href="/account/profile">Profile</a>',
             "admin": ' <a href="/app">App</a> <a href="/admin/products">Products</a>'}.get(who, "")
    nav = f'<header><nav><a href="/">Home</a> <a href="/account">Account</a> <a href="/cart">Cart</a>{extra}</nav></header>'
    return f"<!doctype html><html><head><title>Test Shop</title>{STYLE}</head><body>{nav}<main>{body}</main></body></html>"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep test output quiet
        pass

    @property
    def site(self):
        return self.server.site

    def who(self):
        cookie = self.headers.get("Cookie", "")
        return "admin" if "who=admin" in cookie else "user" if "who=user" in cookie else None

    def send(self, body: str, status=200, headers=None, head_only=False):
        if "</body>" in body and "consent=" not in self.headers.get("Cookie", ""):   # nobody has answered the banner yet
            body = body.replace("</body>", WALL + "</body>")
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def redirect(self, to, headers=None):
        self.send("", 302, {"Location": to, **(headers or {})})

    def home(self):
        query = parse_qs(urlparse(self.path).query)
        html = HOME.replace("__PAGE__", "Second page of results" if query.get("page") == ["2"] else "First page of results")
        html = html.replace("__NEXT__", "#" if "pagination" in self.site.broken else "/?page=2")
        if "a11y" in self.site.broken:
            html = html.replace("</script>", "</script><img src='/missing.png'><button></button>")
        if "js" in self.site.broken:   # no scripts and no inline handlers: everything interactive goes dead
            start = html.index("<script>")
            html = html[:start].replace("onclick=", "data-off=").replace("oninput=", "data-off=").replace("onkeydown=", "data-off=")
        return page(html, self.who())

    def route(self, head_only=False):
        path, who = urlparse(self.path).path, self.who()
        if path == "/":
            return self.send(self.home(), head_only=head_only)
        if path == "/cart":
            return self.send(page("<h1>Your cart</h1><p>Empty</p>", who), head_only=head_only)
        if path == "/app":
            # a single-page app: the browser gets the page, a plain HTTP request does not
            status = 200 if self.headers.get("Sec-Fetch-Dest") == "document" else 404
            return self.send(page("<h1>App</h1>", who), status, head_only=head_only)
        if path == "/login":
            return self.send(page(LOGIN), head_only=head_only)
        if path == "/logout":
            return self.redirect("/login", {"Set-Cookie": "who=; Max-Age=0; Path=/"})
        if path.startswith("/admin"):
            if who != "admin":
                return self.redirect("/login")
            return self.send(page(PRODUCTS if path == "/admin/products" else ADMIN, who), head_only=head_only)
        if path.startswith("/account"):
            if who != "user":
                return self.redirect("/login")
            return self.send(page(PROFILE if path == "/account/profile" else ACCOUNT, who), head_only=head_only)
        self.send(page("<h1>Not found</h1>"), 404, head_only=head_only)

    def do_GET(self):
        self.route()

    def do_HEAD(self):
        self.route(head_only=True)

    def do_OPTIONS(self):
        self.send("", 204, {"Allow": "GET, HEAD, POST, OPTIONS"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        data = parse_qs(self.rfile.read(length).decode(errors="ignore"))
        path = urlparse(self.path).path
        if path == "/login":
            who = "admin" if (data.get("email") or [""])[0].startswith("admin") else "user"
            # users land on the cart, a page anyone can open: the tool must not treat it as a protected area
            return self.redirect("/admin" if who == "admin" else "/cart", {"Set-Cookie": f"who={who}; Path=/"})
        if path == "/subscribe" and "submit500" in self.site.broken:
            return self.send("<h1>Error</h1>", 500)
        self.send(page(THANKS))


class Site:
    """Starts the test website on a free port. `broken` can be changed while it runs."""

    def __init__(self):
        self.broken = set()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.site = self
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
