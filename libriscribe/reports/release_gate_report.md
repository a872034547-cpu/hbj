# Libriscribe Release Gate Report

- Generated at: `2026-05-10T08:16:26.736387+00:00`
- Project root: `D:\weidong\libriscribe`
- Overall status: **PASS**

## JSON Summary

```json
{
  "generated_at": "2026-05-10T08:16:26.736387+00:00",
  "project_root": "D:\\weidong\\libriscribe",
  "passed": true,
  "steps": [
    {
      "name": "Compile source tree",
      "command": "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python311\\python.exe -m compileall src",
      "passed": true,
      "returncode": 0,
      "duration_seconds": 0.115
    },
    {
      "name": "Run pytest suite",
      "command": "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python311\\python.exe -m pytest -q",
      "passed": true,
      "returncode": 0,
      "duration_seconds": 3.89
    },
    {
      "name": "Practical writing workflow smoke check",
      "command": "C:\\Users\\Administrator\\AppData\\Local\\Programs\\Python\\Python311\\python.exe -c \nimport json\nimport sys\nfrom pathlib import Path\n\nproject_root = Path.cwd()\nsrc_path = project_root / \"src\"\nif str(src_path) not in sys.path:\n    sys.path.insert(0, str(src_path))\n\nexpected_visible = [\n    \"Projects\",\n    \"Sources\",\n    \"Outline\",\n    \"Editor\",\n    \"Prompts\",\n    \"Quality\",\n    \"Exports\",\n    \"AIConfig\",\n]\nexpected_internal = [\n    \"Workspace\",\n    \"Pipeline\",\n    \"Citations\",\n    \"Tools\",\n    \"Settings\",\n    \"Audit\",\n    \"GlobalSettings\",\n]\n\nfrom libriscribe.web import app\n\nnav_pages = list(getattr(app, \"NAV_PAGES\", []))\npage_renderers = getattr(app, \"PAGE_RENDERERS\", {})\nrenderer_keys = list(page_renderers.keys())\n\nmissing_from_nav = [page for page in expected_visible if page not in nav_pages]\nunexpected_visible_internal_pages = [page for page in expected_internal if page in nav_pages]\nexpected_all = expected_visible + expected_internal\nmissing_from_renderers = [page for page in expected_all if page not in page_renderers]\nnon_callable_renderers = [\n    page for page in expected_all\n    if page in page_renderers and not callable(page_renderers[page])\n]\n\nresult = {\n    \"expected_visible_routes\": expected_visible,\n    \"expected_internal_routes\": expected_internal,\n    \"nav_pages\": nav_pages,\n    \"renderer_keys\": renderer_keys,\n    \"missing_from_nav\": missing_from_nav,\n    \"unexpected_visible_internal_pages\": unexpected_visible_internal_pages,\n    \"missing_from_renderers\": missing_from_renderers,\n    \"non_callable_renderers\": non_callable_renderers,\n    \"passed\": not (missing_from_nav or unexpected_visible_internal_pages or missing_from_renderers or non_callable_renderers),\n}\nprint(json.dumps(result, ensure_ascii=False, indent=2))\n\nif not result[\"passed\"]:\n    raise SystemExit(1)\n",
      "passed": true,
      "returncode": 0,
      "duration_seconds": 2.472
    }
  ]
}
```

## Step Results

### 1. Compile source tree

- Command: `C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe -m compileall src`
- Status: **PASS**
- Return code: `0`
- Duration: `0.115s`
- Started at: `2026-05-10T08:16:20.259236+00:00`
- Finished at: `2026-05-10T08:16:20.372985+00:00`

#### stdout

```text
Listing 'src'...
Listing 'src\\libriscribe'...
Listing 'src\\libriscribe\\agents'...
Listing 'src\\libriscribe\\export'...
Listing 'src\\libriscribe\\memory'...
Listing 'src\\libriscribe\\rag'...
Listing 'src\\libriscribe\\services'...
Listing 'src\\libriscribe\\utils'...
Listing 'src\\libriscribe\\web'...
Listing 'src\\libriscribe\\web\\components'...
Listing 'src\\libriscribe\\web\\legacy_pages'...
Listing 'src\\libriscribe\\workflow'...
Listing 'src\\libriscribe.egg-info'...
```

