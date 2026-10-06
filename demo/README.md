# GUI demo (GitHub Pages)

`build.py` renders the real web interface (the FastAPI routes and Jinja2 templates in `frontend/`) against a mock backend filled with the sample data in `demo_data.py`, and writes static HTML to `docs/`. GitHub Pages serves that folder.

The demo behaves like the application, with these differences:

- All data comes from `demo_data.py`: instruments, instrument models, runs with their status histories, directory-stability folders, settings (the real defaults from the backend), containers and log lines.
- Links are relative, so the site works under any path.
- The JSON endpoints that pages poll (run history, containers, logs, version check) are written as files under `docs/api/`.
- Buttons and forms do nothing; a short message says that actions are disabled. Run filters link to pre-rendered pages for the filters used on the dashboard and for each instrument.

## Rebuild

From the repository root, with the frontend requirements installed:

```bash
pip install -r frontend/requirements.txt
python demo/build.py          # writes docs/
```

Rebuild after changing templates, routes or sample data, and commit `docs/` with the change. Timestamps are generated relative to the build time, so the dashboard charts show the last 14 days as of the build.

## Publish

In the repository settings, under **Pages**, choose **Deploy from a branch**, branch `main`, folder `/docs`.
