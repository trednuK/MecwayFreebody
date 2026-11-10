# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# fb_docs.py
# The documentation in the panel (fb_gui, tab Documentation): the list of
# documents, a simple conversion from Markdown to HTML for the built-in browser
# element, and where a link in a document leads. After the documentation page
# of MecwayAsterBridge (bridge_docs.py), without its glossary.
#
# The conversion only knows what is used in docs/ and README.md: headings
# (#..####, with an id as GitHub makes it), paragraphs, lists (-, *, 1.) with
# indentation, tables (| a | b |), code blocks (```), inline code, bold,
# italic, links, images, horizontal rules and quotes. Everything else is text,
# HTML-escaped. No pip packages. IronPython 2.7.9 and Python 3, without Mecway.
#
# Images (![alt](images/x.png)) go into the page as a data URI: the page is
# loaded as about:blank, so a relative src would not resolve. Only a relative
# path to a PNG, JPEG or GIF file within docs/, up to MAX_IMAGE_BYTES; anything
# else shows its alt text in brackets, as does the text view without a browser.
# The same relative paths work on GitHub.

import base64
import io
import os
import re

# Order in the list: (file nl, file en, title nl, title en), relative to docs/
DOCS = [
    ("MecwayFreebody.md", "en/MecwayFreebody.md", u"Handleiding", u"User guide"),
    ("../README.md", "../README.md", u"Overzicht, installatie en gebruik (README, Engels)",
     u"Overview, installation and use (README)"),
]

# Texts of the documentation page, as fb_gui.T: (nl, en)
T = {
    "tab": (u"Documentatie", u"Documentation"),
    "not_found": (u"Document niet gevonden: {0} ({1})", u"Document not found: {0} ({1})"),
    "outside": (u"buiten de projectmap", u"outside the project folder"),
    "unreadable": (u"ontbreekt of is niet leesbaar", u"missing or not readable"),
    "not_shown": (u"Document niet getoond: {0}", u"Document not shown: {0}"),
    "link_failed": (u"Link niet geopend: {0}", u"Link not opened: {0}"),
    "link_none": (u"Deze link opent niet hier: alleen documenten (.md) en webadressen: {0}",
                  u"This link does not open here: only documents (.md) and web addresses: {0}"),
}

# Trademark notice at the bottom of the Documentation tab; the same text is in
# README.md and the two user guides.
TRADEMARK_NOTICE = (
    u"Mecway is een product van Mecway Ltd. Code_Aster is een handelsmerk van EDF. Dit "
    u"project is niet verbonden aan en niet goedgekeurd door Mecway Ltd of EDF.",
    u"Mecway is a product of Mecway Ltd. Code_Aster is a trademark of EDF. This project is "
    u"not affiliated with or endorsed by Mecway Ltd or EDF.")

_CSS = (u"body{font-family:Segoe UI,Arial,sans-serif;font-size:10pt;"
        u"margin:12px 18px;color:#1f2933;line-height:1.45}"
        u"h1{font-size:16pt;color:#202936}"
        u"h2{font-size:13pt;color:#202936;border-bottom:2px solid #e1e5ea;"
        u"padding-bottom:2px;margin-top:18px}"
        u"h3{font-size:11pt;color:#0078d4}h4{font-size:10pt}"
        u"a{color:#0078d4}"
        u"table{border-collapse:collapse;margin:8px 0}"
        u"td,th{border:1px solid #e1e5ea;padding:4px 8px;vertical-align:top}"
        u"th{background:#f7f9fb;text-align:left}"
        u"code{background:#eef2f6;padding:0 3px;font-family:Consolas,monospace}"
        u"pre{background:#f7f9fb;border-left:3px solid #0078d4;padding:8px;"
        u"font-family:Consolas,monospace;white-space:pre-wrap}"
        u"blockquote{border-left:3px solid #e1e5ea;margin:8px 0;padding-left:10px;"
        u"color:#69707a}"
        u"img{max-width:100%;height:auto;border:1px solid #e1e5ea}")

# Images in a document: types by extension, and the largest file taken in
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_PAGE_IMAGE_BYTES = 8 * 1024 * 1024
_IMAGE_TYPES = {u".png": u"image/png", u".jpg": u"image/jpeg", u".jpeg": u"image/jpeg",
                u".gif": u"image/gif"}


def tx(key, lang):
    nl, en = T[key]
    return nl if lang == "nl" else en


