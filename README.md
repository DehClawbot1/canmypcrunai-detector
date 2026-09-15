# CanMyPCRunAI Detector

Source repository: https://github.com/DehClawbot1/canmypcrunai-detector.
License: MIT (see LICENSE).

This portable Windows 10/11 detector reads CPU, physical RAM, GPU memory,
available storage and installed AI runtimes. When launched from a paired download
it uploads that hardware profile over HTTPS to the session the visitor started
at https://canmypcrunai.online. It does not read personal documents or install a
background service. Review the privacy policy at https://canmypcrunai.online/privacy.
Delete the executable to remove it. Run without a pairing code to use local output.

## Build and test

On Windows with Python 3.12.10:

    python -m pip install pyinstaller==6.22.3
    python -m unittest discover -s apps/detector -p "test_*.py"
    python -m PyInstaller --clean --noconfirm canmypcrunai-detector.spec

The output is dist/canmypcrunai-detector.exe. The workflow builds the same source
on GitHub Windows runners. Builds are unsigned until SignPath accepts the project
and signing is configured. Verify SHA-256 independently from any signature.

## Code signing policy

Maintainer and release approver: [DehClawbot1](https://github.com/DehClawbot1). Source changes require review; signing requires explicit
release approval. MFA must be enabled for the maintainer's GitHub and SignPath
accounts. We are applying to SignPath Foundation; no certificate has been granted yet.

This source package excludes the private website, database configuration, Git
history and credentials. Python is distributed under the PSF license; PyInstaller
uses GPL with its bootloader exception. Preserve upstream notices in distributions.

## macOS and Linux detector

Python 3.9 or newer is required. Build the inspectable Python zipapp with `python scripts/release-unix-detector.py`. The Windows executable remains v1.3.2; the Unix detector is v1.4.0.

Run the downloaded paired `.pyz` file with `python3 /path/to/CanMyPCRunAI_<pairing>.pyz`. Keep the same browser tab open. For local inspection without uploading, add `--profile-only`.

Apple Silicon uses shared system memory and Metal. Intel Macs use Ollama CPU inference. Linux reads NVIDIA memory through nvidia-smi and AMD capacity through sysfs; other missing GPU measurements stay unknown. Available RAM on macOS stays unknown. Disk space is measured on OLLAMA_MODELS, or the home volume when unset. No administrator access is requested.

The Unix workflow tests actual Linux, Apple Silicon macOS, and Intel macOS runners. Upload smoke tests use a local loopback receiver and never the production website.
