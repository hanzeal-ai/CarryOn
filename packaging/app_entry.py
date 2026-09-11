"""Finder launcher; the same executable also hosts its detached service child."""
import contextlib
import html
import io
import sys
import webbrowser
from connectnow.cli import main
from connectnow.paths import state_dir, private_dir

if len(sys.argv)>1:
    raise SystemExit(main())
output=io.StringIO()
with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
    result=main(['start'])
if result:
    path=private_dir(state_dir())/'startup-error.html'
    path.write_text('<!doctype html><meta charset="utf-8"><title>ConnectNow 启动失败</title>'
        '<h1>ConnectNow 启动失败</h1><pre>'+html.escape(output.getvalue())+'</pre>')
    webbrowser.open(path.as_uri())
raise SystemExit(result)
