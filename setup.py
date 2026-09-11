"""Copy the source-controlled console into wheel resources during builds."""
from pathlib import Path
from setuptools import setup
from setuptools.command.build_py import build_py

ASSETS=('example.html','app.js','client.js','timeline.js','operations.js','cloud-ui.js','cloud-console-client.js','style.css')
class Build(build_py):
    def run(self):
        super().run()
        target=Path(self.build_lib)/'connectnow/web'
        target.mkdir(parents=True,exist_ok=True)
        for name in ASSETS:self.copy_file(name,str(target/name))
setup(cmdclass={'build_py':Build})
