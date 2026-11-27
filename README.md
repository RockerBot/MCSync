# MCSync

## Main CLI Usage (all commands from repo root)

Start the server with sync handling
```sh
python -m mcsync.cli server start
```

For usage
```sh
python -m mcsync.cli --help
```

## Test Commands (all from repo root)

Run the integration tests
```sh
python -m unittest discover -v
```

Run the unit tests
```sh
python -m unittest discover -s tests -v
```

Run checkpoint tests
```sh
python -m scripts.test_checkpoint -c 'main()'
```

Run a single unit test (examples)
```sh
python -m unittest tests.test_checkpoint.CheckpointTests.test_checkpoint_stops_snapshots_and_restarts -v
python -m unittest tests.test_snapshots.SnapshotTests.test_create_and_verify_snapshot -v
```

## What the local server directory should have

- mods
- world data
- run.bat
- eula.txt
- ops.json
- server.properties
- user_jvm_args.txt

## Open issues / TODO

(We'll move to GitHub issues only if it's REALLY needed)

- [x] Snapshots aren't getting created
	They get created through scripts/test_checkpoint.py
- [x] Checkpoint unit tests don't call the actual snapshot creation functions. They only mock them (even though the actual function is imported)
	It doesn't get called because there's a @patch on the unit test for that function.
- [ ] Snapshots don't get created during cli start at regular intervals
- [ ] There is no manual snapshot creation command in the cli
- [ ] Creating a snapshot invokes a stop server command
- [ ] `run.bat` ends the java server but not the batch process on graceful shutdown
	This works sometimes, but now it isn't working after `cli server start`. (Press ctrl+pause/break in this case to exit)