def docs_dir():
    """docs/ next to the folder Scripts/ this file is in."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "docs")


def root_dir():
    """The folder that holds Scripts/ and docs/: links may not leave it."""
    return os.path.dirname(docs_dir())


def doc_list(lang):
    """[(title, path relative to docs/)] in the language."""
    return [(en_t if lang != "nl" else nl_t, en if lang != "nl" else nl)
            for nl, en, nl_t, en_t in DOCS]


def same_doc(rel):
    """Index in doc_list() of the document rel, in either language, or None."""
    low = rel.lower()
    for k, row in enumerate(DOCS):
        if low in (row[0].lower(), row[1].lower()):
            return k
    return None


def _listed_name(rel):
    """rel as DOCS spells it when it is a listed document (a link may use other
    capitals; Windows does not mind), else rel."""
    for row in DOCS:
        for name in row[:2]:
            if name.lower() == rel.lower():
                return name
    return rel


# ==========================================
# MARKDOWN -> HTML
# ==========================================
def _esc(text):
    return (text.replace(u"&", u"&amp;").replace(u"<", u"&lt;")
            .replace(u">", u"&gt;").replace(u'"', u"&quot;"))


def _unesc(text):
    return (text.replace(u"&lt;", u"<").replace(u"&gt;", u">")
            .replace(u"&quot;", u'"').replace(u"&amp;", u"&"))


_CODE_RE = re.compile(u"`([^`]+)`")
_IMG_RE = re.compile(u"!\\[([^\\]]*)\\]\\(([^)\\s]+)\\)")
_LINK_RE = re.compile(u"\\[([^\\]]+)\\]\\(([^)\\s]+)\\)")
_BOLD_RE = re.compile(u"\\*\\*(.+?)\\*\\*")
_ITAL_RE = re.compile(u"(?<![\\w*])\\*([^*\\s][^*]*?)\\*(?![\\w*])")
_SCHEME_RE = re.compile(u"^([A-Za-z][A-Za-z0-9+.-]*):")


def _href_allowed(href):
    """Only web addresses, relative paths and anchors become a link."""
    m = _SCHEME_RE.match(href)
    return m is None or m.group(1).lower() in (u"http", u"https")


def _inline(text, image=None):
    """Inline markup: images, code, links, bold, italic. Code first as a
    placeholder, so that * in code is no italic and a link around code works
    ([`a.md`](a.md)). image(alt, src) gives the HTML of an image
    (_image_html); without it an image shows as its alt text in brackets."""
    keep = []

    def hold(html):
        keep.append(html)
        return u"\u0001{0}\u0001".format(len(keep) - 1)

    def picture(m):
        if image is None:
            return hold(u"[{0}]".format(_esc(m.group(1))))
        return hold(image(m.group(1), m.group(2)))
    text = text.replace(u"\u0001", u"")
    # code first: an image in code stays text
    text = _CODE_RE.sub(lambda m: hold(u"<code>{0}</code>".format(_esc(m.group(1)))), text)
    text = _IMG_RE.sub(picture, text)
    text = _esc(text)

    def link(m):
        # the href was escaped with the text: back, then escaped once for the
        # attribute, so a quote cannot end it
        href = _unesc(m.group(2))
        if not _href_allowed(href):
            return m.group(1)
        return u'<a href="{0}">{1}</a>'.format(_esc(href), m.group(1))
    text = _LINK_RE.sub(link, text)
    text = _BOLD_RE.sub(u"<b>\\1</b>", text)
    text = _ITAL_RE.sub(u"<i>\\1</i>", text)
    return re.sub(u"\u0001(\\d+)\u0001", lambda m: keep[int(m.group(1))], text)


_LIST_RE = re.compile(u"^(\\s*)([-*]|\\d+\\.)\\s+(.*)$")
_HEAD_RE = re.compile(u"^(#{1,4})\\s+(.*?)\\s*#*\\s*$")


def _cells(line):
    line = line.strip()
    if line.startswith(u"|"):
        line = line[1:]
    if line.endswith(u"|"):
        line = line[:-1]
    return [c.strip() for c in line.split(u"|")]


def slug(heading):
    """Anchor of a heading as GitHub makes it: lower case, without Markdown and
    punctuation, spaces -> '-' ('Cut by nodes on a plane' ->
    'cut-by-nodes-on-a-plane')."""
    text = _LINK_RE.sub(lambda m: m.group(1), heading)
    text = text.replace(u"`", u"").replace(u"*", u"").strip().lower()
    text = re.sub(u"[^\\w\\- ]", u"", text, flags=re.UNICODE)
    return text.replace(u" ", u"-")


def markdown_to_html(text, title=u"", rel=None):
    """HTML page from Markdown text (see the header of this file). rel: the
    path of the document relative to docs/, for its images; without it an
    image is its alt text. HTML comments (<!-- ... -->) are left out; a heading
    that comes again gets -1, -2 after its id, as on GitHub."""
    image = _image_html(rel) if rel is not None else None

    def inline(t):
        return _inline(t, image)
    text = re.sub(u"<!--.*?-->", u"", text, flags=re.DOTALL)
    lines = text.replace(u"\r\n", u"\n").split(u"\n")
    out = []
    para = []
    item = []           # text of the current list item (several lines)
    lists = []          # stack (indentation, 'ul'/'ol')
    ids = {}
    i = 0

    def flush_item():
        # through _inline in one go: bold or code across a line break
        if item:
            out.append(inline(u" ".join(item)))
            del item[:]

    def flush_para():
        flush_item()
        if para:
            out.append(u"<p>{0}</p>".format(inline(u" ".join(para))))
            del para[:]

    def close_lists(indent=-1):
        flush_item()
        while lists and lists[-1][0] > indent:
            out.append(u"</li></{0}>".format(lists.pop()[1]))

    def unique(anchor):
        n = ids.get(anchor, 0)
        ids[anchor] = n + 1
        return anchor if n == 0 else u"{0}-{1}".format(anchor, n)

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith(u"```"):
            flush_para()
            # an indented code block belongs to the current list item
            if not (lists and line.startswith(u" ")):
                close_lists()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(u"```"):
                code.append(lines[i])
                i += 1
            out.append(u"<pre>{0}</pre>".format(_esc(u"\n".join(code))))
            i += 1
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        m = _HEAD_RE.match(stripped)
        if m:
            flush_para()
            close_lists()
            n = len(m.group(1))
            out.append(u'<h{0} id="{2}">{1}</h{0}>'.format(
                n, inline(m.group(2)), _esc(unique(slug(m.group(2))))))
            i += 1
            continue
        if re.match(u"^(-{3,}|\\*{3,})$", stripped):
            flush_para()
            close_lists()
            out.append(u"<hr>")
            i += 1
            continue
        if stripped.startswith(u"|") and i + 1 < len(lines) and \
                re.match(u"^\\|?[\\s:|-]+\\|?$", lines[i + 1].strip()) and \
                u"-" in lines[i + 1]:
            flush_para()
            close_lists()
            out.append(u"<table><tr>{0}</tr>".format(u"".join(
                u"<th>{0}</th>".format(inline(c)) for c in _cells(line))))
            i += 2
            while i < len(lines) and lines[i].strip().startswith(u"|"):
                out.append(u"<tr>{0}</tr>".format(u"".join(
                    u"<td>{0}</td>".format(inline(c)) for c in _cells(lines[i]))))
                i += 1
            out.append(u"</table>")
            continue
        m = _LIST_RE.match(line)
        if m:
            flush_para()
            indent = len(m.group(1).replace(u"\t", u"    "))
            kind = u"ol" if m.group(2)[0].isdigit() else u"ul"
            if lists and indent < lists[-1][0]:
                close_lists(indent)
            if lists and indent == lists[-1][0] and kind != lists[-1][1]:
                close_lists(indent - 1)     # another kind of list at this level
            if not lists or indent > lists[-1][0]:
                out.append(u"<{0}><li>".format(kind))
                lists.append((indent, kind))
            else:
                out.append(u"</li><li>")
            item.append(m.group(3))
            i += 1
            continue
        if lists and line.startswith(u" "):
            item.append(stripped)       # continuation line of a list item
            i += 1
            continue
        if stripped.startswith(u">"):
            flush_para()
            close_lists()
            out.append(u"<blockquote>{0}</blockquote>".format(
                inline(stripped.lstrip(u"> "))))
            i += 1
            continue
        close_lists()
        para.append(stripped)
        i += 1
    flush_para()
    close_lists()
    return _page(title, u"\n".join(out))


def _page(title, body):
    return (u"<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
            u"<meta http-equiv=\"X-UA-Compatible\" content=\"IE=edge\">"
            u"<title>{0}</title><style>{1}</style></head><body>{2}"
            u"</body></html>").format(_esc(title), _CSS, body)


def _inside_root(path, folder=None):
    """The absolute, normalised path if it lies within folder (root_dir() by
    default), else None (compared without regard to case on Windows; the path
    keeps its case)."""
    full = os.path.abspath(path)
    root = os.path.normcase(os.path.abspath(folder or root_dir()))
    case = os.path.normcase(full)
    if case == root or not case.startswith(root.rstrip(os.sep) + os.sep):
        return None
    return full


def image_path(current, src):
    """The file of an image src in the document current (both relative to
    docs/), or None: only a relative path with forward slashes to a PNG, JPEG
    or GIF file within docs/, of at most MAX_IMAGE_BYTES. No scheme (data:,
    http:, file:), drive, absolute path, backslash, query or anchor."""
    if not src or _SCHEME_RE.match(src) or u":" in src or u"\\" in src or \
            src.startswith(u"/") or u"?" in src or u"#" in src or \
            any(ord(ch) < 32 for ch in src):
        return None
    if os.path.splitext(src)[1].lower() not in _IMAGE_TYPES:
        return None
    try:
        base = os.path.dirname(current.replace(u"/", os.sep))
        full = _inside_root(os.path.join(docs_dir(), base, src.replace(u"/", os.sep)),
                            docs_dir())
        if full is None or not os.path.isfile(full) or \
                os.path.getsize(full) > MAX_IMAGE_BYTES:
            return None
    except (IOError, OSError, ValueError):
        return None
    return full


def _image_html(current):
    """image(alt, src) for _inline in the document current: an img with the
    file as a data URI, or the alt text in brackets. A page takes images up to
    MAX_PAGE_IMAGE_BYTES together; after that, alt texts."""
    used = [0]

    def image(alt, src):
        path = image_path(current, src)
        data = None
        if path is not None:
            try:
                f = io.open(path, "rb")
                try:
                    data = f.read(MAX_IMAGE_BYTES + 1)
                finally:
                    f.close()
            except (IOError, OSError, ValueError):
                data = None
        if not data or len(data) > MAX_IMAGE_BYTES or \
                used[0] + len(data) > MAX_PAGE_IMAGE_BYTES:
            return u"[{0}]".format(_esc(alt))
        used[0] += len(data)
        kind = _IMAGE_TYPES[os.path.splitext(path)[1].lower()]
        return u'<img alt="{0}" src="data:{1};base64,{2}">'.format(
            _esc(alt), kind, base64.b64encode(data).decode("ascii"))
    return image


def doc_html(rel, lang):
    """HTML of a document (rel relative to docs/). A missing or unreadable
    file, or one outside the folder of the project, gives a page that says so."""
    path = os.path.join(docs_dir(), rel.replace(u"/", os.sep))
    # the page names the file from the project folder, not the whole path
    shown = os.path.normpath(os.path.join(u"docs", rel.replace(u"/", os.sep)))
    if _inside_root(path) is None:
        return _page(rel, u"<p>{0}</p>".format(_esc(tx("not_found", lang).format(
            shown, tx("outside", lang)))))
    try:
        f = io.open(path, encoding="utf-8")
        try:
            text = f.read()
        finally:
            f.close()
    except (IOError, OSError, ValueError):
        # a text of its own: the error of IronPython names the whole path
        return _page(rel, u"<p>{0}</p>".format(_esc(tx("not_found", lang).format(
            shown, tx("unreadable", lang)))))
    return markdown_to_html(text, rel, rel)


def page_text(html):
    """Plain text of a page of this module, for a viewer without a browser; an
    image is its alt text in brackets."""
    body = html[html.find(u"<body>"):] if u"<body>" in html else html
    body = re.sub(u'<img\\b[^>]*\\balt="([^"]*)"[^>]*>', u"[\\1]", body)
    body = re.sub(u"</(p|h[1-4]|li|tr|pre|table|blockquote)>|<br>|<hr>", u"\n", body)
    body = re.sub(u"</t[dh]>", u"  ", body)
    text = _unesc(re.sub(u"<[^>]+>", u"", body))
    text = re.sub(u"\n{3,}", u"\n\n", text)
    return text.strip().replace(u"\n", u"\r\n")


# ==========================================
# LINKS
# ==========================================
def href_from_url(url):
    """The href a link had: the browser element loads a page of DocumentText as
    about:blank, so a relative link arrives as about:<href> and an anchor as
    about:blank#<id>. Other addresses come back as they are."""
    if url.startswith(u"about:blank"):
        return url[len(u"about:blank"):]
    if url.startswith(u"about:"):
        return url[len(u"about:"):]
    return url


