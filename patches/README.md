# Offline engine patches

`poke_engine_0_0_48_critstats_v1.patch` applies only to the locked poke-engine 0.0.48 PyPI
source archive, SHA256 `070010686f2aedff11e25137e696e301ccd80fd57c805d255464067fc905ca12`.
It corrects critical offensive-stat/Unaware selection and adds a 16-case Rust stat-selection
regression. It is an experimental offline variant, not a replacement for the reproduced baseline.

`poke_engine_0_0_48_jointfix_v1.patch` is a **cumulative alternative**, applied directly to the same
unchanged archive (do not apply both patches). It retains the critical-stat fix, isolates mutable
choices between speed-tie orders, and corrects ordinary move recovery, Showdown fixed-point weather
recovery and the Helmet fraction. Weather recovery is not replaced with exact mathematical 2/3. Two
upstream weather-healing expectations change from 66 to 67 at 100 max HP in the Gen 9 build; the
Showdown fixed-point path produces that amount. Its wheel is retained under `.artifacts/conformance/engine/`
and installed only in `.venvs/engine-jointfix-v1`. Both patches retain the license below.

The patch and its upstream context are distributed under the upstream MIT license below. This
does not choose a license for the whole PokeForge project or for the separate GPL FoulPlay boundary.
The full upstream tree is extracted in a separate temporary directory, not vendored into this repo.

## Upstream license notice

MIT License

Copyright (c) 2024 pmariglia

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
