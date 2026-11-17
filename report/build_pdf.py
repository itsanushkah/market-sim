"""Build report/report.pdf from report/report.md (Markdown -> HTML -> PDF via headless Chrome).

    python report/build_pdf.py

Needs the `markdown` package (in requirements.txt) and Google Chrome or Chromium.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import markdown

HERE = Path(__file__).resolve().parent
CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    "google-chrome", "chromium", "chromium-browser",
]

CSS = """
@page { size: Letter; margin: 0.8in 0.8in 0.85in 0.8in;
        @bottom-center { content: counter(page); font-size: 9pt; color: #666; } }
body { font-family: "Charter", "Georgia", serif; font-size: 10.5pt; line-height: 1.42; color: #111; }
h1.title { font-size: 20pt; margin: 0 0 4pt; line-height: 1.2; }
p.subtitle { font-size: 12.5pt; color: #444; margin: 0 0 10pt; }
.titleblock { border-top: 1.5px solid #222; border-bottom: 1.5px solid #222; padding: 6pt 0; margin-bottom: 12pt; }
.titleblock p { margin: 2pt 0; font-size: 10pt; text-align: left; }
.titleblock .course { font-weight: bold; }
h2 { font-size: 14pt; margin: 18pt 0 6pt; border-bottom: 1px solid #ccc; padding-bottom: 2pt; break-after: avoid; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; break-after: avoid; }
h4 { font-size: 10.5pt; margin: 10pt 0 4pt; font-style: italic; break-after: avoid; }
p { margin: 0 0 6pt; text-align: justify; hyphens: auto; }
ul, ol { margin: 0 0 6pt; padding-left: 18pt; } li { margin-bottom: 2pt; }
table { border-collapse: collapse; margin: 8pt auto 10pt; font-size: 8.8pt; break-inside: avoid; }
th, td { border-top: 0.5px solid #bbb; border-bottom: 0.5px solid #bbb; padding: 3pt 6pt; text-align: left; vertical-align: top; }
th { background: #f0f3f8; font-weight: bold; }
code { font-family: "Menlo", monospace; font-size: 8.6pt; background: #f4f4f4; padding: 0 2px; }
pre { background: #f6f6f6; padding: 6pt 8pt; font-size: 8.4pt; break-inside: avoid; white-space: pre-wrap; }
pre code { background: none; padding: 0; }
figure { margin: 10pt auto 12pt; text-align: center; break-inside: avoid; }
figure img { max-width: 100%; }
figcaption { font-size: 8.8pt; color: #333; text-align: left; margin-top: 4pt; line-height: 1.3; }
"""


def md_to_html(text: str) -> str:
    title = subtitle = ""
    m = re.match(r"---\n(.*?)\n---\n", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            k, _, v = line.partition(":")
            v = v.strip().strip('"')
            if k.strip() == "title":
                title = v
            elif k.strip() == "subtitle":
                subtitle = v
        text = text[m.end():]

    # ![caption](path){width=NN%}  ->  <figure>
    def fig(mt: re.Match) -> str:
        cap, src, width = mt.group(1), mt.group(2), mt.group(3) or "100%"
        cap_html = markdown.markdown(cap.replace("*", "\\*")).removeprefix("<p>").removesuffix("</p>")
        return (f'\n<figure><img src="{src}" style="width:{width}">'
                f"<figcaption>{cap_html}</figcaption></figure>\n")
    text = re.sub(r"!\[(.+?)\]\((\S+?)\)(?:\{width=(\d+%)\})?", fig, text)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "md_in_html"])
    head = f'<h1 class="title">{title}</h1>' + (f'<p class="subtitle">{subtitle}</p>' if subtitle else "")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>"
            f"<style>{CSS}</style></head><body>{head}{body}</body></html>")


def main() -> None:
    src = HERE / "report.md"
    html = HERE / "report.html"
    pdf = HERE / "report.pdf"
    html.write_text(md_to_html(src.read_text()))
    chrome = next((c for c in CHROME_CANDIDATES if Path(c).exists() or shutil.which(c)), None)
    if chrome is None:
        sys.exit(f"wrote {html}; no Chrome found, open it in a browser and print to PDF")
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", html.as_uri()], check=True, capture_output=True)
    print(f"wrote {pdf}")


if __name__ == "__main__":
    main()