#### stderr

```text
<empty>
```

### 2. Run pytest suite

- Command: `C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe -m pytest -q`
- Status: **PASS**
- Return code: `0`
- Duration: `3.890s`
- Started at: `2026-05-10T08:16:20.372985+00:00`
- Finished at: `2026-05-10T08:16:24.263490+00:00`

#### stdout

```text
............................                                             [100%]
28 passed in 2.11s
```

#### stderr

```text
<empty>
```

### 3. Practical writing workflow smoke check

- Command: `C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe -c 
import json
import sys
from pathlib import Path

project_root = Path.cwd()
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

expected_visible = [
    "Projects",
    "Sources",
    "Outline",
    "Editor",
    "Prompts",
    "Quality",
    "Exports",
    "AIConfig",
]
expected_internal = [
    "Workspace",
    "Pipeline",
    "Citations",
    "Tools",
    "Settings",
    "Audit",
    "GlobalSettings",
]

from libriscribe.web import app

nav_pages = list(getattr(app, "NAV_PAGES", []))
page_renderers = getattr(app, "PAGE_RENDERERS", {})
renderer_keys = list(page_renderers.keys())

missing_from_nav = [page for page in expected_visible if page not in nav_pages]
unexpected_visible_internal_pages = [page for page in expected_internal if page in nav_pages]
expected_all = expected_visible + expected_internal
missing_from_renderers = [page for page in expected_all if page not in page_renderers]
non_callable_renderers = [
    page for page in expected_all
    if page in page_renderers and not callable(page_renderers[page])
]

result = {
    "expected_visible_routes": expected_visible,
    "expected_internal_routes": expected_internal,
    "nav_pages": nav_pages,
    "renderer_keys": renderer_keys,
    "missing_from_nav": missing_from_nav,
    "unexpected_visible_internal_pages": unexpected_visible_internal_pages,
    "missing_from_renderers": missing_from_renderers,
    "non_callable_renderers": non_callable_renderers,
    "passed": not (missing_from_nav or unexpected_visible_internal_pages or missing_from_renderers or non_callable_renderers),
}
print(json.dumps(result, ensure_ascii=False, indent=2))

if not result["passed"]:
    raise SystemExit(1)
`
- Status: **PASS**
- Return code: `0`
- Duration: `2.472s`
- Started at: `2026-05-10T08:16:24.263490+00:00`
- Finished at: `2026-05-10T08:16:26.735387+00:00`

#### stdout

```text
{
  "expected_visible_routes": [
    "Projects",
    "Sources",
    "Outline",
    "Editor",
    "Prompts",
    "Quality",
    "Exports",
    "AIConfig"
  ],
  "expected_internal_routes": [
    "Workspace",
    "Pipeline",
    "Citations",
    "Tools",
    "Settings",
    "Audit",
    "GlobalSettings"
  ],
  "nav_pages": [
    "Projects",
    "Sources",
    "Outline",
    "Editor",
    "Prompts",
    "Quality",
    "Exports",
    "AIConfig"
  ],
  "renderer_keys": [
    "GlobalSettings",
    "Workspace",
    "Projects",
    "Dashboard",
    "Sources",
    "Outline",
    "Pipeline",
    "Editor",
    "Citations",
    "Quality",
    "Prompts",
    "Exports",
    "Tools",
    "Chat",
    "Settings",
    "AIConfig",
    "Audit"
  ],
  "missing_from_nav": [],
  "unexpected_visible_internal_pages": [],
  "missing_from_renderers": [],
  "non_callable_renderers": [],
  "passed": true
}
```

#### stderr

```text
2026-05-10 16:16:25.980 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-05-10 16:16:25.981 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-05-10 16:16:26.506 WARNING streamlit: 
  [33m[1mWarning:[0m to view a Streamlit app on a browser, use Streamlit in a file and
  run it with the following command:

    streamlit run [FILE_NAME] [ARGUMENTS]
2026-05-10 16:16:26.506 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
2026-05-10 16:16:26.507 WARNING streamlit.runtime.scriptrunner_utils.script_run_context: Thread 'MainThread': missing ScriptRunContext! This warning can be ignored when running in bare mode.
```
