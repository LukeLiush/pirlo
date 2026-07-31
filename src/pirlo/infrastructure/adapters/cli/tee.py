import os
import sys


def main():
    if len(sys.argv) < 2:
        print(
            "Usage: python -m pirlo.infrastructure.adapters.cli.tee <output_file>",
            file=sys.stderr,
        )
        sys.exit(1)

    output_file_path = sys.argv[1]

    # Ensure the parent directories exist
    os.makedirs(os.path.dirname(os.path.abspath(output_file_path)), exist_ok=True)

    try:
        # Read raw bytes to ensure compatibility with all console encodings and ignore line ending variations
        with open(output_file_path, "wb") as f:
            while True:
                chunk = sys.stdin.buffer.read(4096)
                if not chunk:
                    break

                # Write to log file
                f.write(chunk)
                f.flush()

                # Write to console stdout
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
    except Exception as e:  # noqa: BLE001
        print(f"\n[tee.py Error] Failed to redirect logs: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
