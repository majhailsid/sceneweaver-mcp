"""Explicit setup and a stdio-only server; no web application is launched."""
import argparse
import json

from . import __version__


def main():
    parser=argparse.ArgumentParser(prog='sceneweaver-mcp')
    parser.add_argument('command',nargs='?',default='serve',choices=['serve','doctor','setup-voice','version'])
    args=parser.parse_args()
    if args.command=='version':print(__version__);return
    if args.command=='doctor':
        from .server import capabilities
        print(json.dumps(capabilities(),indent=2));return
    if args.command=='setup-voice':
        from .audio import setup_voice
        print(json.dumps(setup_voice(),indent=2));return
    from .server import serve
    serve()


if __name__=='__main__':main()
