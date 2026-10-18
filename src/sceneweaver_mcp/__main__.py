"""Explicit setup and a stdio-only server; no web application is launched."""
import argparse
import json

from . import __version__


def main():
    parser=argparse.ArgumentParser(prog='sceneweaver-mcp')
    parser.add_argument('command',nargs='?',default='serve',choices=['serve','doctor','setup-voice','version','clients','connect'])
    parser.add_argument('--client',choices=['codex','cursor','claude-desktop'])
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if (args.client or args.dry_run) and args.command!='connect':parser.error('--client and --dry-run require connect')
    if args.command in ('clients','connect'):
        from .clients import discover,connect,wizard
        try:
            if args.command=='clients' or (args.dry_run and not args.client):result=discover()
            elif args.client:result=connect(args.client,args.dry_run)
            else:result=wizard()
        except (OSError,ValueError) as exc:
            parser.exit(1, f'Client setup failed: {exc if isinstance(exc,ValueError) else type(exc).__name__}. Existing backups are kept; inspect local files before retrying.\n')
        print(json.dumps(result,indent=2));return
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
