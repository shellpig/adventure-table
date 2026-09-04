Adventure Table Standalone — English
====================================

WHAT THIS IS
Adventure Table Standalone is the offline Windows x64 Character Workshop. It
contains Character Builder, Character Sheet, Level Up, Version History,
archive/delete, Traditional Chinese / English switching, and Character JSON
import/export. It does not include Room, Campaign, Session, Seat, Combat,
Timeline, AI Actor, accounts, or online sync.

STARTING AND STOPPING
Run adventure-table.exe. A console window stays open while the local server is
running and your default browser opens automatically. Press Ctrl+C in the
console, or close the console window, to stop Adventure Table. Closing only the
browser tab does NOT stop the local server.

YOUR DATA
By default the database is adventure-table.sqlite3 beside adventure-table.exe.
The launcher prints the exact absolute path, and the Landing page shows the same
path. To move to a new extracted version, copy your existing
adventure-table.sqlite3 into the new folder before starting it. Advanced users
may override the location with ADVENTURE_TABLE_DATABASE_PATH.

IMPORT / EXPORT
Export is available from Character Workshop and Character Sheet. Import is
available from Character Workshop and accepts a character JSON file or pasted
JSON. Web and standalone use the same M03 character exchange format.

IMPORTANT M03 LIMITATION
The Character JSON schema is UNSTABLE during M03. A JSON file exported by this
build is not guaranteed to import into a later build until the schema is locked
at P2. Keep the original standalone folder/database as your durable copy.

PLATFORM
This M03 release is Windows x64 only. It is a portable folder/zip, not an
installer, and it has no automatic updater or code signing.

REPORTING A PROBLEM
When reporting a startup problem, include the console output, the build id shown
in the first line, and whether the database path shown there is writable.
