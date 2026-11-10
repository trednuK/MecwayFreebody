# -*- coding: utf-8 -*-
# Copyright (C) 2026 trednuK
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# test_gui_docs.py
# The documentation tab without Windows Forms (fb_docs): the conversion of
# what docs/ and README.md use, HTML escapes, anchors, where a link leads, a
# missing document, and every link in the real documents. Run from
# test_gui_logic.main(), in CPython 3 and in Mecway's IronPython.

import base64
import io
import os
import re
import shutil
import tempfile

import test_gui_support as sup  # noqa: F401  (puts Scripts/ on the path)

import fb_docs

_IDS = re.compile(u'<h[1-4] id="([^"]*)"')
_MD_LINK = re.compile(u"(?<!!)\\[[^\\]]+\\]\\(([^)\\s]+)\\)")
_MD_IMAGE = re.compile(u"!\\[[^\\]]*\\]\\(([^)\\s]+)\\)")


def _body(html):
    return html[html.find(u"<body>") + len(u"<body>"):html.rfind(u"</body>")]


def _read(rel):
    with io.open(os.path.join(fb_docs.docs_dir(), rel.replace(u"/", os.sep)),
                 encoding="utf-8") as f:
        return f.read()


def test_docs_headings(r):
    html = fb_docs.markdown_to_html(u"# Main title\n\n## Cut by *nodes* on a plane\n\n"
                                    u"### 4.4 `x`-rule, again!\n\n## Limits\n\n## Limits ##\n",
                                    u"t")
    ids = _IDS.findall(html)
    r.check("docs: heading ids as GitHub",
            ids == [u"main-title", u"cut-by-nodes-on-a-plane", u"44-x-rule-again", u"limits",
                    u"limits-1"], ids)
    r.check("docs: heading markup", u"<h2 id=\"cut-by-nodes-on-a-plane\">Cut by <i>nodes</i> "
            u"on a plane</h2>" in html, html)
    r.check("docs: closing hashes dropped", u"Limits ##" not in html)
    r.check("docs: title escaped", u"<title>t</title>" in html)
    r.check("docs: slug of a link", fb_docs.slug(u"See [the guide](a.md)") == u"see-the-guide")
    r.check("docs: slug keeps accents", fb_docs.slug(u"Één snede") == u"één-snede",
            fb_docs.slug(u"Één snede"))


def test_docs_lists(r):
    md = (u"- one\n  carried on\n- two\n  - inner **bold\n    across** lines\n- three\n\n"
          u"1. first\n2. second\n\nafter\n")
    body = _body(fb_docs.markdown_to_html(md)).replace(u"\n", u"")
    r.check("docs: list with continuation", u"<ul><li>one carried on</li><li>two" in body, body)
    r.check("docs: nested list", u"<ul><li>inner <b>bold across</b> lines</li></ul>" in body,
            body)
    r.check("docs: back to the outer list", u"</ul></li><li>three</li></ul>" in body, body)
    r.check("docs: numbered list", u"<ol><li>first</li><li>second</li></ol>" in body, body)
    r.check("docs: paragraph after the lists", body.endswith(u"<p>after</p>"), body)


def test_docs_table_code(r):
    md = (u"| Case | Code |\n|---|:-:|\n| a < b & c | `x*y` |\n| **bold** | *it* |\n\n"
          u"```python\nif a < b and c > d: x = \"*q*\" & 1\n```\n")
    body = _body(fb_docs.markdown_to_html(md))
    r.check("docs: table head", u"<table><tr><th>Case</th><th>Code</th></tr>" in body, body)
    r.check("docs: table cells escaped",
            u"<tr><td>a &lt; b &amp; c</td><td><code>x*y</code></td></tr>" in body, body)
    r.check("docs: markup in cells", u"<td><b>bold</b></td><td><i>it</i></td>" in body, body)
    r.check("docs: code block escaped, no markup",
            u"<pre>if a &lt; b and c &gt; d: x = &quot;*q*&quot; &amp; 1</pre>" in body, body)


