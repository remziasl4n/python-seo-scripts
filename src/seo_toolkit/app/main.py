"""Dashboard entry point: `uv run seo app`, then open http://localhost:8501.

Pages: Home, Setup and Results, plus one page per tool, grouped like the tools folder.
"""

import streamlit as st

from seo_toolkit.app import views
from seo_toolkit.tools.base import GROUPS, discover

st.set_page_config(page_title="SEO Toolkit", page_icon=":material/travel_explore:", layout="wide")

pages: dict[str, list] = {
    "Overview": [
        st.Page(views.home, title="Home", icon=":material/home:", url_path="home", default=True),
        st.Page(views.setup, title="Setup", icon=":material/settings:", url_path="setup"),
        st.Page(views.results, title="Results", icon=":material/folder_open:", url_path="results"),
    ]
}
for tool in discover().values():
    pages.setdefault(GROUPS[tool.group], []).append(
        st.Page(views.tool_page(tool), title=tool.title, url_path=tool.id.replace("/", "-"))
    )

navigation = st.navigation(pages)
views.sidebar()
navigation.run()
