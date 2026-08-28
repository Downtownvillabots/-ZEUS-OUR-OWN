# DOWNTOWN VILLA Features

Every major feature gets its own directory.

Example future structure:

functions/
├── start/
├── help/
├── runtime_test/
├── search/
├── media/
├── imdb/
├── spell_check/
├── rename/
├── indexing/
├── admin/
├── statistics/
├── backup/
└── premium/

A feature should expose a clear `register(runtime)` entry point.

Do not put database implementation, Telegram client construction, or unrelated
feature code inside another feature's folder.