def test_docs_inline(r):
    inline = fb_docs._inline
    r.check("docs: star in code is no italic",
            inline(u"`*a*` and *b*") == u"<code>*a*</code> and <i>b</i>", inline(u"`*a*` and *b*"))
    r.check("docs: link around code",
            inline(u"[`a.md`](a.md)") == u'<a href="a.md"><code>a.md</code></a>',
            inline(u"[`a.md`](a.md)"))
    r.check("docs: bold around code", inline(u"**`x`-rule**") == u"<b><code>x</code>-rule</b>")
    out = inline(u'[say "x"](a.md"b) <script>&')
    r.check("docs: quote cannot leave the attribute",
            out == u'<a href="a.md&quot;b">say &quot;x&quot;</a> &lt;script&gt;&amp;', out)
    r.check("docs: other schemes are text",
            inline(u"[j](javascript:alert) [f](file:///c:/x.md) [m](mailto:a)") == u"j f m",
            inline(u"[j](javascript:alert) [f](file:///c:/x.md) [m](mailto:a)"))
    r.check("docs: web and anchor links stay",
            inline(u"[w](https://x.org/a?b=1&c=2) [h](#top)") ==
            u'<a href="https://x.org/a?b=1&amp;c=2">w</a> <a href="#top">h</a>',
            inline(u"[w](https://x.org/a?b=1&c=2) [h](#top)"))
    r.check("docs: image is its alt text", inline(u"![a plot](img/x.png)") == u"[a plot]")
    r.check("docs: an image in code stays code",
            inline(u"`![a](x.png)`") == u"<code>![a](x.png)</code>", inline(u"`![a](x.png)`"))
    r.check("docs: a multiplication is no italic", inline(u"t x L and a * b * c") ==
            u"t x L and a * b * c", inline(u"t x L and a * b * c"))


