"""Installation helpers bundled with the CLI."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
from .client import Error


def install_browser(with_deps=False):
    command = [sys.executable, '-m', 'playwright', 'install']
    if with_deps:
        command.append('--with-deps')
    command.append('chromium')
    result = subprocess.run(command, stdout=sys.stderr)
    if result.returncode:
        raise Error('浏览器安装失败，请查看上方安装器输出')
    return {'installed': 'chromium'}


def install_skill(destination=None):
    source = Path(sys.prefix) / 'share/bnul/skills/bnu-library'
    if not (source / 'SKILL.md').is_file():
        # Editable development installs may not install data files.
        source = Path(__file__).resolve().parents[2] / 'skills/bnu-library'
    if not (source / 'SKILL.md').is_file():
        raise Error('安装包缺少 skill，请重新安装 bnul')
    target = Path(destination).expanduser() if destination else Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))) / 'skills/bnu-library'
    if target.resolve() == source.resolve():
        return {'installed': str(target)}
    target.mkdir(parents=True, exist_ok=True)
    for relative in ('SKILL.md', 'references/installation.md'):
        dest = target / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / relative, dest)
    return {'installed': str(target)}