def resolve_link(current, href):
    """
    Target of a link in a document: ("anchor", None, id) in the same
    document, ("doc", path relative to docs/, anchor or None), ("web", url,
    None) for http and https, or (None, None, None). current is the path of
    the open document, relative to docs/. A document must be a .md file that
    exists within the project folder (README.md next to docs/ is
    '../README.md'); links to code, other files or other schemes do not open.
    """
    anchor = href.split(u"#", 1)[1] if u"#" in href else None
    path = href.split(u"#", 1)[0]
    scheme = _SCHEME_RE.match(path)
    if scheme is not None and len(scheme.group(1)) > 1:
        # a scheme (a single letter is a drive, refused below)
        if scheme.group(1).lower() in (u"http", u"https"):
            return "web", href, None
        return None, None, None
    if not path:
        return ("anchor", None, anchor) if anchor else (None, None, None)
    if path.startswith(u"/") or path.startswith(u"\\") or u":" in path or \
            not path.lower().endswith(u".md"):
        return None, None, None
    base = os.path.dirname(current.replace(u"/", os.sep))
    full = _inside_root(os.path.join(docs_dir(), base, path.replace(u"/", os.sep)))
    if full is None or not os.path.isfile(full):
        return None, None, None
    rel = os.path.relpath(full, os.path.abspath(docs_dir()))
    return "doc", _listed_name(rel.replace(os.sep, u"/")), anchor or None
