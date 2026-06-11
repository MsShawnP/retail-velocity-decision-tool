"""
lailara_frame.py — Dash brand frame helper  v1.0.1

Vendor this file alongside lailara-frame.css into your app's project root.

Usage
-----
    from lailara_frame import wrap

    app.layout = wrap(
        layout=html.Div([...]),      # your existing Dash layout unchanged
        tool_name="OTIF Analysis",
        footer_note="Data: Cinderhaven Provisions. Trailing 13 weeks."  # optional
    )

    # Full-bleed layouts (no max-width container):
    app.layout = wrap(
        layout=html.Div([...]),
        tool_name="Competitive Shelf Intelligence",
        no_container=True,
    )

Setup (3 steps)
---------------
    1. Copy lailara-frame.css  →  assets/lailara-frame.css
    2. Copy fonts/             →  assets/fonts/   (keeps @font-face paths working)
    3. Copy lailara_frame.py   →  project root, next to app.py

Dash auto-loads every file in assets/, so no explicit stylesheet link needed.

IDs
---
    No IDs are added by this module. All class names are prefixed `lailara-`,
    which will not collide with your callback targets.
"""

from dash import html


def wrap(layout, tool_name: str, footer_note: str = None, no_container: bool = False):
    """Wrap a Dash layout with the Lailara brand frame.

    Args:
        layout:       Any Dash component or list of components (your existing layout).
        tool_name:    Short name displayed in the header, e.g. "OTIF Analysis".
        footer_note:  Optional one-line disclosure or data-provenance note.
        no_container: If True, layout renders full-bleed (no lailara-container
                      max-width or padding). Use for full-width dashboard layouts.

    Returns:
        html.Div containing the full page: header, wrapped layout, footer.
        Assign to app.layout.
    """
    footer_children = [
        html.P([
            "Built by ",
            html.A(
                "Lailara LLC",
                href="https://lailarallc.com",
                target="_blank",
                rel="noopener",
            ),
        ]),
    ]
    if footer_note:
        footer_children.append(
            html.P(footer_note, className="lailara-footer-note")
        )

    if no_container:
        main_content = html.Main(layout, className="lailara-main")
    else:
        main_content = html.Main(
            html.Div(layout, className="lailara-container"),
            className="lailara-main",
        )

    return html.Div(
        [
            html.Header(
                html.Nav(
                    [
                        html.A(
                            "Lailara LLC",
                            href="https://lailarallc.com",
                            className="lailara-wordmark",
                            target="_blank",
                            rel="noopener",
                        ),
                        html.Span(tool_name, className="lailara-tool-name"),
                    ],
                    className="lailara-nav-inner",
                ),
                className="lailara-header",
            ),
            main_content,
            html.Footer(
                html.Div(footer_children, className="lailara-footer-inner"),
                className="lailara-footer",
            ),
        ],
        className="lailara-page",
    )
