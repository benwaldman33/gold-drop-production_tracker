#!/usr/bin/env python3
"""Convert USER_MANUAL.md to a styled PDF."""

import markdown
from weasyprint import HTML

INPUT = "USER_MANUAL.md"
OUTPUT = "USER_MANUAL.pdf"

CSS = """
@page {
    size: letter;
    margin: 0.75in 0.9in;
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-size: 9px;
        color: #888;
        font-family: 'Helvetica Neue', Arial, sans-serif;
    }
    @top-center {
        content: "Gold Drop Production Tracker — User Manual";
        font-size: 9px;
        color: #aaa;
        font-family: 'Helvetica Neue', Arial, sans-serif;
    }
}

body {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 11pt;
    line-height: 1.55;
    color: #1a1a1a;
}

h1 {
    font-size: 26pt;
    color: #9A7230;
    border-bottom: 3px solid #C8963E;
    padding-bottom: 8px;
    margin-top: 0;
    margin-bottom: 6px;
}

h1 + p {
    font-size: 11pt;
    color: #555;
    margin-top: 4px;
}

h2 {
    font-size: 18pt;
    color: #1B1D2E;
    border-bottom: 2px solid #E5C882;
    padding-bottom: 4px;
    margin-top: 28px;
    page-break-after: avoid;
}

h3 {
    font-size: 13pt;
    color: #333;
    margin-top: 18px;
    margin-bottom: 6px;
    page-break-after: avoid;
}

h4 {
    font-size: 11pt;
    color: #555;
    margin-top: 14px;
    margin-bottom: 4px;
}

p {
    margin: 6px 0;
}

ul, ol {
    margin: 6px 0 6px 20px;
    padding-left: 0;
}

li {
    margin-bottom: 3px;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0;
    font-size: 10pt;
    page-break-inside: auto;
}

thead {
    display: table-header-group;
}

tr {
    page-break-inside: avoid;
}

th {
    background-color: #1B1D2E;
    color: #E5C882;
    padding: 7px 10px;
    text-align: left;
    font-weight: 600;
    font-size: 9.5pt;
}

td {
    padding: 6px 10px;
    border-bottom: 1px solid #ddd;
}

tr:nth-child(even) td {
    background-color: #f8f6f1;
}

code {
    background-color: #f0ebe0;
    color: #9A7230;
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 9.5pt;
    font-family: 'Courier New', monospace;
}

pre {
    background-color: #1B1D2E;
    color: #E5C882;
    padding: 12px 16px;
    border-radius: 6px;
    font-size: 9pt;
    line-height: 1.4;
    overflow-x: auto;
    page-break-inside: avoid;
}

pre code {
    background: none;
    color: inherit;
    padding: 0;
}

strong {
    color: #1a1a1a;
}

hr {
    border: none;
    border-top: 1px solid #ddd;
    margin: 24px 0;
}

blockquote {
    border-left: 4px solid #C8963E;
    margin: 10px 0;
    padding: 6px 14px;
    color: #555;
    background-color: #faf7f0;
}
"""

with open(INPUT, "r") as f:
    md_text = f.read()

html_body = markdown.markdown(
    md_text,
    extensions=["tables", "fenced_code", "toc"],
)

full_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><style>{CSS}</style></head>
<body>{html_body}</body>
</html>"""

HTML(string=full_html).write_pdf(OUTPUT)
print(f"Generated {OUTPUT}")
