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

## Adding a language

1. `python3 tools/i18n_extract.py` writes `engine/i18n/en.json`: every English text of the pages and of the server's
   messages (`{0}`, `{1}`… stand for numbers and names).
2. Copy `engine/i18n/hi.json` to `engine/i18n/<code>.json` (`<code>` = the two-letter language code, e.g. `ta`, `bn`, `es`),
   set `"_name"` to the language's own name, and replace each translation. Keep every `{0}`; you may leave out one that
   only adds an English plural ending.
3. `python3 tools/i18n_extract.py --check` shows how many texts are translated and catches broken placeholders. Missing
   texts simply stay in English. The new language appears in the Language menu by itself.

New page text needs no extra step for English; run the extractor afterwards to see what the translations miss.

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
