# Wiki source (reviewed)

This directory is the **reviewed source of truth** for the GitHub Wiki. A wiki page changes in
the same pull request as the behaviour it documents, so reviewers see both together.

- Edit pages here, then publish with `python scripts/sync_wiki.py --push`.
- Pull remote edits back with `python scripts/sync_wiki.py --pull`.
- `_Sidebar.md` and `_Footer.md` are part of the published wiki; every page must be listed in
  the sidebar (checked in CI by `scripts/check_docs_links.py`).
- Page names use GitHub wiki conventions (`Quick-Start.md` → `/wiki/Quick-Start`).
