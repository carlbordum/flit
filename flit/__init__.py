"""A simple packaging tool for simple packages."""
import argparse
import configparser
import hashlib
import logging
import os
import pathlib
import shutil
import sys
import zipfile

from . import common
from . import inifile
from .log import enable_colourful_output

__version__ = '0.2'

log = logging.getLogger(__name__)

wheel_file_template = """\
Wheel-Version: 1.0
Generator: flit {version}
Root-Is-Purelib: true
""".format(version=__version__)

def wheel(ini_path, upload=None, verify_metadata=None):
    """Build a wheel from a module/package
    """
    directory = ini_path.parent
    ini_info = inifile.read_pkg_ini(ini_path)

    build_dir = directory / 'build' / 'flit'
    try:
        build_dir.mkdir(parents=True)
    except FileExistsError:
        shutil.rmtree(str(build_dir))
        build_dir.mkdir()

    target = common.Module(ini_info['module'], directory)

    # Copy module/package to build directory
    if target.is_package:
        ignore = shutil.ignore_patterns('*.pyc', '__pycache__')
        shutil.copytree(str(target.path), str(build_dir / target.name), ignore=ignore)
    else:
        shutil.copy2(str(target.path), str(build_dir))

    md_dict = {'name': target.name, 'provides': [target.name]}
    md_dict.update(common.get_info_from_module(target))
    md_dict.update(ini_info['metadata'])
    metadata = common.Metadata(md_dict)

    dist_version = metadata.name + '-' + metadata.version
    py2_support = not (metadata.requires_python or '').startswith(('3', '>3', '>=3'))

    dist_info = build_dir / (dist_version + '.dist-info')
    dist_info.mkdir()

    # Write entry points
    if ini_info['scripts']:
        cp = configparser.ConfigParser()
        cp['console_scripts'] = {k: '%s:%s' % v
                                 for (k,v) in ini_info['scripts'].items()}
        log.debug('Writing entry_points.txt in %s', dist_info)
        with (dist_info / 'entry_points.txt').open('w') as f:
            cp.write(f)

    with (dist_info / 'WHEEL').open('w') as f:
        f.write(wheel_file_template)
        if py2_support:
            f.write("Tag: py2-none-any\n")
        f.write("Tag: py3-none-any\n")

    with (dist_info / 'METADATA').open('w') as f:
        metadata.write_metadata_file(f)

    # Generate the record of the files in the wheel
    records = []
    for dirpath, dirs, files in os.walk(str(build_dir)):
        reldir = os.path.relpath(dirpath, str(build_dir))
        for f in files:
            relfile = os.path.join(reldir, f)
            file = os.path.join(dirpath, f)
            h = hashlib.sha256()
            with open(file, 'rb') as fp:
                h.update(fp.read())
            size = os.stat(file).st_size
            records.append((relfile, h.hexdigest(), size))

    with (dist_info / 'RECORD').open('w') as f:
        for path, hash, size in records:
            f.write('{},sha256={},{}\n'.format(path, hash, size))
        # RECORD itself is recorded with no hash or size
        f.write(dist_version + '.dist-info/RECORD,,\n')

    # So far, we've built the wheel file structure in a directory.
    # Now, zip it up into a .whl file.
    dist_dir = target.path.parent / 'dist'
    try:
        dist_dir.mkdir()
    except FileExistsError:
        pass
    tag = ('py2.' if py2_support else '') + 'py3-none-any'
    filename = '{}-{}.whl'.format(dist_version, tag)
    with zipfile.ZipFile(str(dist_dir / filename), 'w',
                         compression=zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirs, files in os.walk(str(build_dir)):
            reldir = os.path.relpath(dirpath, str(build_dir))
            for file in files:
                z.write(os.path.join(dirpath, file), os.path.join(reldir, file))

    log.info("Created %s", dist_dir / filename)

    if verify_metadata is not None:
        from .upload import verify
        verify(metadata, verify_metadata)

    if upload is not None:
        from .upload import do_upload
        do_upload(dist_dir / filename, metadata, upload)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('-f', '--ini-file', type=pathlib.Path, default='flit.ini')
    subparsers = ap.add_subparsers(title='subcommands', dest='subcmd')

    parser_wheel = subparsers.add_parser('wheel')
    parser_wheel.add_argument('--upload', action='store', nargs='?',
                              const='pypi', default=None,
          help="Upload the built wheel to PyPI"
    )
    parser_wheel.add_argument('--verify-metadata', action='store', nargs='?',
                              const='pypi', default=None,
          help="Verify the package metadata with the PyPI server"
    )

    parser_install = subparsers.add_parser('install')
    parser_install.add_argument('--symlink', action='store_true',
        help="Symlink the module/package into site packages instead of copying it"
    )

    args = ap.parse_args(argv)

    enable_colourful_output()

    if args.subcmd == 'wheel':
        wheel(args.ini_file, upload=args.upload,
              verify_metadata=args.verify_metadata)
    elif args.subcmd == 'install':
        from .install import Installer
        Installer(args.ini_file, symlink=args.symlink).install()
    else:
        sys.exit('No command specified')

if __name__ == '__main__':
    main()