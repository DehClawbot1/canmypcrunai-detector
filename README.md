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
accounts. We have applied to SignPath Foundation; no certificate has been granted yet.

This source package excludes the private website, database configuration, Git
history and credentials. Python is distributed under the PSF license; PyInstaller
uses GPL with its bootloader exception. Preserve upstream notices in distributions.

## macOS and Linux detector

Python 3.9 or newer is required. Build the inspectable Python zipapp with `python scripts/release-unix-detector.py`. The Windows executable remains v1.3.2; the Unix detector is v1.4.0.

Run the downloaded paired `.pyz` file with `python3 /path/to/CanMyPCRunAI_<pairing>.pyz`. Keep the same browser tab open. For local inspection without uploading, add `--profile-only`.

Apple Silicon uses shared system memory and Metal. Intel Macs use Ollama CPU inference. Linux reads NVIDIA memory through nvidia-smi and AMD capacity through sysfs; other missing GPU measurements stay unknown. Available RAM on macOS stays unknown. Disk space is measured on --models-dir or OLLAMA_MODELS, or the documented platform default when unset (home/.ollama/models on macOS, /usr/share/ollama/.ollama/models on Linux). No administrator access is requested.

The Unix workflow tests actual Linux, Apple Silicon macOS, and Intel macOS runners. Upload smoke tests use a local loopback receiver and never the production website.

## Try the site before downloading

The maintainer is [Delcio Pedro](https://canmypcrunai.online/about).
You can use a [reference hardware estimate](https://canmypcrunai.online/estimate)
or the [LLM VRAM calculator](https://canmypcrunai.online/llm-vram-calculator)
without running this detector. These are labelled hypothetical configurations,
not measurements of your computer, and they do not increment the completed-scan counter.

For measured hardware, start at the [scan page](https://canmypcrunai.online/scan).
Windows uses the executable; macOS/Linux use the Python archive and the paired
command displayed by the site. Neither detector benchmarks inference speed.

- [How the memory calculation works](https://canmypcrunai.online/methodology)
- [Windows/Linux/macOS setup and troubleshooting](https://canmypcrunai.online/how-to-run-ai-locally#platform-troubleshooting)
- [16 GB Apple Silicon example](https://canmypcrunai.online/guides/apple-silicon-16gb)
- [Report a correction](https://github.com/DehClawbot1/canmypcrunai-detector/issues)

Include the exact model tag, context and a public source when reporting a
requirements issue. Do not post pairing codes, scan credentials or personal
hardware profiles. The SignPath application has been submitted; approval and
signing credentials are still pending. The Windows download remains unsigned.
