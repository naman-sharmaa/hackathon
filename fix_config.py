with open('backend/config.py', 'r') as f:
    content = f.read()

fallback = """try:
    from dotenv import load_dotenv

    # Load backend/.env regardless of where the process is launched from.
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:  # pragma: no cover - dotenv is optional at runtime
    pass"""

better_fallback = """try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except Exception:
    import os
    from pathlib import Path
    env_path = Path(__file__).resolve().parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip())"""

if fallback in content:
    content = content.replace(fallback, better_fallback)
    with open('backend/config.py', 'w') as f:
        f.write(content)
        print("Patched config.py")
else:
    print("Could not find fallback to patch")