# A PNG of 1 x 1 pixel
_PNG = base64.b64decode(u"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _fake_docs():
    """A folder docs/ of its own, with images/a.png, images/b.svg, en/ and a PNG
    beside it (outside docs/); fb_docs.docs_dir points there until restored."""
    top = tempfile.mkdtemp(prefix="fb_docs_")
    docs = os.path.join(top, "docs")
    for folder in (os.path.join(docs, "images"), os.path.join(docs, "en")):
        os.makedirs(folder)
    for path in (os.path.join(docs, "images", "a.png"), os.path.join(docs, "images", "b.svg"),
                 os.path.join(docs, "images", "c.JPG"), os.path.join(top, "out.png")):
        with io.open(path, "wb") as f:
            f.write(_PNG)
    return top, docs


def test_docs_images(r):
    top, docs = _fake_docs()
    real_dir, real_max = fb_docs.docs_dir, fb_docs.MAX_IMAGE_BYTES
    fb_docs.docs_dir = lambda: docs
    try:
        want = u'<img alt="x" src="data:image/png;base64,{0}">'.format(
            base64.b64encode(_PNG).decode("ascii"))
        image = fb_docs._image_html(u"MecwayFreebody.md")
        r.check("docs: image as a data URI", image(u"x", u"images/a.png") == want,
                image(u"x", u"images/a.png")[:80])
        r.check("docs: image from en/ one folder up",
                fb_docs._image_html(u"en/MecwayFreebody.md")(u"x", u"../images/a.png") == want)
        r.check("docs: jpg in capitals", u"data:image/jpeg;base64," in
                image(u"x", u"images/c.JPG"))
        out = image(u'say "a" <b>', u"images/a.png")
        r.check("docs: alt escaped once, a quote cannot leave the attribute",
                out.startswith(u'<img alt="say &quot;a&quot; &lt;b&gt;" src='), out[:60])
        for src in (u"images/b.svg", u"images/none.png", u"../out.png", u"../../out.png",
                    u"images/../../out.png", u"/images/a.png", u"images\\a.png",
                    u"C:/images/a.png", u"file:///c:/x.png", u"http://x.org/a.png",
                    u"data:image/png;base64,AAAA", u"images/a.png?x", u"images/a.png#x",
                    u"images/a\u0000.png", u"images/a.png\u0000", u"images", u""):
            got = image(u"alt <x>", src)
            r.check(u"docs: image refused: {0}".format(src),
                    got == u"[alt &lt;x&gt;]" and fb_docs.image_path(u"MecwayFreebody.md", src)
                    is None, got[:60])
        fb_docs.MAX_IMAGE_BYTES = len(_PNG) - 1
        r.check("docs: image larger than the limit refused",
                image(u"x", u"images/a.png") == u"[x]")
        fb_docs.MAX_IMAGE_BYTES = real_max
        real_page = fb_docs.MAX_PAGE_IMAGE_BYTES
        fb_docs.MAX_PAGE_IMAGE_BYTES = 2 * len(_PNG)
        try:
            page = fb_docs._image_html(u"MecwayFreebody.md")
            three = [page(u"x", u"images/a.png") for _ in range(3)]
        finally:
            fb_docs.MAX_PAGE_IMAGE_BYTES = real_page
        r.check("docs: images of a page up to the page limit",
                three[0] == want and three[1] == want and three[2] == u"[x]",
                [t[:20] for t in three])
        html =fb_docs.markdown_to_html(u"Text\n\n![The panel](images/a.png)\n\n| a |\n|---|\n"
                                        u"| ![c](images/a.png) |\n", u"t", u"MecwayFreebody.md")
        r.check("docs: image in a paragraph and a cell",
                html.count(u'<img alt="') == 2 and u"<p><img alt=\"The panel\"" in html)
        r.check("docs: without a document no image",
                u"<img" not in fb_docs.markdown_to_html(u"![a](images/a.png)"))
        text = fb_docs.page_text(html)
        r.check("docs: text view shows the alt text", u"[The panel]" in text and
                u"base64" not in text and u"<" not in text, text)
    finally:
        fb_docs.docs_dir, fb_docs.MAX_IMAGE_BYTES = real_dir, real_max
        shutil.rmtree(top, ignore_errors=True)


def _image_links(rel):
    return _MD_IMAGE.findall(_read(rel))


def test_docs_real_images(r):
    """Every image in the guides and the README exists within docs/ and goes
    in; a guide uses the images of its own language, and both guides show
    every window image."""
    folder = os.path.join(fb_docs.docs_dir(), "images")
    names = sorted(n for n in os.listdir(folder) if n.startswith("window_")) \
        if os.path.isdir(folder) else []
    for rel, lang in ((u"MecwayFreebody.md", u"nl"), (u"en/MecwayFreebody.md", u"en"),
                      (u"../README.md", None)):
        html = fb_docs.doc_html(rel, "en")
        links = _image_links(rel)
        r.check(u"docs: every image of {0} goes in".format(rel),
                html.count(u'<img alt="') == len(links) and
                html.count(u"base64,") == len(links), (len(links), html.count(u"<img")))
        for src in links:
            r.check(u"docs: image {0} in {1}".format(src, rel),
                    fb_docs.image_path(rel, src) is not None)
            if lang:
                r.check(u"docs: image {0} in the language of {1}".format(src, rel),
                        src.endswith(u"_{0}.png".format(lang)))
        if lang:
            shown = set(os.path.basename(s) for s in links)
            missing = [n for n in names if n.endswith(u"_{0}.png".format(lang)) and
                       n not in shown]
            r.check(u"docs: {0} shows every window image".format(rel), not missing, missing)
    r.check("docs: window images in both languages",
            sorted(n.replace(u"_nl.", u"_en.") for n in names if u"_nl." in n) ==
            sorted(n for n in names if u"_en." in n), names)


def _figure_tables(rel):
    """{image name without _nl/_en.png: numbers in the first column of the
    first table after it} for the window images of a guide."""
    lines = _read(rel).replace(u"\r\n", u"\n").split(u"\n")
    out = {}
    current = None
    for i, line in enumerate(lines):
        m = re.match(u"^!\\[[^\\]]*\\]\\(([^)\\s]+)\\)\\s*$", line.strip())
        if m:
            name = os.path.basename(m.group(1))
            current = re.sub(u"_(nl|en)\\.png$", u"", name) if name.startswith(u"window_") \
                else None
            continue
        if current and line.startswith(u"|") and i + 1 < len(lines) and \
                lines[i + 1].startswith(u"|--"):
            numbers = []
            for row in lines[i + 2:]:
                if not row.startswith(u"|"):
                    break
                numbers.append(row.split(u"|")[1].strip())
            out[current] = numbers
            current = None
    return out


def test_docs_figure_tables(r):
    """The table under each image of the panel has the numbers of its markers
    (tools/fb_marks.py), 1 to n in order, the same in both languages."""
    import sys
    tools = os.path.join(os.path.dirname(fb_docs.docs_dir()), "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import fb_marks
    tables = {}
    for rel in (u"MecwayFreebody.md", u"en/MecwayFreebody.md"):
        tables[rel] = _figure_tables(rel)
        r.check(u"docs: every image of the panel has a table in " + rel,
                sorted(tables[rel]) == sorted(fb_marks.FIGURES), sorted(tables[rel]))
        for name, keys in sorted(fb_marks.FIGURES.items()):
            want = [u"{0}".format(k + 1) for k in range(len(keys))]
            got = tables[rel].get(name)
            r.check(u"docs: numbers of {0} in {1}".format(name, rel), got == want, got)
    r.check("docs: markers have distinct parts",
            all(len(set(k)) == len(k) for k in fb_marks.FIGURES.values()))


def test_docs_misc(r):
    body = _body(fb_docs.markdown_to_html(u"a <!-- hidden\nline --> b\n\n---\n\n> quote *q*\n"))
    r.check("docs: comment left out", u"hidden" not in body and u"<p>a  b</p>" in body, body)
    r.check("docs: rule", u"<hr>" in body)
    r.check("docs: quote", u"<blockquote>quote <i>q</i></blockquote>" in body, body)
    text = fb_docs.page_text(fb_docs.markdown_to_html(u"# T\n\n| a | b |\n|---|---|\n| 1 < 2 | 3 |\n"))
    r.check("docs: page text without tags", u"<" not in text.replace(u"1 < 2", u"") and
            u"1 < 2" in text and text.startswith(u"T"), text)


def test_docs_list_and_files(r):
    for lang in ("nl", "en"):
        items = fb_docs.doc_list(lang)
        r.check("docs: list {0}".format(lang), len(items) == len(fb_docs.DOCS) and
                items[0][1] == (u"MecwayFreebody.md" if lang == "nl" else u"en/MecwayFreebody.md"),
                items)
        for title, rel in items:
            path = os.path.join(fb_docs.docs_dir(), rel.replace(u"/", os.sep))
            r.check("docs: file exists " + rel, os.path.isfile(path), path)
    r.check("docs: same document in the other language",
            fb_docs.same_doc(u"en/MecwayFreebody.md") == 0 and
            fb_docs.same_doc(u"MecwayFreebody.md") == 0 and
            fb_docs.same_doc(u"../README.md") == 1 and fb_docs.same_doc(u"design/x.md") is None)
    r.check("docs: docs next to Scripts",
            os.path.basename(fb_docs.docs_dir()) == "docs" and
            os.path.isdir(os.path.join(fb_docs.root_dir(), "Scripts")))
    fields = re.compile(r"\{(\d*)\}")
    for key, pair in fb_docs.T.items():
        r.check("docs: both languages " + key, len(pair) == 2 and all(pair), pair)
        r.check("docs: same fields " + key,
                sorted(fields.findall(pair[0])) == sorted(fields.findall(pair[1])), pair)
    r.check("docs: trademark notice in both languages",
            len(fb_docs.TRADEMARK_NOTICE) == 2 and u"Mecway Ltd" in fb_docs.TRADEMARK_NOTICE[0]
            and u"EDF" in fb_docs.TRADEMARK_NOTICE[1])


def test_docs_missing(r):
    for rel in (u"nothing_here.md", u"../../outside.md", u"../Scripts/fb_docs.py.md"):
        try:
            html = fb_docs.doc_html(rel, "nl")
            r.check("docs: missing document says so " + rel,
                    u"Document niet gevonden" in html and u"<body>" in html, html[-200:])
        except Exception as e:
            r.check("docs: missing document says so " + rel, False, e)
    html = fb_docs.doc_html(u"../../outside.md", "en")
    r.check("docs: outside the project is refused", u"outside the project folder" in html,
            html[-200:])
    html = fb_docs.doc_html(u"nothing_here.md", "en")
    r.check("docs: the message names no whole path",
            fb_docs.root_dir() not in html and os.path.join(u"docs", u"nothing_here.md") in html,
            html[-200:])
    r.check("docs: a link in other capitals finds the listed name",
            fb_docs.resolve_link(u"../README.md", u"docs/EN/mecwayfreebody.md") ==
            ("doc", u"en/MecwayFreebody.md", None) and
            fb_docs.same_doc(u"EN/MECWAYFREEBODY.MD") == 0)


def test_docs_links(r):
    res = fb_docs.resolve_link
    cases = [
        ((u"MecwayFreebody.md", u"#grenzen"), ("anchor", None, u"grenzen")),
        ((u"MecwayFreebody.md", u"#"), (None, None, None)),
        ((u"../README.md", u"docs/en/MecwayFreebody.md"), ("doc", u"en/MecwayFreebody.md", None)),
        ((u"../README.md", u"docs/MecwayFreebody.md#limits"),
         ("doc", u"MecwayFreebody.md", u"limits")),
        ((u"en/MecwayFreebody.md", u"../../README.md"), ("doc", u"../README.md", None)),
        ((u"en/MecwayFreebody.md", u"../MecwayFreebody.md"), ("doc", u"MecwayFreebody.md", None)),
        ((u"../README.md", u"docs/design/contract.md"), ("doc", u"design/contract.md", None)),
        ((u"../README.md", u"LICENSE"), (None, None, None)),
        ((u"../README.md", u"Scripts/fb_docs.py"), (None, None, None)),
        ((u"../README.md", u"docs/none.md"), (None, None, None)),
        ((u"../README.md", u"../outside.md"), (None, None, None)),
        ((u"MecwayFreebody.md", u"../../../../x.md"), (None, None, None)),
        ((u"../README.md", u"C:/x.md"), (None, None, None)),
        ((u"../README.md", u"/x.md"), (None, None, None)),
        ((u"../README.md", u"\\\\server\\share\\x.md"), (None, None, None)),
        ((u"../README.md", u"file:///c:/x.md"), (None, None, None)),
        ((u"../README.md", u"javascript:alert(1)"), (None, None, None)),
        ((u"../README.md", u"mailto:a"), (None, None, None)),
        ((u"../README.md", u"https://mecway.com"), ("web", u"https://mecway.com", None)),
        ((u"../README.md", u"http://x.org/a#b"), ("web", u"http://x.org/a#b", None)),
    ]
    for (current, href), want in cases:
        got = res(current, href)
        r.check(u"docs: link {0} from {1}".format(href, current), got == want, got)
    hu = fb_docs.href_from_url
    r.check("docs: url of an anchor", hu(u"about:blank#limits") == u"#limits")
    r.check("docs: url of a relative link", hu(u"about:docs/en/MecwayFreebody.md") ==
            u"docs/en/MecwayFreebody.md")
    r.check("docs: url of the web", hu(u"https://mecway.com/") == u"https://mecway.com/")


def test_docs_version(r):
    """One version, in fb_core: the newest heading of the CHANGELOG and the
    README name it, the copied table too."""
    import fb_core
    import fb_gui
    version = fb_core.VERSION
    r.check("version: as the other tools, V<year>.<n>",
            re.match(u"^V20[0-9]{2}\\.[1-9][0-9]*$", version) is not None, version)
    heads = [line for line in _read(u"../CHANGELOG.md").splitlines() if line.startswith(u"## ")]
    r.check("version: newest in the CHANGELOG",
            heads and heads[0].startswith(u"## " + version + u" "), heads[:1])
    r.check("version: in the README", re.search(u"(?<![0-9.])" + re.escape(version) +
                                                 u"(?![0-9])", _read(u"../README.md")))


def test_docs_real_documents(r):
    """The real guides and README: they convert, and every link leads somewhere:
    a .md link to a document, an anchor to a heading of the target."""
    rels = [u"MecwayFreebody.md", u"en/MecwayFreebody.md", u"../README.md"]
    ids = {}
    for rel in rels:
        html = fb_docs.doc_html(rel, "en")
        found = _IDS.findall(html)
        ids[rel] = set(found)
        r.check("docs: converts " + rel, u"not found" not in html and len(found) >= 5, found)
        r.check("docs: ids unique " + rel, len(found) == len(set(found)))
        plain = re.sub(u"<pre>.*?</pre>|<code>.*?</code>", u"", html, flags=re.DOTALL)
        r.check("docs: no Markdown left " + rel,
                u"**" not in plain and u"](" not in plain and u"\n|" not in plain and
                u"__" not in plain, [m for m in (u"**", u"](", u"\n|", u"__") if m in plain])
        uneven = []
        for table in html.split(u"<table>")[1:]:
            cells = [len(re.findall(u"<t[hd]>", row))
                     for row in re.findall(u"<tr>(.*?)</tr>", table.split(u"</table>")[0])]
            if len(set(cells)) > 1:
                uneven.append(cells)
        r.check("docs: every table row as wide as its head " + rel, not uneven, uneven[:2])
        if rel != u"../README.md":
            r.check("docs: tables in " + rel, html.count(u"<table>") >= 4, html.count(u"<table>"))
            r.check("docs: trademark notice in " + rel,
                    fb_docs.TRADEMARK_NOTICE[0 if rel == u"MecwayFreebody.md" else 1] in
                    html.replace(u"\n", u" "))
    r.check("docs: trademark notice in README",
            fb_docs.TRADEMARK_NOTICE[1] in _read(u"../README.md").replace(u"\n", u" "))
    for rel in rels:
        for href in _MD_LINK.findall(_read(rel)):
            kind, target, anchor = fb_docs.resolve_link(rel, href)
            if href.startswith(u"http"):
                r.check(u"docs: web link {0} in {1}".format(href, rel), kind == "web")
                continue
            if href.split(u"#")[0].lower().endswith(u".md") or href.startswith(u"#"):
                r.check(u"docs: link {0} in {1} leads somewhere".format(href, rel),
                        kind in ("doc", "anchor"), (kind, target, anchor))
            if anchor and kind in ("doc", "anchor"):
                where = rel if kind == "anchor" else target
                if where not in ids:
                    ids[where] = set(_IDS.findall(fb_docs.doc_html(where, "en")))
                r.check(u"docs: anchor {0} in {1}".format(href, rel), anchor in ids[where])
