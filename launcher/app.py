"""Process Engineering Toolbox launcher.

Run:  streamlit run launcher/app.py

Apps are discovered from apps/<category>/<app>/app.toml, so adding an app
never requires editing this file.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import streamlit as st

from proctoolbox_core.ui import CATEGORIES, STATUS_LABELS

ROOT = Path(__file__).resolve().parent.parent
APPS_DIR = ROOT / "apps"

st.set_page_config(
    page_title="Process Engineering Toolbox", page_icon=str(ROOT / "desktop" / "toolbox.png"), layout="wide",
)


def discover_apps() -> dict[str, list[dict]]:
    """Map category id -> list of app manifests, in CATEGORIES order."""
    found: dict[str, list[dict]] = {c: [] for c in CATEGORIES}
    for manifest in sorted(APPS_DIR.glob("*/*/app.toml")):
        with manifest.open("rb") as f:
            meta = tomllib.load(f)
        if meta.get("category") not in found:
            continue
        meta["entry_path"] = manifest.parent / meta.get("entry", "app.py")
        found[meta["category"]].append(meta)
    for apps in found.values():
        apps.sort(key=lambda m: (m.get("status") != "available", m["name"]))
    return found


apps_by_cat = discover_apps()
pages: dict[str, st.Page] = {}
for cat_apps in apps_by_cat.values():
    for meta in cat_apps:
        suffix = "" if meta.get("status") == "available" else " (planned)"
        pages[meta["id"]] = st.Page(
            str(meta["entry_path"]), title=meta["name"] + suffix, url_path=meta["id"],
        )


def home() -> None:
    st.title("Process Engineering Toolbox")
    st.caption("Self-hosted engineering calculation apps · FOSS only")
    cats = list(CATEGORIES.items())
    for row in range(0, len(cats), 3):
        cols = st.columns(3)
        for col, (cat_id, cat_name) in zip(cols, cats[row:row + 3]):
            with col, st.container(border=True):
                st.markdown(f"##### {cat_name}")
                apps = apps_by_cat[cat_id]
                if not apps:
                    st.caption("No apps scoped yet.")
                for meta in apps:
                    status = STATUS_LABELS.get(meta.get("status", ""), meta.get("status", ""))
                    st.page_link(pages[meta["id"]], label=f"{meta['name']}  ·  {status}")
                    if meta.get("description"):
                        st.caption(meta["description"])


nav: dict[str, list[st.Page]] = {"": [st.Page(home, title="Home", default=True)]}
for cat_id, cat_apps in apps_by_cat.items():
    if cat_apps:
        nav[CATEGORIES[cat_id]] = [pages[m["id"]] for m in cat_apps]

st.navigation(nav).run()
