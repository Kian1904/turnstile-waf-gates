#!/usr/bin/env python3
"""setup.py — one-command installer for turnstile-waf-gates.

Detects the platform and installs the browser + sets up the PATH.

Usage:
  python3 setup.py              # auto-detect and install
  python3 setup.py --check      # check what's installed
  python3 setup.py --browser    # install chromium only
"""
import os
import platform
import shutil
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.expanduser("~/.local/bin")


def detect_platform():
    """Return (os_name, package_manager, install_cmd)."""
    system = platform.system().lower()

    if system == "linux":
        # Check if Termux
        if os.path.isdir("/data/data/com.termux/files/usr"):
            return ("termux", "pkg", ["pkg", "install", "-y", "chromium"])

        # Check for apt
        if shutil.which("apt"):
            return ("debian", "apt", ["apt", "install", "-y", "chromium"])

        # Check for dnf
        if shutil.which("dnf"):
            return ("fedora", "dnf", ["dnf", "install", "-y", "chromium"])

        # Check for pacman
        if shutil.which("pacman"):
            return ("arch", "pacman", ["pacman", "-S", "--noconfirm", "chromium"])

        return ("linux-unknown", None, None)

    elif system == "darwin":
        if shutil.which("brew"):
            return ("macos", "brew",
                    ["brew", "install", "--cask", "google-chrome"])
        return ("macos", None, None)

    elif system == "windows":
        return ("windows", "winget",
                ["winget", "install", "Google.Chrome"])

    return (system, None, None)


def find_browser():
    """Auto-detect Chrome/Chromium on the system."""
    # Termux
    for p in [
        "/data/data/com.termux/files/usr/lib/chromium/chrome",
        "/data/data/com.termux/files/usr/bin/chromium",
    ]:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p

    # Linux
    for name in ["google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome"]:
        p = shutil.which(name)
        if p:
            return p

    # macOS
    for p in [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]:
        if os.path.isfile(p):
            return p

    # Windows
    for p in [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
    ]:
        if os.path.isfile(p):
            return p

    return None


def install_browser(install_cmd):
    """Install chromium via the platform's package manager."""
    if not install_cmd:
        print("Cannot auto-install browser on this platform.")
        print("Please install Chrome or Chromium manually.")
        return False

    print(f"Installing browser: {' '.join(install_cmd)}")
    try:
        subprocess.run(install_cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"Install failed: {e}", file=sys.stderr)
        return False
    except FileNotFoundError:
        print(f"Package manager not found for: {install_cmd[0]}", file=sys.stderr)
        return False


def link_scripts():
    """Symlink scripts into ~/.local/bin (or Windows Scripts dir)."""
    os.makedirs(BIN_DIR, exist_ok=True)

    scripts = ["clean-fp-chrome", "fp-audit", "turnstile-solve",
               "solver-api.py", "awswaf-solve"]
    linked = []

    for script in scripts:
        src = os.path.join(SCRIPTS_DIR, script)
        if not os.path.isfile(src):
            continue

        # Make executable
        os.chmod(src, 0o755)

        dst = os.path.join(BIN_DIR, script)
        # Remove old link if exists
        if os.path.lexists(dst):
            os.remove(dst)

        try:
            os.symlink(src, dst)
            linked.append(script)
        except OSError:
            # Windows: copy instead
            shutil.copy2(src, dst)
            linked.append(script)

    return linked


def check_install():
    """Check what's installed."""
    print("=== turnstile-waf-gates setup check ===\n")

    os_name, pkg_mgr, install_cmd = detect_platform()
    print(f"Platform:    {os_name}")
    print(f"Package mgr: {pkg_mgr or 'none'}")

    browser = find_browser()
    if browser:
        print(f"Browser:     {browser}")
    else:
        print("Browser:     NOT FOUND")
        if install_cmd:
            print(f"  → install with: {' '.join(install_cmd)}")

    linked = []
    for script in ["clean-fp-chrome", "fp-audit", "turnstile-solve",
                   "solver-api.py", "awswaf-solve"]:
        src = os.path.join(SCRIPTS_DIR, script)
        dst = os.path.join(BIN_DIR, script)
        if os.path.isfile(src):
            status = "linked" if os.path.lexists(dst) else "not linked"
            print(f"  {script:20s} {status}")

    # Check PATH
    path_env = os.environ.get("PATH", "")
    if BIN_DIR not in path_env:
        print(f"\n⚠ {BIN_DIR} not in PATH.")
        print(f"  Add to ~/.bashrc or ~/.zshrc:")
        print(f"    export PATH=\"{BIN_DIR}:$PATH\"")

    if browser:
        print("\n✅ Ready to use. Run: clean-fp-chrome && fp-audit")
    else:
        print("\n❌ Install a browser first, then re-run: python3 setup.py")

    return browser is not None


def main():
    if "--check" in sys.argv:
        check_install()
        return

    if "--browser" in sys.argv:
        os_name, pkg_mgr, install_cmd = detect_platform()
        if install_cmd:
            install_browser(install_cmd)
        else:
            print("Cannot auto-install. Please install Chrome/Chromium manually.")
        return

    print("=== turnstile-waf-gates setup ===\n")

    # 1. Detect platform
    os_name, pkg_mgr, install_cmd = detect_platform()
    print(f"Platform: {os_name}")

    # 2. Check/install browser
    browser = find_browser()
    if browser:
        print(f"Browser:  {browser} ✅")
    else:
        print("Browser:  NOT FOUND")
        if install_cmd:
            print(f"  Installing: {' '.join(install_cmd)}")
            if install_browser(install_cmd):
                browser = find_browser()
                if browser:
                    print(f"  Browser: {browser} ✅")
        if not browser:
            print("\n❌ No browser found. Install Chrome or Chromium manually,")
            print("   then re-run: python3 setup.py")
            sys.exit(1)

    # 3. Link scripts
    linked = link_scripts()
    print(f"Scripts:  linked {len(linked)} scripts to {BIN_DIR}")

    # 4. Check PATH
    path_env = os.environ.get("PATH", "")
    if BIN_DIR not in path_env:
        print(f"\n⚠ Add to your shell profile (~/.bashrc or ~/.zshrc):")
        print(f'    export PATH="{BIN_DIR}:$PATH"')
        print(f"  Then run: source ~/.bashrc  (or ~/.zshrc)")

    print("\n✅ Setup complete. Quick start:")
    print("    clean-fp-chrome")
    print("    fp-audit")
    print("    turnstile-solve --url https://target.example/login")


if __name__ == "__main__":
    main()