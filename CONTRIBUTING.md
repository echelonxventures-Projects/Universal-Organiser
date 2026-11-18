# Contributing

- **Standard library only.** The engine must run with a plain Python 3.9+ on macOS, Windows and Linux.
- **System differences** belong in `engine/platforms.py`; everything else asks it.
- **Never personal data.** Use neutral examples ("Alex Example", "Sam Example"). The privacy check runs before each
  commit and push once you set `git config core.hooksPath .githooks`; it reads names from your own local profile and
  never writes them anywhere.
- **Anything that changes files** must be a preview the person approves, logged, and undoable.
- **Tests:** `python3 -m unittest discover -s tests -v`. Tests use throwaway data folders (`UO_DATA`) and an unencrypted
  catalogue, so they never touch a real install.
- **Accessible pages.** Every field needs a label (or `aria-label`), every button readable text (or `aria-label`), and
  anything clickable must be a link or button, or reachable with Tab (`engine/a11y.js` handles rows and tiles the pages
  build in script). Keep colours as tokens on `:root` with a dark-mode set; `python3 tools/a11y_check.py` checks text
  contrast (4.5:1) and the rest.
- **Installers:** after changing `install/`, try one locally:
  `sh install/install.sh --dir /tmp/uo-try --yes --no-start --no-link && python3 tools/install_smoke.py /tmp/uo-try first`.

## Adding a country pack

Copy `profiles/regions/india.json` to `profiles/regions/<country>.json` and change:

- `doc_types_insert`: the country's documents (`name`, words in the text `any_text` / `all_text`, words in the file
  name `any_name`, and `tags` such as `id`, `holder`, `dob`, `important`, `paper`, `money`, `tax`), each placed `before`
  an existing type.
- `doc_types_replace`: replace a built-in type with a country version.
- `set`: anything else, e.g. `insights.year_start_month` (tax year), `insights.expected_docs`, search words, speech
  languages for transcripts.
- `topic_keywords_extra`: extra words for the built-in topics (local bank names, tax forms).

Run the tests, then open a pull request.
