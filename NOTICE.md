# Authorship and licence

Copyright 2026 David Nelson-Elske, for his original contributions.
Apache License 2.0 applies to the original material where the contributors hold the required rights.
Read LICENSE for the terms.

## Third-party components

`dictate` invokes the OpenAI transcription API at runtime.
It bundles no OpenAI code and includes no API key.
Use of that service is governed by OpenAI's terms, and it is billed to the account that supplies the key.

`dictate` requires the following programs to be installed separately.
They are not distributed here and retain their own licences:

| Program | Used for | Licence |
| --- | --- | --- |
| SoX (`sox`, `rec`, `soxi`) | Recording and audio inspection | GPL-2.0 / LGPL-2.1 |
| `curl` | HTTPS requests | curl licence (MIT-like) |
| `jq` | JSON parsing | MIT |
| `xdotool` | Window focus and keystrokes | MIT |
| `xclip` | Clipboard access | GPL-2.0 |
| `notify-send` | Desktop notifications | part of libnotify, LGPL-2.1 |

The test suite downloads a short public-domain speech sample from the
`ggerganov/whisper.cpp` repository at run time.
That sample is not redistributed here.

## No warranty

These tools are provided as-is, without warranty of any kind.
In particular, `dictate` sends audio of your voice to a third-party API.
Read `tools/dictate/README.md` before using it for anything sensitive.
