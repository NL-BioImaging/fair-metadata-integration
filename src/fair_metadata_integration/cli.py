"""Command line interface: write a Workflow Run Crate for a run of a bilayers workflow."""
import argparse

from .metadata_integration import create_ro_crate


def parse_args(args=None):
    parser = argparse.ArgumentParser(
        prog='create-ro-crate',
        description='Write a Workflow Run Crate describing a run of a Bilayers workflow.')
    parser.add_argument('dest_path', help='folder the crate is written to, created if it does not exist')
    parser.add_argument('workflow_schema', help='the Bilayers config.yaml describing the workflow')
    parser.add_argument('-i', '--input', dest='input_paths', nargs='+', default=[], metavar='PATH',
                        help='the data the run consumed (e.g. an OME-Zarr folder or a TIFF file)')
    parser.add_argument('-o', '--output', dest='output_paths', nargs='+', default=[], metavar='PATH',
                        help='the data the run produced')
    parser.add_argument('-m', '--metadata', dest='metadata_paths', nargs='+', default=[], metavar='PATH',
                        help='further files describing the data, copied into the crate')
    parser.add_argument('-p', '--parameters', metavar='PATH',
                        help="YAML or JSON file of the values the run gave the workflow's parameters")
    parser.add_argument('--copy-inputs', action='store_true',
                        help='copy inputs outside the crate into it, rather than referencing them')
    parser.add_argument('--copy-outputs', action='store_true',
                        help='copy outputs outside the crate into it, rather than referencing them')
    parser.add_argument('--gen-preview', action=argparse.BooleanOptionalAction, default=True,
                        help='write ro-crate-preview.html (default: yes)')
    return parser.parse_args(args)


def main(args=None):
    args = parse_args(args)
    create_ro_crate(args.dest_path, args.workflow_schema, args.input_paths, args.output_paths, args.metadata_paths,
                    parameters=args.parameters, copy_inputs=args.copy_inputs, copy_outputs=args.copy_outputs,
                    gen_preview=args.gen_preview)
    print(f'RO-Crate written to {args.dest_path}')


if __name__ == '__main__':
    main()
